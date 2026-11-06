"""Inspect a workload CSV and print the cleaning report.

Examples (from the project folder):
  python inspect_dataset.py data\\alibaba\\openb_pod_list_default.csv
  python inspect_dataset.py data\\alibaba\\openb_pod_list_default.csv --scale 3600 --max-tasks 300
"""
import argparse
import csv
import json

from core.dataset import load_workload, summarize, SchemaError, _open

ap = argparse.ArgumentParser()
ap.add_argument("path")
ap.add_argument("--scale", type=float, default=1.0, help="divide times by this (Alibaba only)")
ap.add_argument("--max-tasks", type=int, default=None)
ap.add_argument("--sample-every", type=int, default=1)
ap.add_argument("--start", type=int, default=None)
ap.add_argument("--end", type=int, default=None)
ap.add_argument("--max-demand", type=int, default=None, help="milli-GPU units")
a = ap.parse_args()

with _open(a.path) as f:
    print("Columns found:", next(csv.reader(f), []))
try:
    tasks, rep = load_workload(a.path, time_scale=a.scale, max_tasks=a.max_tasks,
                               sample_every=a.sample_every, start=a.start, end=a.end,
                               max_demand=a.max_demand)
except SchemaError as e:
    raise SystemExit(f"SCHEMA ERROR: {e}")
print("\nLoad report:\n", json.dumps(rep.to_dict(), indent=2))
print("\nSummary:\n", json.dumps(summarize(tasks), indent=2))
print("\nFirst 5 tasks:")
for t in tasks[:5]:
    print(" ", t.id, "demand", t.demand, "arrival", t.arrival, "duration", t.duration, "prio", t.priority)