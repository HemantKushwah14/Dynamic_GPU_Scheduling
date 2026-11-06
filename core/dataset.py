"""Dataset loading and preprocessing. Standard library only.

Supported inputs (plain .csv or .csv.gz), detected from the header:
  1. Alibaba cluster-trace-gpu-v2023  openb_pod_list_*.csv
       columns used: name, num_gpu, gpu_milli, creation_time, scheduled_time,
                     deletion_time, qos, pod_phase
  2. SenseTime Helios 2020  cluster_log.csv
       columns used: job_id, user, gpu_num, state, submit_time, start_time, end_time
  3. Simple simulator format (uploads / synthetic):
       id, demand, arrival, duration [, priority, user]

Rows are streamed one at a time, so large files do not need much memory.
Every dropped row is counted by reason in LoadReport (nothing is silent).
"""
import csv
import gzip
from dataclasses import dataclass, field, asdict
from datetime import datetime
from statistics import mean, median

from .models import Task

# Mapping decision (documented in the app): Alibaba QoS class -> priority 1..3.
QOS_PRIORITY = {"LS": 3, "BURSTABLE": 2, "BE": 1}
DEFAULT_PRIORITY = 2
GPU_MILLI = 1000                 # 1 whole GPU = 1000 milli-GPU units (same unit as Alibaba gpu_milli)
HELIOS_MAX_GPUS = 8              # Alibaba pods ask for at most 8 GPUs; bigger Helios jobs span several nodes

ALIBABA_REQUIRED = ("name", "num_gpu", "gpu_milli", "creation_time",
                    "deletion_time", "scheduled_time")
HELIOS_REQUIRED = ("job_id", "gpu_num", "submit_time", "start_time", "end_time")
SIMPLE_REQUIRED = ("id", "demand", "arrival", "duration")
_EPOCH = datetime(1970, 1, 1)


class SchemaError(ValueError):
    pass


@dataclass
class LoadReport:
    source: str = ""
    fmt: str = ""
    rows_read: int = 0
    kept: int = 0
    dropped: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1

    def note(self, key: str, n: int = 1) -> None:
        self.notes[key] = self.notes.get(key, 0) + n

    def to_dict(self) -> dict:
        return asdict(self)


def _open(path):
    if str(path).lower().endswith(".gz"):
        return gzip.open(path, "rt", newline="", encoding="utf-8")
    return open(path, "r", newline="", encoding="utf-8")


def _num(value):
    """'' / 'nan' / garbage -> None, otherwise int."""
    if value is None:
        return None
    value = value.strip()
    if value == "" or value.lower() in ("nan", "none", "null"):
        return None
    try:
        return int(float(value))
    except (ValueError, OverflowError):
        return None


def _ts(value):
    """'2020-03-18 04:01:39' -> whole seconds. Empty / garbage -> None.
    Naive times are used on purpose, so no time-zone shift is added to durations."""
    if value is None:
        return None
    value = value.strip()
    if value == "" or value.lower() in ("nan", "none", "null"):
        return None
    try:
        return int((datetime.fromisoformat(value) - _EPOCH).total_seconds())
    except (ValueError, TypeError):
        return None


def _check_columns(fieldnames, required, label):
    missing = [c for c in required if c not in (fieldnames or [])]
    if missing:
        raise SchemaError(f"{label}: missing columns {missing}. Found: {list(fieldnames or [])}")


def _sample(rows, rep, sample_every, max_tasks):
    rows.sort(key=lambda x: (x[0], x[1]))            # deterministic order
    before = len(rows)
    rows = rows[::sample_every]
    if max_tasks is not None:
        rows = rows[:max_tasks]
    if before - len(rows):
        rep.note("removed_by_sampling_or_limit", before - len(rows))
    return rows


