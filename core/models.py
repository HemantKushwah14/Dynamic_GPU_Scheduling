"""Core data model (Part 1): Task and its state machine.

Units
-----
demand   : milli-GPU units (1000 = one full GPU). demand = num_gpu * gpu_milli.
arrival  : virtual seconds since workload start.
duration : virtual seconds of execution once started.
priority : 1 (low) .. 3 (high).

States: PENDING (not arrived yet) -> WAITING (queued) -> RUNNING -> COMPLETED.
"""
from dataclasses import dataclass, asdict, replace

PENDING, WAITING, RUNNING, COMPLETED = "PENDING", "WAITING", "RUNNING", "COMPLETED"
TRANSITIONS = {
    PENDING: {WAITING},
    WAITING: {RUNNING},
    RUNNING: {COMPLETED},
    COMPLETED: set(),
}


class InvalidTransition(Exception):
    pass


@dataclass
class Task:
    id: str
    demand: int
    arrival: int
    duration: int
    priority: int = 2
    user: str | None = None      # not present in the Alibaba v2023 trace
    qos: str = ""
    num_gpu: int = 1
    censored: bool = False       # True when the pod was still Running at trace end
    status: str = PENDING
    start: int | None = None
    finish: int | None = None
    group: str | None = None

    def set_status(self, new: str) -> None:
        if new not in TRANSITIONS[self.status]:
            raise InvalidTransition(f"{self.id}: {self.status} -> {new}")
        self.status = new

    def fresh_copy(self) -> "Task":
        """Un-run copy, used so every scheduler sees an identical workload."""
        return replace(self, status=PENDING, start=None, finish=None, group=None)

    def to_dict(self) -> dict:
        return asdict(self)