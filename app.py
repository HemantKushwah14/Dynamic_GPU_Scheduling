"""Flask API. Run:  python app.py   then open http://127.0.0.1:5000"""
import os
import tempfile
import webbrowser
import threading

from flask import Flask, jsonify, request, Response, send_from_directory

from core import experiments as ex
from core.dataset import load_workload, summarize
from core.schedulers import make_order, POLICIES
from core.simulator import Simulator, Playback, SPEEDS
from core.synthetic import generate

ROOT = os.path.dirname(os.path.abspath(__file__))
ALIBABA_DEFAULT = os.path.join(ROOT, "data", "alibaba", "openb_pod_list_default.csv")
HELIOS_DEFAULT = os.path.join(ROOT, "data", "helios", "cluster_log.csv")
DATASET_LABELS = {"alibaba": "Alibaba 2023", "helios": "Helios 2020", "synthetic": "Synthetic"}
DATASET_HINTS = {"alibaba": "Put openb_pod_list_default.csv in data/alibaba/",
                 "helios": "Put cluster_log.csv in data/helios/"}
UNITS = {1: ("s", "seconds"), 60: ("min", "minutes"), 3600: ("h", "hours"), 86400: ("d", "days")}

app = Flask(__name__, static_folder=os.path.join(ROOT, "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024


def dataset_path(name):
    """Read the module globals at call time, so tests can point them at small files."""
    return {"alibaba": ALIBABA_DEFAULT, "helios": HELIOS_DEFAULT}[name]


def time_unit(scale):
    """Virtual time unit. Real traces are in seconds and divided by `scale`; synthetic data has no real unit."""
    if not scale:
        return {"short": "t", "long": "time units"}
    s, l = UNITS.get(scale, (f"×{scale:g}s", f"units of {scale:g} s"))
    return {"short": s, "long": l}


def unit_of(report):
    return time_unit(report.notes.get("time_scale") if report else None)


class Lab:
    """All mutable server state in one place."""
    def __init__(self):
        self.playback = Playback()
        self.cfg = {"nodes": 4, "capacity": 8000, "sizes": None}
        self.policy = "proposed"
        self.last = {"compare": [], "experiment": [], "datasets": []}
        self.cache = {}
        self.set_workload(generate(), None, "synthetic")

    def set_workload(self, tasks, report, source):
        self.tasks, self.report, self.source = tasks, report, source
        self.unit = unit_of(report)
        self.build()

    def build(self):
        self.sim = Simulator(self.tasks, order=make_order(self.policy, self.tasks), **self.cfg)
        self.playback.pause()


lab = Lab()


def num(d, key, default=None, cast=int):
    v = d.get(key)
    if v in (None, ""):
        return default
    try:
        return cast(v)
    except (TypeError, ValueError):
        raise ValueError(f"'{key}' must be a number")


@app.errorhandler(ValueError)
def bad(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(KeyError)
def missing(e):
    return jsonify(error=f"unknown item {e}"), 400


def read_dataset(name, d):
    """Load a named real trace with the options in d (JSON body or form)."""
    if name not in ("alibaba", "helios"):
        raise ValueError("dataset must be 'synthetic', 'alibaba' or 'helios'")
    path = dataset_path(name)
    if not os.path.exists(path):
        raise ValueError(f"{DATASET_LABELS[name]} file not found. {DATASET_HINTS[name]}")
    opts = dict(time_scale=num(d, "scale", 1.0, float), max_tasks=num(d, "max_tasks"),
                sample_every=num(d, "sample_every", 1), start=num(d, "start"), end=num(d, "end"),
                max_demand=num(d, "max_demand"))
    if name == "helios":
        opts["max_gpus"] = num(d, "max_gpus", 8)
    return load_workload(path, **opts)


def cached_dataset(name, d):
    """Datasets used by Comparison / Experiments / Datasets tabs. Cached per option set (fast re-runs)."""
    scale, max_tasks = num(d, "scale", 3600.0, float), num(d, "max_tasks", 300)
    if name == "synthetic":
        return generate(), time_unit(None)
    path = dataset_path(name) if name in ("alibaba", "helios") else ""
    stamp = os.path.getmtime(path) if os.path.exists(path) else 0      # re-read if the file changes
    key = (name, scale, max_tasks, num(d, "max_gpus", 8), stamp)
    if key not in lab.cache:
        tasks, rep = read_dataset(name, {**d, "scale": scale, "max_tasks": max_tasks})
        if not tasks:
            raise ValueError(f"{DATASET_LABELS[name]}: no valid tasks after cleaning - see report: {rep.dropped}")
        lab.cache[key] = (tasks, unit_of(rep))
    return lab.cache[key]


def pick_tasks(d):
    """Which workload an experiment runs on: the loaded one ('current') or a named dataset."""
    name = d.get("dataset") or "current"
    if name == "current":
        return lab.tasks, lab.unit, lab.source
    tasks, unit = cached_dataset(name, d)
    return tasks, unit, name


def cluster_from(d):
    """Manual nodes x capacity cluster -> (cfg, None). Load level preset -> (None, None), sized later per dataset."""
    if d.get("load_percent"):
        return None, None
    cfg = {"nodes": num(d, "nodes", lab.cfg["nodes"]), "capacity": num(d, "capacity", lab.cfg["capacity"]),
           "sizes": lab.cfg["sizes"]}
    if not 1 <= cfg["nodes"] <= 32 or not 1000 <= cfg["capacity"] <= 64000:
        raise ValueError("nodes must be 1-32 and capacity 1000-64000")
    return cfg, None


def full_state():
    s = lab.sim.state()
    s.update(policy=lab.policy, policies=POLICIES, cfg=lab.cfg, source=lab.source, unit=lab.unit,
             summary=summarize(lab.tasks), report=lab.report.to_dict() if lab.report else None,
             datasets={k: os.path.exists(dataset_path(k)) for k in ("alibaba", "helios")},
             dataset_labels=DATASET_LABELS,
             playback={"running": lab.playback.running, "speed": lab.playback.speed,
                       "interval": lab.playback.interval(), "speeds": list(SPEEDS)})
    return s


@app.get("/")
def index():
    path = os.path.join(ROOT, "static", "index.html")
    if os.path.exists(path):
        return send_from_directory(app.static_folder, "index.html")
    return Response("Backend is running. Frontend (static/index.html) is missing.", mimetype="text/plain")


# ------------------------------------------------------------------ read
@app.get("/api/state")
def state(): return jsonify(full_state())


@app.get("/api/plan")
def plan():
    scope = request.args.get("scope", "auto")
    if scope not in ("auto", "all"):
        raise ValueError("scope must be 'auto' or 'all'")
    return jsonify(lab.sim.plan_snapshot(scope))


@app.get("/api/tasks")
def tasks():
    """Paged + filtered task table (keeps large workloads fast to render)."""
    a = request.args
    status, prio = a.get("status"), num(a, "priority")
    min_d, q = num(a, "min_demand", 0), (a.get("q") or "").lower()
    rows = [t for t in lab.sim.tasks.values()
            if (not status or t.status == status) and (prio is None or t.priority == prio)
            and t.demand >= min_d and q in t.id.lower()]
    rows.sort(key=lambda t: (t.arrival, t.id))
    off, lim = max(0, num(a, "offset", 0)), min(500, max(1, num(a, "limit", 100)))
    return jsonify(total=len(rows), rows=[t.to_dict() for t in rows[off:off + lim]])


@app.get("/api/datasets")
def datasets():
    return jsonify({k: {"label": DATASET_LABELS[k], "available": os.path.exists(dataset_path(k)),
                        "hint": DATASET_HINTS[k]} for k in ("alibaba", "helios")})


# ------------------------------------------------------------------ workload / config
@app.post("/api/load")
def load():
    d = request.get_json(silent=True) or {}
    source = d.get("source", "synthetic")
    if source == "synthetic":
        lab.set_workload(generate(num(d, "n", 60), num(d, "seed", 42)), None, "synthetic")
    else:
        tasks, rep = read_dataset(source, d)
        lab.set_workload(tasks, rep, source)
    return jsonify(full_state())


@app.post("/api/upload")
def upload():
    f = request.files.get("file")
    if not f:
        raise ValueError("no file uploaded")
    suffix = ".csv.gz" if f.filename.lower().endswith(".gz") else ".csv"
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        f.save(path)
        o = request.form
        tasks, rep = load_workload(path, time_scale=num(o, "scale", 1.0, float), max_tasks=num(o, "max_tasks"),
                                   sample_every=num(o, "sample_every", 1), start=num(o, "start"),
                                   end=num(o, "end"), max_demand=num(o, "max_demand"),
                                   max_gpus=num(o, "max_gpus", 8))
    finally:
        os.remove(path)
    if not tasks:
        raise ValueError("no valid tasks after cleaning - see report: " + str(rep.dropped))
    lab.set_workload(tasks, rep, "upload:" + f.filename)
    return jsonify(full_state())


@app.post("/api/config")
def config():
    d = request.get_json(silent=True) or {}
    policy = d.get("policy", lab.policy)
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {list(POLICIES)}")
    if d.get("load_percent"):                            # preset: cluster sized from the workload's own peak demand
        cfg, _ = ex.load_cluster(lab.tasks, num(d, "load_percent"))
    else:
        cfg = {"nodes": num(d, "nodes", lab.cfg["nodes"]), "capacity": num(d, "capacity", lab.cfg["capacity"]),
               "sizes": d.get("sizes")}                  # None = default halving partitions
        if not 1 <= cfg["nodes"] <= 32 or not 1000 <= cfg["capacity"] <= 64000:
            raise ValueError("nodes must be 1-32 and capacity 1000-64000")
    Simulator(lab.tasks[:1], **cfg)                      # validates sizes before committing
    lab.cfg, lab.policy = cfg, policy
    lab.build()
    return jsonify(full_state())


# ------------------------------------------------------------------ simulation controls
@app.post("/api/step")
def step():
    n = min(1000, max(1, num(request.get_json(silent=True) or {}, "n", 1)))
    for _ in range(n):
        if not lab.sim.step():
            lab.playback.pause()
            break
    return jsonify(full_state())


@app.post("/api/run")
def run_all():
    lab.sim.run_all()
    lab.playback.pause()
    return jsonify(full_state())


@app.post("/api/play")
def play():
    lab.playback.play()
    return jsonify(full_state())


@app.post("/api/pause")
def pause():
    lab.playback.pause()
    return jsonify(full_state())


@app.post("/api/speed")
def speed():
    d = request.get_json(silent=True) or {}
    lab.playback.set_speed(num(d, "speed", 1, float))
    return jsonify(full_state())


@app.post("/api/reset")
def reset():
    lab.sim.reset()
    lab.playback.pause()
    return jsonify(full_state())


@app.post("/api/inject")
def inject():
    d = request.get_json(silent=True) or {}
    lab.sim.inject(num(d, "demand", 1000), num(d, "duration", 30), num(d, "priority", 2), d.get("user"))
    return jsonify(full_state())


# ------------------------------------------------------------------ experiments
@app.post("/api/compare")
def compare():
    d = request.get_json(silent=True) or {}
    work, unit, source = pick_tasks(d)
    cfg, peak = cluster_from(d)
    if cfg is None:
        cfg, peak = ex.load_cluster(work, num(d, "load_percent"))
    rows = ex.compare(work, **cfg)
    for r in rows:
        r["peak"], r["unit"], r["dataset"] = peak, unit["short"], source
    lab.last["compare"] = rows
    return jsonify(rows)


@app.post("/api/experiment")
def experiment():
    d = request.get_json(silent=True) or {}
    kind = d.get("kind")
    values = [int(v) for v in d.get("values", [])][:10]
    if not values:
        raise ValueError("provide a list of values")
    work, unit, source = pick_tasks(d)
    if kind == "workload":
        rows = ex.workload_scaling(work, values, **lab.cfg)
    elif kind == "gpu":
        rows = ex.gpu_scaling(work, values, lab.cfg["capacity"], lab.cfg["sizes"])
    elif kind == "load":
        rows = ex.load_scaling(work, values)
    else:
        raise ValueError("kind must be 'workload', 'gpu' or 'load'")
    for r in rows:
        r["unit"], r["dataset"] = unit["short"], source
    lab.last["experiment"] = rows
    return jsonify(rows)


@app.post("/api/dataset_compare")
def dataset_compare():
    """Same policies, same relative load, two real traces: Alibaba vs Helios."""
    d = request.get_json(silent=True) or {}
    names = [n for n in d.get("datasets", ["alibaba", "helios"]) if n in ("alibaba", "helios", "synthetic")]
    if len(names) < 2:
        raise ValueError("choose at least two datasets")
    loaded = {n: cached_dataset(n, d) for n in names}
    cfg, _ = cluster_from(d)
    pct = None if cfg else num(d, "load_percent")
    rows = ex.compare_datasets({DATASET_LABELS[n]: loaded[n][0] for n in names}, percent=pct,
                               **(cfg or {}))
    units = {loaded[n][1]["short"] for n in names}
    unit = units.pop() if len(units) == 1 else "mixed"      # 'mixed' only if synthetic is compared with a real trace
    for r in rows:
        r["unit"] = unit
    lab.last["datasets"] = rows
    return jsonify(rows=rows, unit=loaded[names[0]][1],
                   summary={DATASET_LABELS[n]: summarize(loaded[n][0]) for n in names})


@app.get("/api/export/<name>.csv")
def export(name):
    if name not in lab.last:
        raise KeyError(name)
    return Response(ex.rows_to_csv(lab.last[name]), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}.csv"})


if __name__ == "__main__":
    threading.Timer(1.2, lambda: webbrowser.open("http://127.0.0.1:5000")).start()
    app.run(debug=False, port=5000)