# ---------------------------------------------------------------- Alibaba
def load_alibaba(path, *, start=None, end=None, max_tasks=None, sample_every=1,
                 time_scale=1.0, max_demand=None):
    """Load openb_pod_list_*.csv.

    start/end   : keep pods whose raw creation_time is inside [start, end]
    sample_every: keep every k-th pod (after sorting by arrival)
    max_tasks   : keep the first N pods after sampling
    time_scale  : divide arrival and duration by this (e.g. 3600 -> seconds become hours)
    max_demand  : drop pods asking for more than this many milli-GPU units
    Duration = deletion_time - scheduled_time. Arrival = creation_time - first creation_time.
    """
    if time_scale <= 0 or sample_every < 1:
        raise ValueError("time_scale must be > 0 and sample_every >= 1")
    rep = LoadReport(source=str(path), fmt="alibaba-gpu-v2023")
    rows = []
    with _open(path) as f:
        reader = csv.DictReader(f)
        _check_columns(reader.fieldnames, ALIBABA_REQUIRED, "Alibaba pod list")
        for r in reader:
            rep.rows_read += 1
            ng, gm = _num(r["num_gpu"]), _num(r["gpu_milli"])
            if ng is None or gm is None:
                rep.drop("bad_gpu_fields"); continue
            if ng <= 0 or gm <= 0:
                rep.drop("no_gpu_request"); continue
            ct = _num(r["creation_time"])
            if ct is None:
                rep.drop("no_creation_time"); continue
            st = _num(r["scheduled_time"])
            if st is None:
                rep.drop("never_scheduled"); continue
            dt = _num(r["deletion_time"])
            if dt is None:
                rep.drop("no_deletion_time"); continue
            if dt - st <= 0:
                rep.drop("non_positive_duration"); continue
            if (start is not None and ct < start) or (end is not None and ct > end):
                rep.drop("outside_time_window"); continue
            demand = ng * gm
            if max_demand is not None and demand > max_demand:
                rep.drop("exceeds_max_demand"); continue
            rows.append((ct, r["name"], demand, dt - st, ng,
                         (r.get("qos") or "").strip(), (r.get("pod_phase") or "").strip()))

    rows = _sample(rows, rep, sample_every, max_tasks)
    t0 = rows[0][0] if rows else 0                   # timestamp normalization
    tasks = []
    for ct, name, demand, dur, ng, qos, phase in rows:
        key = qos.upper()
        if key not in QOS_PRIORITY:
            rep.note("unknown_qos_default_priority")
        tasks.append(Task(
            id=name, demand=demand,
            arrival=round((ct - t0) / time_scale),
            duration=max(1, round(dur / time_scale)),
            priority=QOS_PRIORITY.get(key, DEFAULT_PRIORITY),
            user=None, qos=qos, num_gpu=ng,
            censored=(phase.lower() == "running")))
    rep.kept = len(tasks)
    rep.notes["censored_running_pods"] = sum(t.censored for t in tasks)
    rep.notes["time_scale"] = time_scale
    return tasks, rep


# ---------------------------------------------------------------- Helios
def load_helios(path, *, start=None, end=None, max_tasks=None, sample_every=1,
                time_scale=1.0, max_demand=None, max_gpus=HELIOS_MAX_GPUS):
    """Load SenseTime Helios cluster_log.csv (Earth / Saturn / Uranus / Venus).

    Demand   = gpu_num x 1000 milli-GPU (whole GPUs, same unit as Alibaba).
    Duration = end_time - start_time. Arrival = submit_time - first submit_time.
    start/end: keep jobs submitted inside [start, end] seconds after the first GPU job.
    max_gpus : drop multi-node jobs asking for more GPUs than one node has (default 8).
    Helios has no priority column, so every job gets DEFAULT_PRIORITY.
    TIMEOUT jobs were stopped at the cluster time limit, so they are flagged as censored.
    """
    if time_scale <= 0 or sample_every < 1:
        raise ValueError("time_scale must be > 0 and sample_every >= 1")
    rep = LoadReport(source=str(path), fmt="helios-sensetime-2020")
    rows, states = [], {}
    with _open(path) as f:
        reader = csv.DictReader(f)
        _check_columns(reader.fieldnames, HELIOS_REQUIRED, "Helios cluster_log")
        for r in reader:
            rep.rows_read += 1
            ng = _num(r["gpu_num"])
            if ng is None:
                rep.drop("bad_gpu_fields"); continue
            if ng <= 0:
                rep.drop("no_gpu_request"); continue
            if max_gpus is not None and ng > max_gpus:
                rep.drop("exceeds_max_gpus"); continue
            sub = _ts(r["submit_time"])
            if sub is None:
                rep.drop("no_submit_time"); continue
            st = _ts(r["start_time"])
            if st is None:
                rep.drop("never_started"); continue
            en = _ts(r["end_time"])
            if en is None:
                rep.drop("no_end_time"); continue
            if en - st <= 0:
                rep.drop("non_positive_duration"); continue
            demand = ng * GPU_MILLI
            if max_demand is not None and demand > max_demand:
                rep.drop("exceeds_max_demand"); continue
            state = (r.get("state") or "").strip().upper()
            rows.append((sub, (r["job_id"] or "").strip(), demand, en - st, ng,
                         (r.get("user") or "").strip(), state))

    if rows and (start is not None or end is not None):   # window is relative to the first GPU job
        first = min(x[0] for x in rows)
        keep = []
        for x in rows:
            rel = x[0] - first
            if (start is not None and rel < start) or (end is not None and rel > end):
                rep.drop("outside_time_window")
            else:
                keep.append(x)
        rows = keep

    rows = _sample(rows, rep, sample_every, max_tasks)
    t0 = rows[0][0] if rows else 0
    tasks = []
    for sub, jid, demand, dur, ng, user, state in rows:
        states[state or "UNKNOWN"] = states.get(state or "UNKNOWN", 0) + 1
        tasks.append(Task(
            id=f"HEL-{jid}", demand=demand,
            arrival=round((sub - t0) / time_scale),
            duration=max(1, round(dur / time_scale)),
            priority=DEFAULT_PRIORITY,
            user=user or None, qos="", num_gpu=ng,
            censored=(state == "TIMEOUT")))
    rep.kept = len(tasks)
    rep.notes["censored_timeout_jobs"] = sum(t.censored for t in tasks)
    rep.notes["no_priority_column_default_priority"] = len(tasks)
    rep.notes["job_states"] = dict(sorted(states.items()))
    rep.notes["time_scale"] = time_scale
    return tasks, rep


