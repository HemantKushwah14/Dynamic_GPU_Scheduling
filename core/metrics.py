"""Evaluation metrics (Part 4 logic, computed from real simulation state).

utilization  : time-weighted  integral(used) / (capacity * window)  x 100
wastage      : 100 - utilization (time-weighted unused capacity)
avg_wait     : mean(start - arrival) over tasks that started
avg_turnaround: mean(finish - arrival) over completed tasks
throughput   : completed tasks per virtual second over the makespan
fairness     : Jain's index over per-task slowdown (turnaround / duration); 1.0 = perfectly fair
starved      : tasks that waited longer than the common starvation threshold
overhead_rounds  : scheduling rounds (deterministic)
overhead_seconds : wall-clock time spent scheduling (NOT deterministic; excluded from equality tests)
"""
from .models import COMPLETED, WAITING

DETERMINISTIC_KEYS = ("utilization", "wastage", "avg_wait", "max_wait", "avg_turnaround",
                      "throughput", "fairness", "starved", "completed", "unscheduled",
                      "makespan", "overhead_rounds")


def jain(xs) -> float:
    s, q = sum(xs), sum(x * x for x in xs)
    return round(s * s / (len(xs) * q), 4) if xs and q else 1.0


def _mean(xs):
    return round(sum(xs) / len(xs), 3) if xs else 0.0


def compute(sim, starve_threshold: float) -> dict:
    tasks = list(sim.tasks.values())
    done = [t for t in tasks if t.status == COMPLETED]
    waits = [t.start - t.arrival for t in tasks if t.start is not None]

    util = 0.0
    s = sim.samples
    if len(s) >= 2 and s[-1][0] > s[0][0]:
        area = sum(s[i][1] * (s[i + 1][0] - s[i][0]) for i in range(len(s) - 1))
        util = area / (sim.cluster.total_capacity * (s[-1][0] - s[0][0])) * 100

    makespan = (max(t.finish for t in done) - min(t.arrival for t in done)) if done else 0
    by_prio = {}
    for t in tasks:
        if t.start is not None:
            by_prio.setdefault(t.priority, []).append(t.start - t.arrival)

    return {
        "utilization": round(util, 2), "wastage": round(100 - util, 2) if s else 0.0,
        "avg_wait": _mean(waits), "max_wait": max(waits) if waits else 0,
        "avg_turnaround": _mean([t.finish - t.arrival for t in done]),
        "throughput": round(len(done) / makespan, 6) if makespan else 0.0,
        "fairness": jain([(t.finish - t.arrival) / t.duration for t in done]),
        "starved": sum(w > starve_threshold for w in waits),
        "completed": len(done),
        "unscheduled": sum(t.status == WAITING for t in tasks),
        "makespan": makespan,
        "wait_by_priority": {p: _mean(w) for p, w in sorted(by_prio.items())},
        "overhead_rounds": sim.rounds,
        "overhead_seconds": round(sim.sched_seconds, 4),
    }