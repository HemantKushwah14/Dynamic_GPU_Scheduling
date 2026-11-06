"""verify_calculations.py - recompute every number the UI shows, independently, and compare.

  python verify_calculations.py                      # synthetic workload
  python verify_calculations.py --alibaba data\\alibaba\\openb_pod_list_default.csv --scale 3600 --max-tasks 300

How it works: the app's numbers come from core/metrics.py. Here every metric is recomputed from the
raw facts (arrival, start, finish, demand, duration) with plain formulas written separately, and the
scheduling decisions themselves are re-checked (order rule, no idle space left, capacity never exceeded).
"""
import argparse, csv, math, statistics, sys
from app import app, lab
from core.dataset import load_alibaba
from core.schedulers import make_order
from core.simulator import Simulator

POL = ["fifo", "sjf", "ieee", "proposed"]
NAME = {"fifo": "FIFO", "sjf": "SJF", "ieee": "IEEE-inspired", "proposed": "Proposed"}
TOL = {"utilization": .0051, "wastage": .0051, "avg_wait": .00051, "avg_turnaround": .00051, "throughput": 5.1e-7, "fairness": 5.1e-5}
fails, checks = [], 0


def chk(label, got, exp, tol=0.0):
    global checks
    checks += 1
    ok = (got == exp) if (not tol or exp is None) else (got is not None and abs(got - exp) <= tol)
    if not ok:
        fails.append(f"{label}: shown={got!r}  independent={exp!r}")


# ---------------------------------------------------------------- independent formulas
def ref_of(tasks):
    return max(1.0, float(statistics.median(t.duration for t in tasks))) if tasks else 1.0


def indep(tasks, cap, ref):
    """All comparison/experiment metrics, straight from the definitions."""
    done = [t for t in tasks if t.finish is not None]
    waits = [t.start - t.arrival for t in tasks if t.start is not None]
    t0 = min(t.arrival for t in tasks)
    t_end = max([t.finish for t in done] + [t.arrival for t in tasks])
    window = t_end - t0
    util = sum(t.demand * t.duration for t in done) / (cap * window) * 100 if window > 0 else 0.0   # work done / capacity offered
    slow = [(t.finish - t.arrival) / t.duration for t in done]
    mk = max(t.finish for t in done) - min(t.arrival for t in done) if done else 0
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0
    return {"utilization": util, "wastage": 100 - util, "avg_wait": mean(waits), "max_wait": max(waits, default=0),
            "avg_turnaround": mean([t.finish - t.arrival for t in done]), "throughput": len(done) / mk if mk else 0.0,
            "fairness": sum(slow) ** 2 / (len(slow) * sum(x * x for x in slow)) if slow else 1.0,
            "starved": sum(w > 5 * ref for w in waits), "completed": len(done),
            "unscheduled": sum(t.start is None for t in tasks), "makespan": mk}


def score(t, now, ref, cap_max, frees):
    """Proposed priority formula, rewritten from the documented spec."""
    wait = now - t.arrival
    fit = [f for f in frees if f >= t.demand]
    s = (.30 * (t.priority - 1) / 2 + .30 * min(1, wait / ref) + .15 / (1 + t.duration / ref)
         + .10 * max(0, 1 - t.demand / cap_max) + .15 * (t.demand / min(fit) if fit else 0))
    return s + (10 + wait / ref if wait >= 5 * ref else 0)


def order_ok(pol, w, now, frees, cap_max, out, ref):
    if sorted(t.id for t in w) != sorted(t.id for t in out):
        return False
    keys = {"fifo": lambda t: (t.arrival, t.id), "sjf": lambda t: (t.duration, t.arrival, t.id), "ieee": lambda t: (-t.demand, t.arrival, t.id)}
    if pol in keys:
        return [t.id for t in out] == [t.id for t in sorted(w, key=keys[pol])]
    sc = [score(t, now, ref, cap_max, frees) for t in out]
    return all(sc[i] >= sc[i + 1] - 1e-9 for i in range(len(sc) - 1))


def sweep_ok(items, cap):                       # items: (start, finish, demand); releases before adds at equal times
    ev = sorted([(s, 1, d) for s, f, d in items] + [(f, 0, -d) for s, f, d in items])
    cur = 0
    for _, _, d in ev:
        cur += d
        if cur > cap:
            return False
    return True


class Rec:
    def __init__(self, fn): self.fn, self.calls = fn, []
    def __call__(self, waiting, now, cluster):
        frees = sorted(p.free for p in cluster.partitions)
        out = self.fn(waiting, now, cluster)
        self.calls.append((list(waiting), now, frees, max(p.capacity for p in cluster.partitions), list(out)))
        return out


