"""Discrete-event simulator (Part 2).

Virtual clock + heap of events (time, kind, seq, task id).
At equal times COMPLETIONs are processed before ARRIVALs (resources are released first);
`seq` breaks remaining ties, so results are fully deterministic.

step() = process ALL events at the next timestamp, then run one scheduling round.
Playback speed never touches the virtual clock: it only changes how often the UI calls step().
"""
import heapq
from collections import deque
from time import perf_counter

from .gpu_manager import Cluster
from .allocation import best_fit, plan_initial
from .models import PENDING, WAITING, RUNNING, COMPLETED, Task

COMPLETION, ARRIVAL = 0, 1
SPEEDS = (0.5, 1, 2, 5, 10)


def fifo_order(waiting, now, cluster=None):
    """Default policy; core/schedulers.py provides FIFO, SJF, IEEE-inspired and proposed."""
    return sorted(waiting, key=lambda t: (t.arrival, t.id))


class Playback:
    """Wall-clock pacing only. interval() is the pause between steps for the UI timer."""
    BASE_SECONDS = 1.0

    def __init__(self):
        self.speed, self.running = 1, False

    def set_speed(self, s):
        if s not in SPEEDS:
            raise ValueError(f"speed must be one of {SPEEDS}")
        self.speed = s

    def interval(self) -> float:
        return self.BASE_SECONDS / self.speed

    def play(self): self.running = True
    def pause(self): self.running = False


