"""Task grouping and resource analysis (Part 2).

Algorithm: First-Fit Decreasing (FFD) bin packing
  1. sort tasks by demand, largest first (ties: arrival, id -> deterministic)
  2. put each task in the first group whose total stays <= limit
  3. otherwise open a new group
limit = capacity of the largest partition, so a group can fit one partition.
A task bigger than the limit gets its own group, flagged as not fitting.
Complexity: O(T log T) sort + O(T * Gr) scan, Gr = number of groups.
"""
from dataclasses import dataclass, field, asdict


@dataclass
class Group:
    id: str
    task_ids: list = field(default_factory=list)
    total: int = 0

    def to_dict(self):
        return asdict(self)


def group_tasks(tasks, limit: int) -> list:
    groups = []
    for t in sorted(tasks, key=lambda t: (-t.demand, t.arrival, t.id)):
        target = next((g for g in groups if g.total + t.demand <= limit), None)
        if target is None:
            target = Group(f"G{len(groups) + 1}")
            groups.append(target)
        target.task_ids.append(t.id)
        target.total += t.demand
        t.group = target.id
    return groups


def analyze_groups(groups, cluster) -> list:
    """Resource analysis: does each group fit in the largest free partition?"""
    largest_free = max(p.free for p in cluster.partitions)
    return [{"group": g.id, "num_tasks": len(g.task_ids), "required": g.total,
             "available": largest_free, "fits": g.total <= largest_free,
             "remaining": largest_free - g.total} for g in groups]