def replay(tasks, pol, nodes, cap, sizes, tag):
    """Run one policy and audit every scheduling decision."""
    ref, rec = ref_of(tasks), Rec(make_order(pol, tasks))
    sim = Simulator([t.fresh_copy() for t in tasks], nodes, cap, sizes, order=rec)
    seen, bad_order, bad_idle = 0, [], []
    while sim.step():
        bad_idle += [(sim.clock, i) for i in sim.waiting if any(p.free >= sim.tasks[i].demand for p in sim.cluster.partitions)]
        if len(rec.calls) > seen:
            seen = len(rec.calls)
            w, now, frees, cap_max, out = rec.calls[-1]
            started = [e["task"] for e in list(sim.log)[-400:] if e["event"] == "START" and e["t"] == now]
            it = iter(t.id for t in out)
            if not order_ok(pol, w, now, frees, cap_max, out, ref) or not all(s in it for s in started):
                bad_order.append(now)
    run = [t for t in sim.tasks.values() if t.start is not None]
    chk(f"{tag} {pol}: scheduling order follows the {NAME[pol]} rule at every round", bad_order, [])
    chk(f"{tag} {pol}: no waiting task left that fits free space", bad_idle, [])
    chk(f"{tag} {pol}: every task starts >= arrival and runs exactly its duration",
        [t.id for t in run if t.start < t.arrival or t.finish != t.start + t.duration], [])
    chk(f"{tag} {pol}: total capacity never exceeded", sweep_ok([(t.start, t.finish, t.demand) for t in run], sim.cluster.total_capacity), True)
    part = {e["task"]: e["detail"].split("-> ")[1] for e in sim.log if e["event"] == "START"}
    if len(part) == len(run):                    # log not truncated -> also check each partition
        caps, by = {p.id: p.capacity for p in sim.cluster.partitions}, {}
        for t in run: by.setdefault(part[t.id], []).append((t.start, t.finish, t.demand))
        chk(f"{tag} {pol}: every partition capacity never exceeded", all(sweep_ok(v, caps[k]) for k, v in by.items()), True)
    return sim, ref


def verify_rows(rows, tasks, nodes, cap, sizes, tag):
    for pol, row in zip(POL, rows):
        before = len(fails)
        chk(f"{tag} {pol}: row order/policy", row["policy"], pol)
        sim, ref = replay(tasks, pol, nodes, cap, sizes, tag)
        for k, v in indep(list(sim.tasks.values()), nodes * cap, ref).items():
            chk(f"{tag} {pol} {k}", row[k], v, TOL.get(k, 0))
        chk(f"{tag} {pol} tasks column", row["tasks"], len(tasks))
        print(f"  {tag:<34}{NAME[pol]:<15}{'OK' if len(fails) == before else 'MISMATCH'}")