class Simulator:
    def __init__(self, tasks, nodes=4, capacity=8000, sizes=None, order=fifo_order):
        self._orig = [t.fresh_copy() for t in tasks]
        self.cfg = {"nodes": nodes, "capacity": capacity, "sizes": sizes}
        self.order = order
        self.reset()

    # ------------------------------------------------------------ lifecycle
    def reset(self):
        self.tasks = {t.id: t.fresh_copy() for t in self._orig}
        self.cluster = Cluster(**self.cfg)
        self.clock, self.seq, self.rounds, self.sched_seconds, self.injected = 0, 0, 0, 0.0, 0
        self.heap, self.waiting, self.running = [], [], set()
        self.log = deque(maxlen=2000)
        self.max_wait, self.wait_sum, self.n_started = 0, 0, 0
        self.area = 0                           # integral of used capacity over virtual time
        self.samples = []                       # (time, used, waiting, running) per step
        for t in self.tasks.values():
            self._push(t.arrival, ARRIVAL, t.id)

    def _push(self, time, kind, tid):
        self.seq += 1
        heapq.heappush(self.heap, (time, kind, self.seq, tid))

    def _log(self, now, event, tid, detail=""):
        self.log.append({"t": now, "event": event, "task": tid, "detail": detail})

    @property
    def done(self) -> bool:
        return not self.heap

    # ------------------------------------------------------------ stepping
    def step(self) -> bool:
        if not self.heap:
            return False
        now = self.heap[0][0]
        self.clock = now
        while self.heap and self.heap[0][0] == now:
            _, kind, _, tid = heapq.heappop(self.heap)
            t = self.tasks[tid]
            if kind == COMPLETION:
                self.cluster.release(tid)
                self.running.discard(tid)
                t.set_status(COMPLETED)
                t.finish = now
                self._log(now, "COMPLETE", tid, "resources released")
            else:
                t.set_status(WAITING)
                self.waiting.append(tid)
                self._log(now, "ARRIVE", tid, f"demand {t.demand}")
        self._dispatch(now)
        if self.samples:
            self.area += self.samples[-1][1] * (now - self.samples[-1][0])
        self.samples.append((now, self.cluster.used, len(self.waiting), len(self.running)))
        return True

    def _dispatch(self, now):
        if not self.waiting:
            return
        t0 = perf_counter()
        ordered = self.order([self.tasks[i] for i in self.waiting], now, self.cluster)
        self.rounds += 1
        for t in ordered:
            part = best_fit(self.cluster, t.demand)
            if part is None:
                continue                         # stays WAITING (may be infeasible)
            self.cluster.allocate(t, part)
            t.set_status(RUNNING)
            t.start = now
            self.max_wait, self.wait_sum, self.n_started = max(self.max_wait, now - t.arrival), self.wait_sum + now - t.arrival, self.n_started + 1
            self.running.add(t.id)
            self._push(now + t.duration, COMPLETION, t.id)
            self._log(now, "START", t.id, f"-> {part.id}")
        self.waiting = [i for i in self.waiting if self.tasks[i].status == WAITING]
        self.sched_seconds += perf_counter() - t0

    def run_until(self, time) -> None:
        while self.heap and self.heap[0][0] <= time:
            self.step()

    def run_all(self) -> None:
        while self.step():
            pass

    # ------------------------------------------------------------ user actions
    def inject(self, demand, duration, priority=2, user=None) -> str:
        if demand <= 0 or duration <= 0:
            raise ValueError("demand and duration must be positive")
        self.injected += 1
        t = Task(id=f"INJ-{self.injected}", demand=int(demand), arrival=self.clock,
                 duration=int(duration), priority=min(3, max(1, int(priority))), user=user)
        self.tasks[t.id] = t
        self._push(self.clock, ARRIVAL, t.id)
        self._log(self.clock, "INJECT", t.id, f"demand {t.demand}, duration {t.duration}")
        return t.id

    def infeasible(self) -> list:
        """Tasks that can never run: larger than the biggest partition."""
        limit = max(p.capacity for p in self.cluster.partitions)
        return [t.id for t in self.tasks.values() if t.demand > limit]

    def plan_snapshot(self, scope="auto") -> dict:
        """Phase 2 visualizer: dry-run grouping/partitioning/allocation (never changes real state).
        auto: the waiting queue; if nothing waits, a preview of the next 15 arriving tasks.
        all : the whole workload (max 100 tasks) on an EMPTY cluster."""
        if scope == "all":
            tasks = sorted(self.tasks.values(), key=lambda t: (t.arrival, t.id))[:100]
            cluster, source = Cluster(**self.cfg), f"whole workload on an empty cluster ({len(tasks)} tasks)"
        else:
            tasks, cluster, source = [self.tasks[i] for i in self.waiting], self.cluster, "waiting queue"
            if not tasks:
                tasks = sorted((t for t in self.tasks.values() if t.status == PENDING),
                               key=lambda t: (t.arrival, t.id))[:15]
                source = "next arriving tasks (preview, nothing is waiting right now)"
        plan = plan_initial([t.fresh_copy() for t in tasks], cluster)
        plan["source"], plan["count"] = source, len(tasks)
        return plan

    def avg_utilization(self):
        """Time-weighted utilization over the run so far (None before the first interval)."""
        if not self.samples or self.clock <= self.samples[0][0]:
            return None
        return round(self.area / (self.cluster.total_capacity * (self.clock - self.samples[0][0])) * 100, 2)

    def state(self, max_rows=200) -> dict:
        waiting = sorted((self.tasks[i] for i in self.waiting), key=lambda t: (t.arrival, t.id))
        counts = {s: 0 for s in ("PENDING", WAITING, RUNNING, COMPLETED)}
        pending, finished = [], []
        for t in self.tasks.values():
            counts[t.status] += 1
            if t.status == PENDING: pending.append(t)
            elif t.status == COMPLETED: finished.append(t)
        upcoming = heapq.nsmallest(30, pending, key=lambda t: (t.arrival, t.id))
        recent = heapq.nlargest(30, finished, key=lambda t: (t.finish, t.id))
        return {"clock": self.clock, "done": self.done, "counts": counts, "avg_utilization": self.avg_utilization(), "max_wait": self.max_wait,
                "avg_wait": round(self.wait_sum / self.n_started, 2) if self.n_started else None,
                "cluster": self.cluster.snapshot(), "wastage": self.cluster.wastage(),
                "waiting": [t.to_dict() for t in waiting[:max_rows]],
                "running": [self.tasks[i].to_dict() for i in sorted(self.running)][:max_rows],
                "upcoming": [t.to_dict() for t in upcoming],
                "recent_done": [t.to_dict() for t in recent],
                "log": list(self.log)[-50:], "rounds": self.rounds,
                "infeasible": self.infeasible()}