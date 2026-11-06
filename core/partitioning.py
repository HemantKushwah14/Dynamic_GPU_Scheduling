"""GPU partition configuration (Part 2). Software partitions only - no NVIDIA MIG needed.

A node of capacity C is split into partitions whose sizes sum to C.
Default split halves what remains while it is above one GPU:  8000 -> [4000, 2000, 1000, 1000].
"""
from dataclasses import dataclass, field


@dataclass
class Partition:
    id: str
    node_id: int
    capacity: int
    used: int = 0
    tasks: dict = field(default_factory=dict)      # task id -> demand

    @property
    def free(self) -> int:
        return self.capacity - self.used


def default_sizes(capacity: int) -> list:
    sizes, rem = [], capacity
    while rem > 0:
        s = rem // 2 if rem > 1000 else rem
        sizes.append(s)
        rem -= s
    return sizes


def _label(i: int) -> str:
    return chr(65 + i) if i < 26 else f"P{i}"


def make_partitions(node_id: int, capacity: int, sizes=None) -> list:
    sizes = list(sizes) if sizes else default_sizes(capacity)
    if any(s <= 0 for s in sizes):
        raise ValueError("partition sizes must be positive")
    if sum(sizes) > capacity:
        raise ValueError(f"partition sizes {sizes} exceed node capacity {capacity}")
    if sum(sizes) < capacity:
        sizes.append(capacity - sum(sizes))        # remainder becomes the last partition
    return [Partition(f"N{node_id}-{_label(i)}", node_id, s) for i, s in enumerate(sizes)]