def indep_cluster(tasks, pct):
    ev = sorted([(t.arrival, 1, t.demand) for t in tasks] + [(t.arrival + t.duration, 0, -t.demand) for t in tasks])
    cur = peak = 0
    for _, _, d in ev:
        cur += d; peak = max(peak, cur)
    u = max(250, -(-max(t.demand for t in tasks) // 250) * 250)
    parts = max(1, math.ceil(peak * pct / 100 / u))
    return peak, u, parts


# ---------------------------------------------------------------- loader (Alibaba file)
def verify_loader(path, scale, max_tasks):
    PR, rows = {"LS": 3, "BURSTABLE": 2, "BE": 1}, []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try: ng, gm = int(float(r["num_gpu"])), int(float(r["gpu_milli"]))
            except ValueError: continue
            if ng <= 0 or gm <= 0 or any(not (r[k] or "").strip() for k in ("creation_time", "scheduled_time", "deletion_time")): continue
            ct, st, dt = (int(float(r[k])) for k in ("creation_time", "scheduled_time", "deletion_time"))
            if dt - st > 0: rows.append((ct, r["name"], ng * gm, dt - st, (r["qos"] or "").strip(), (r["pod_phase"] or "").strip()))
    rows.sort(key=lambda x: (x[0], x[1]))
    rows = rows[:max_tasks] if max_tasks else rows
    t0 = rows[0][0] if rows else 0
    exp = [(n, d, round((c - t0) / scale), max(1, round(du / scale)), PR.get(q.upper(), 2), ph.lower() == "running") for c, n, d, du, q, ph in rows]
    got, rep = load_alibaba(path, time_scale=scale, max_tasks=max_tasks)
    chk("loader: number of tasks kept", len(got), len(exp))
    chk("loader: demand = num_gpu x gpu_milli, arrival normalized, duration = deletion - scheduled, priority from QoS, censored flag",
        [(t.id, t.demand, t.arrival, t.duration, t.priority, t.censored) for t in got], exp)
    chk("loader: kept + dropped + limited == rows read", rep.kept + sum(rep.dropped.values()) + rep.notes.get("removed_by_sampling_or_limit", 0), rep.rows_read)
    print(f"  loader: read {rep.rows_read}, kept {rep.kept}, dropped {rep.dropped}")
    return got, rep


# ---------------------------------------------------------------- main
ap = argparse.ArgumentParser()
ap.add_argument("--alibaba"); ap.add_argument("--scale", type=float, default=3600.0); ap.add_argument("--max-tasks", type=int, default=300)
a = ap.parse_args()
c = app.test_client()
print("1. LOADER" if a.alibaba else "1. WORKLOAD SOURCE: synthetic")
if a.alibaba:
    tasks, rep = verify_loader(a.alibaba, a.scale, a.max_tasks)
    lab.set_workload(tasks, rep, "alibaba")
tasks, cfg = lab.tasks, lab.cfg
S = c.get("/api/state").get_json()["summary"]
d = [t.duration for t in tasks]
print("2. WORKLOAD LAB numbers")
for k, v in {"count": len(tasks), "total_demand_milli": sum(t.demand for t in tasks), "max_demand_milli": max(t.demand for t in tasks),
             "first_arrival": min(t.arrival for t in tasks), "last_arrival": max(t.arrival for t in tasks),
             "median_duration": statistics.median(d)}.items():
    chk(f"workload {k}", S[k], v)
chk("workload mean_duration", S["mean_duration"], statistics.mean(d), .0501)
chk("workload priority_counts", S["priority_counts"], {str(p): sum(t.priority == p for t in tasks) for p in (1, 2, 3) if any(t.priority == p for t in tasks)})
print("   count, demand totals, arrival range, mean/median duration, priority mix: checked")

print("3. COMPARISON tab (4 policies x 5 cluster settings)")
rows = c.post("/api/compare", json={"nodes": cfg["nodes"], "capacity": cfg["capacity"]}).get_json()
verify_rows(rows, tasks, cfg["nodes"], cfg["capacity"], cfg["sizes"], f"current cluster {cfg['nodes']}x{cfg['capacity']}")
for pct in (100, 60, 40, 25):
    rows = c.post("/api/compare", json={"load_percent": pct}).get_json()
    peak, u, parts = indep_cluster(tasks, pct)
    chk(f"load {pct}%: peak demand shown", rows[0]["peak"], peak)
    chk(f"load {pct}%: cluster size", rows[0]["cluster"], f"1x{parts * u} [{parts} partitions of {u}]")
    verify_rows(rows, tasks, 1, parts * u, [u] * parts, f"load {pct}% ({parts}x{u})")

print("4. EXPERIMENTS tab")
ordered = sorted(tasks, key=lambda t: (t.arrival, t.id))
for kind, vals in (("workload", [20, 40, 60]), ("gpu", [1, 2, 4]), ("load", [100, 60, 40, 25])):
    rows = c.post("/api/experiment", json={"kind": kind, "values": vals}).get_json()
    chk(f"{kind} experiment: row count", len(rows), 4 * len(vals))
    for v in vals:
        grp = [r for r in rows if r["value"] == v]
        if kind == "workload": sub, n, cp, sz = ordered[:v], cfg["nodes"], cfg["capacity"], cfg["sizes"]
        elif kind == "gpu": sub, n, cp, sz = tasks, v, cfg["capacity"], cfg["sizes"]
        else:
            peak, u, parts = indep_cluster(tasks, v); chk(f"load {v}% experiment peak", grp[0]["peak"], peak)
            sub, n, cp, sz = tasks, 1, parts * u, [u] * parts
        verify_rows(grp, sub, n, cp, sz, f"{kind} = {v}")

print("5. VIRTUAL LAB live tiles (step by step)")
c.post("/api/reset")
truth, _ = replay(tasks, lab.policy, cfg["nodes"], cfg["capacity"], cfg["sizes"], "live-run")
T, cap, t0 = list(truth.tasks.values()), cfg["nodes"] * cfg["capacity"], min(t.arrival for t in tasks)
while True:
    s = c.post("/api/step").get_json(); t = s["clock"]
    run = [x for x in T if x.start is not None and x.start <= t < x.finish]
    done = sum(x.finish is not None and x.finish <= t for x in T)
    pend = sum(x.arrival > t for x in T)
    chk(f"t={t} counts", s["counts"], {"PENDING": pend, "WAITING": len(T) - pend - len(run) - done, "RUNNING": len(run), "COMPLETED": done})
    chk(f"t={t} utilization now", s["cluster"]["utilization"], sum(x.demand for x in run) / cap * 100, .0051)
    area = sum(x.demand * max(0, min(x.finish, t) - x.start) for x in T if x.start is not None)
    chk(f"t={t} avg utilization", s["avg_utilization"], area / (cap * (t - t0)) * 100 if t > t0 else None, .0051)
    ws = [x.start - x.arrival for x in T if x.start is not None and x.start <= t]
    chk(f"t={t} avg wait tile", s["avg_wait"], round(sum(ws) / len(ws), 2) if ws else None, .0051)
    if s["done"]: break
chk("final: avg wastage tile = 100 - avg utilization", round(100 - s["avg_utilization"], 2), round(indep(T, cap, ref_of(tasks))["wastage"], 2), .0101)
print(f"   checked counts, utilization-now, avg utilization and avg wastage at every step")

print(f"\n{checks} checks, {len(fails)} FAILED")
for f in fails[:25]: print("  FAIL", f)
print("RESULT:", "ALL DISPLAYED CALCULATIONS ARE CORRECT" if not fails else "SOME CALCULATIONS ARE WRONG - see FAIL lines")
sys.exit(1 if fails else 0)