# ---------------------------------------------------------------- simple CSV
def load_simple_csv(path, *, max_tasks=None):
    rep = LoadReport(source=str(path), fmt="simple-csv")
    tasks, seen = [], set()
    with _open(path) as f:
        reader = csv.DictReader(f)
        _check_columns(reader.fieldnames, SIMPLE_REQUIRED, "Simple workload CSV")
        for r in reader:
            rep.rows_read += 1
            demand, arrival, duration = _num(r["demand"]), _num(r["arrival"]), _num(r["duration"])
            if None in (demand, arrival, duration):
                rep.drop("bad_number"); continue
            if demand <= 0:
                rep.drop("non_positive_demand"); continue
            if duration <= 0:
                rep.drop("non_positive_duration"); continue
            if arrival < 0:
                rep.drop("negative_arrival"); continue
            tid = (r["id"] or "").strip()
            if not tid or tid in seen:
                rep.drop("missing_or_duplicate_id"); continue
            seen.add(tid)
            pr = _num(r.get("priority") or "")
            tasks.append(Task(id=tid, demand=demand, arrival=arrival, duration=duration,
                              priority=min(3, max(1, pr)) if pr else DEFAULT_PRIORITY,
                              user=(r.get("user") or "").strip() or None))
    tasks.sort(key=lambda t: (t.arrival, t.id))
    if max_tasks is not None:
        rep.note("removed_by_limit", max(0, len(tasks) - max_tasks))
        tasks = tasks[:max_tasks]
    rep.kept = len(tasks)
    return tasks, rep


def detect_format(path):
    with _open(path) as f:
        header = next(csv.reader(f), [])
    if "num_gpu" in header and "gpu_milli" in header:
        return "alibaba", header
    if "gpu_num" in header and "submit_time" in header:
        return "helios", header
    if "demand" in header:
        return "simple", header
    return None, header


def load_workload(path, **opts):
    """Detect the format from the header and load. Options a format does not use are ignored."""
    fmt, header = detect_format(path)
    if fmt == "alibaba":
        opts.pop("max_gpus", None)
        return load_alibaba(path, **opts)
    if fmt == "helios":
        return load_helios(path, **opts)
    if fmt == "simple":
        return load_simple_csv(path, max_tasks=opts.get("max_tasks"))
    raise SchemaError(f"Unrecognized workload format. Header: {header}")


def summarize(tasks):
    """Small stats block for the Overview / Workload Lab / Datasets pages."""
    if not tasks:
        return {"count": 0}
    durs = [t.duration for t in tasks]
    prios = {}
    for t in tasks:
        prios[t.priority] = prios.get(t.priority, 0) + 1
    return {
        "count": len(tasks),
        "total_demand_milli": sum(t.demand for t in tasks),
        "max_demand_milli": max(t.demand for t in tasks),
        "mean_demand_milli": round(mean(t.demand for t in tasks), 1),
        "first_arrival": min(t.arrival for t in tasks),
        "last_arrival": max(t.arrival for t in tasks),
        "mean_duration": round(mean(durs), 1),
        "median_duration": median(durs),
        "priority_counts": dict(sorted(prios.items())),
    }