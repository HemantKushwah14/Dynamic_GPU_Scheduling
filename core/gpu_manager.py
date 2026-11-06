"""Simulated GPU cluster (Part 2). Software only; runs on any laptop.

Node      = one simulated GPU machine with capacity in milli-GPU (8000 = 8 GPUs).
Partition = slice of a node; several small tasks may share one partition.
Cluster keeps a running `used` counter so utilization is O(1).
"""
from dataclasses import dataclass

from .partitioning import Partition, make_partitions


class OverAllocation(Exception):
    pass


@dataclass
class Node:
    id: int
    capacity: int
    partitions: list

    @property
    def used(self) -> int:
        return sum(p.used for p in self.partitions)

    @property
    def free(self) -> int:
        return self.capacity - self.used


class Cluster:
    def __init__(self, nodes: int = 4, capacity: int = 8000, sizes=None):
        if nodes < 1 or capacity < 1:
            raise ValueError("nodes and capacity must be >= 1")
        self.nodes = [Node(i, capacity, make_partitions(i, capacity, sizes))
                      for i in range(1, nodes + 1)]
        self.partitions = [p for n in self.nodes for p in n.partitions]   # fixed after build
        self.total_capacity = nodes * capacity
        self.used = 0
        self.where = {}                                   # task id -> Partition

    def allocate(self, task, part: Partition) -> None:
        if task.id in self.where:
            raise OverAllocation(f"{task.id} is already allocated")
        if task.demand > part.free:
            raise OverAllocation(f"{task.id} needs {task.demand}, {part.id} has {part.free} free")
        part.used += task.demand
        part.tasks[task.id] = task.demand
        self.where[task.id] = part
        self.used += task.demand

    def release(self, task_id: str) -> int:
        part = self.where.pop(task_id)
        demand = part.tasks.pop(task_id)
        part.used -= demand
        self.used -= demand
        return demand

    @property
    def utilization(self) -> float:
        return round(self.used / self.total_capacity * 100, 2)

    def wastage(self) -> dict:
        """Wastage % = unused capacity / total capacity x 100 (per node and overall)."""
        unused = self.total_capacity - self.used
        return {"unused": unused,
                "overall": round(unused / self.total_capacity * 100, 2),
                "per_node": {n.id: round(n.free / n.capacity * 100, 2) for n in self.nodes}}

    def snapshot(self) -> dict:
        return {
            "total_capacity": self.total_capacity, "used": self.used,
            "available": self.total_capacity - self.used, "utilization": self.utilization,
            "nodes": [{
                "id": n.id, "capacity": n.capacity, "used": n.used, "free": n.free,
                "utilization": round(n.used / n.capacity * 100, 2),
                "partitions": [{"id": p.id, "capacity": p.capacity, "used": p.used,
                                "free": p.free, "tasks": list(p.tasks)} for p in n.partitions],
            } for n in self.nodes],
        }