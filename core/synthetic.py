"""SYNTHETIC workload generator (NOT Alibaba data). Deterministic for a given seed.

Run:  python -m core.synthetic          -> writes data/synthetic/synthetic_workload.csv
"""
import csv
import os
import random

from .models import Task

# (demand in milli-GPU, relative weight): mostly fractional/1-GPU jobs, few multi-GPU
DEMANDS = [(250, 3), (500, 3), (1000, 4), (2000, 2), (4000, 1)]


def generate(n=60, seed=42, mean_gap=4.0, users=5):
    rng = random.Random(seed)
    values, weights = zip(*DEMANDS)
    t, tasks = 0.0, []
    for i in range(1, n + 1):
        t += rng.expovariate(1 / mean_gap)
        tasks.append(Task(
            id=f"SYN-{i:03d}",
            demand=rng.choices(values, weights)[0],
            arrival=int(t),
            duration=max(5, int(rng.lognormvariate(3.4, 0.7))),
            priority=rng.choices([1, 2, 3], [3, 5, 2])[0],
            user=f"user{rng.randint(1, users)}",
            qos="synthetic"))
    return tasks


def write_csv(tasks, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "demand", "arrival", "duration", "priority", "user"])
        for t in tasks:
            w.writerow([t.id, t.demand, t.arrival, t.duration, t.priority, t.user])


if __name__ == "__main__":
    out = os.path.join("data", "synthetic", "synthetic_workload.csv")
    write_csv(generate(), out)
    print("wrote", out)