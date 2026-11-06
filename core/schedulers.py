"""Scheduling policies (Part 3).

Each policy is a function  order(waiting, now, cluster) -> list of tasks in the order the
simulator should TRY to place them. Any task that does not fit is skipped this round.

1. fifo      : arrival order.
2. sjf       : shortest duration first (uses the known duration, i.e. an oracle - documented).
3. ieee      : IEEE-INSPIRED BASELINE (an approximation, NOT a reproduction of the paper).
               Largest demand first = the FFD packing order used by the Phase 2 grouping.
               No priority, no aging, no starvation guard.
4. proposed  : priority-aware scheduler with aging.

PROPOSED PRIORITY FORMULA (all terms in [0, 1]):
   score = 0.30*P + 0.30*A + 0.15*S + 0.10*G + 0.15*E
   P = (priority - 1) / 2                  priority (QoS class)
   A = min(1, wait / ref)                  AGING: grows with waiting time
   S = 1 / (1 + duration / ref)            shorter jobs score higher
   G = 1 - demand / largest_partition      smaller GPU requirement scores higher
   E = demand / free_of_best_fit_partition resource efficiency: 1 = perfect fit, 0 = no fit now
   ref = median task duration of the workload (makes the formula scale-free)
   STARVATION PREVENTION: if wait >= 5*ref then  score += 10 + wait/ref,
   which puts long-waiting tasks ahead of everything else, oldest first.
Ties are broken by (arrival, id), so results are deterministic.
Cost per round: O(W log W + P log P), W = waiting tasks, P = partitions.
"""
from bisect import bisect_left
from statistics import median

POLICIES = {
    "fifo": "FIFO",
    "sjf": "Shortest Job First",
    "ieee": "IEEE-inspired baseline",
    "proposed": "Proposed priority-aware + aging",
}
WEIGHTS = {"P": 0.30, "A": 0.30, "S": 0.15, "G": 0.10, "E": 0.15}
STARVE_FACTOR = 5
STARVE_BOOST = 10.0


def ref_time(tasks) -> float:
    return max(1.0, float(median(t.duration for t in tasks))) if tasks else 1.0


def starve_threshold(tasks) -> float:
    """Same threshold for every policy, so the 'starved tasks' metric is comparable."""
    return STARVE_FACTOR * ref_time(tasks)


def fifo(waiting, now, cluster=None):
    return sorted(waiting, key=lambda t: (t.arrival, t.id))


def sjf(waiting, now, cluster=None):
    return sorted(waiting, key=lambda t: (t.duration, t.arrival, t.id))


def ieee(waiting, now, cluster=None):
    return sorted(waiting, key=lambda t: (-t.demand, t.arrival, t.id))


def make_proposed(ref: float, weights=WEIGHTS):
    def score(t, now, cap_max, frees):
        wait = now - t.arrival
        i = bisect_left(frees, t.demand)
        e = t.demand / frees[i] if i < len(frees) else 0.0
        s = (weights["P"] * (t.priority - 1) / 2
             + weights["A"] * min(1.0, wait / ref)
             + weights["S"] / (1 + t.duration / ref)
             + weights["G"] * max(0.0, 1 - t.demand / cap_max)
             + weights["E"] * e)
        if wait >= STARVE_FACTOR * ref:
            s += STARVE_BOOST + wait / ref
        return s

    def order(waiting, now, cluster=None):
        cap_max = max(p.capacity for p in cluster.partitions)
        frees = sorted(p.free for p in cluster.partitions)
        return sorted(waiting, key=lambda t: (-score(t, now, cap_max, frees), t.arrival, t.id))
    return order


def make_order(policy: str, tasks):
    if policy == "fifo": return fifo
    if policy == "sjf": return sjf
    if policy == "ieee": return ieee
    if policy == "proposed": return make_proposed(ref_time(tasks))
    raise ValueError(f"unknown policy '{policy}'. Choose from {list(POLICIES)}")