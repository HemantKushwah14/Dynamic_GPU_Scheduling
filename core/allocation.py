"""Allocation (Part 2).

best_fit      : used by the simulator for every placement. Picks the feasible partition that
                leaves the least free space (ties by partition id -> deterministic). O(P).
plan_initial  : dry-run of the Phase 2 pipeline on a queue snapshot. It works on a COPY of the
                cluster, so the Algorithm Visualizer can show every stage without side effects.
"""
import copy

from .grouping import group_tasks, analyze_groups


def best_fit(cluster, demand: int):
    best = None
    for p in cluster.partitions:
        if p.free >= demand:
            key = (p.free - demand, p.id)
            if best is None or key < best[0]:
                best = (key, p)
    return best[1] if best else None


def plan_initial(tasks, cluster) -> dict:
    sim = copy.deepcopy(cluster)
    by_id = {t.id: t for t in tasks}
    limit = max(p.capacity for p in sim.partitions)
    groups = group_tasks(tasks, limit)                    # stage 1: grouping
    analysis = analyze_groups(groups, sim)                # stage 2: resource analysis
    placements = []                                       # stage 4: allocation (3 = partitions)
    for g in sorted(groups, key=lambda g: (-g.total, g.id)):
        part = best_fit(sim, g.total)
        if part is None:
            placements.append({"group": g.id, "node": None, "partition": None,
                               "required": g.total, "unused": 0,
                               "status": "QUEUED (no feasible partition)"})
            continue
        for tid in g.task_ids:
            sim.allocate(by_id[tid], part)
        placements.append({"group": g.id, "node": part.node_id, "partition": part.id,
                           "required": g.total, "unused": part.free, "status": "ALLOCATED"})
    snap = sim.snapshot()
    return {"groups": [g.to_dict() for g in groups], "analysis": analysis,
            "placements": placements, "wastage": sim.wastage(),     # stage 3: wastage
            "nodes": snap["nodes"], "utilization": snap["utilization"]}