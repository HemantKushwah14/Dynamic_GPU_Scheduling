"""Reproducible experiments.

Every policy runs on fresh copies of the SAME workload and the same cluster, so differences
come only from the scheduler. Results are plain numbers from the simulator - nothing is assumed.
"""
import csv
import io
import math

from .metrics import compute
from .schedulers import POLICIES, make_order, starve_threshold
from .simulator import Simulator


def run_policy(tasks, policy, nodes=4, capacity=8000, sizes=None) -> dict:
    work = [t.fresh_copy() for t in tasks]
    sim = Simulator(work, nodes, capacity, sizes, order=make_order(policy, work))
    sim.run_all()
    m = compute(sim, starve_threshold(work))
    m["policy"], m["label"] = policy, POLICIES[policy]
    m["tasks"], m["nodes"], m["capacity"] = len(work), nodes, capacity
    m["cluster"] = f"{nodes}x{capacity}" + (f" [{len(sizes)} partitions of {sizes[0]}]" if sizes else "")
    return m


def compare(tasks, nodes=4, capacity=8000, sizes=None) -> list:
    return [run_policy(tasks, p, nodes, capacity, sizes) for p in POLICIES]


def workload_scaling(tasks, counts, nodes=4, capacity=8000, sizes=None) -> list:
    ordered = sorted(tasks, key=lambda t: (t.arrival, t.id))
    rows = []
    for n in counts:
        for m in compare(ordered[:n], nodes, capacity, sizes):
            rows.append({"scenario": "workload_scaling", "value": min(n, len(ordered)), **m})
    return rows


def gpu_scaling(tasks, node_counts, capacity=8000, sizes=None) -> list:
    rows = []
    for g in node_counts:
        for m in compare(tasks, g, capacity, sizes):
            rows.append({"scenario": "gpu_scaling", "value": g, **m})
    return rows


def peak_demand(tasks) -> int:
    """Most GPU capacity the workload ever needs at once (run on a cluster so big nobody waits)."""
    if not tasks:
        return 0
    sim = Simulator([t.fresh_copy() for t in tasks], nodes=1, capacity=max(1000, 2 * sum(t.demand for t in tasks)))
    sim.run_all()
    return max(x[1] for x in sim.samples)


def load_cluster(tasks, percent):
    """Cluster whose total size is `percent`% of the workload's peak demand.
    Partitions are as big as the largest task, so every task is feasible and only CONTENTION changes."""
    peak = peak_demand(tasks)
    u = max(250, -(-max((t.demand for t in tasks), default=1000) // 250) * 250)
    parts = max(1, math.ceil(peak * percent / 100 / u))
    return {"nodes": 1, "capacity": parts * u, "sizes": [u] * parts}, peak


def load_scaling(tasks, percents) -> list:
    rows = []
    for pct in percents:
        cfg, peak = load_cluster(tasks, pct)
        for m in compare(tasks, **cfg):
            rows.append({"scenario": "load_scaling", "value": pct, "peak": peak, **m})
    return rows


def compare_datasets(workloads, percent=None, nodes=4, capacity=8000, sizes=None) -> list:
    """Run all policies on each dataset. workloads = {"Alibaba": tasks, "Helios": tasks}.

    percent given -> each dataset gets a cluster sized to `percent`% of ITS OWN peak demand,
    so both face the same relative pressure (fair comparison of traces with different sizes).
    percent None  -> both datasets run on the same fixed cluster (nodes x capacity).
    """
    rows = []
    for name, tasks in workloads.items():
        if not tasks:
            raise ValueError(f"dataset '{name}' has no tasks after cleaning")
        if percent:
            cfg, peak = load_cluster(tasks, percent)
        else:
            cfg, peak = {"nodes": nodes, "capacity": capacity, "sizes": sizes}, None
        for m in compare(tasks, **cfg):
            rows.append({"scenario": "dataset_compare", "dataset": name, "load_percent": percent,
                         "peak": peak, **m})
    return rows


def rows_to_csv(rows) -> str:
    if not rows:
        return ""
    flat = [{k: (str(v) if isinstance(v, dict) else v) for k, v in r.items()} for r in rows]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(flat[0]))
    w.writeheader()
    w.writerows(flat)
    return buf.getvalue()