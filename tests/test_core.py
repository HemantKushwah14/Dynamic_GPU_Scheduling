"""Core logic tests: allocation, states, events, schedulers, datasets, playback."""
import gzip
import pytest
from core.dataset import load_workload, load_alibaba, SchemaError
from core.experiments import run_policy
from core.gpu_manager import Cluster, OverAllocation
from core.metrics import DETERMINISTIC_KEYS
from core.models import Task, InvalidTransition, WAITING, RUNNING, COMPLETED, PENDING
from core.schedulers import make_proposed
from core.simulator import Simulator, Playback
from core.synthetic import generate

HEADER = "name,cpu_milli,memory_mib,num_gpu,gpu_milli,gpu_spec,qos,pod_phase,creation_time,deletion_time,scheduled_time\n"
ROWS = ("openb-pod-0000,12000,16384,1,1000,,LS,Running,0,12537496,0\n"
        "openb-pod-0001,6000,12288,1,460,,LS,Running,427061,12902960,427061\n"
        "openb-pod-0002,4000,8000,0,0,,BE,Succeeded,500000,600000,500000\n"      # no GPU -> dropped
        "openb-pod-0003,4000,8000,1,500,,BE,Pending,600000,,\n")                 # never scheduled -> dropped


def T(i, demand, arrival, duration, prio=2):
    return Task(id=i, demand=demand, arrival=arrival, duration=duration, priority=prio)


def check_invariants(sim):
    for p in sim.cluster.partitions:
        assert 0 <= p.used <= p.capacity and p.used == sum(p.tasks.values())
    assert sim.cluster.used == sum(p.used for p in sim.cluster.partitions)


def test_no_overallocation_at_every_step():
    sim = Simulator(generate(), nodes=1, capacity=4000)
    while sim.step():
        check_invariants(sim)


def test_best_fit_partition_choice():
    sim = Simulator([T("a", 900, 0, 5)], nodes=1, capacity=8000)       # partitions 4000,2000,1000,1000
    sim.run_all()
    assert sim.tasks["a"].status == COMPLETED
    assert [e["detail"] for e in sim.log if e["event"] == "START"] == ["-> N1-C"]   # tightest fit (1000)


def test_overallocation_is_refused():
    c = Cluster(1, 4000)
    p = c.partitions[-1]
    with pytest.raises(OverAllocation):
        c.allocate(T("big", p.capacity + 1, 0, 1), p)


def test_state_machine():
    t = T("x", 100, 0, 1)
    with pytest.raises(InvalidTransition):
        t.set_status(RUNNING)                                           # PENDING -> RUNNING is illegal
    for s in (WAITING, RUNNING, COMPLETED):
        t.set_status(s)
    with pytest.raises(InvalidTransition):
        t.set_status(WAITING)


def test_resources_released_after_completion():
    sim = Simulator(generate())
    sim.run_all()
    assert sim.cluster.used == 0 and all(not p.tasks for p in sim.cluster.partitions)
    assert all(t.status == COMPLETED for t in sim.tasks.values())


def test_simultaneous_completion_and_arrival():
    sim = Simulator([T("A", 1000, 0, 10), T("B", 1000, 10, 5)], nodes=1, capacity=1000, sizes=[1000])
    sim.run_all()
    assert sim.tasks["B"].start == 10                                   # completion handled before arrival


def test_empty_workload():
    sim = Simulator([])
    sim.run_all()
    assert sim.done and sim.state()["counts"]["COMPLETED"] == 0
    assert sim.plan_snapshot()["groups"] == []


def test_infeasible_task_stays_queued():
    sim = Simulator([T("huge", 9000, 0, 5), T("ok", 500, 0, 5)], nodes=1, capacity=8000)
    sim.run_all()
    assert sim.tasks["huge"].status == WAITING and sim.infeasible() == ["huge"]
    assert sim.tasks["ok"].status == COMPLETED


def test_priority_aging_and_starvation_guard():
    order = make_proposed(ref=10)
    c = Cluster(1, 8000, [4000])
    old, new = T("old", 1000, 0, 10, 1), T("new", 1000, 3, 10, 3)
    assert order([old, new], 5, c)[0].id == "new"                       # no starvation yet: priority wins
    new.arrival = 99
    assert order([old, new], 100, c)[0].id == "old"                     # waited >= 5*ref: guard boosts it first


def test_deterministic_results():
    tasks = generate()
    a, b = run_policy(tasks, "proposed", 1, 4000), run_policy(tasks, "proposed", 1, 4000)
    assert {k: a[k] for k in DETERMINISTIC_KEYS} == {k: b[k] for k in DETERMINISTIC_KEYS}


def test_speed_never_changes_results():
    def finish_times(speed):
        Playback().set_speed(speed)
        s = Simulator(generate()); s.run_all()
        return [(t.id, t.start, t.finish) for t in s.tasks.values()]
    assert finish_times(0.5) == finish_times(10)


def test_playback_controls():
    p = Playback()
    assert [p.set_speed(s) or p.interval() for s in (0.5, 1, 2, 5, 10)] == [2.0, 1.0, 0.5, 0.2, 0.1]
    with pytest.raises(ValueError):
        p.set_speed(3)
    p.play(); assert p.running
    p.pause(); assert not p.running


def test_step_and_reset():
    sim = Simulator(generate())
    assert sim.step() and sim.clock > 0
    sim.reset()
    assert sim.clock == 0 and sim.state()["counts"]["PENDING"] == 60


def test_inject_task():
    sim = Simulator(generate()); sim.step()
    tid = sim.inject(500, 10, 3)
    sim.run_all()
    assert sim.tasks[tid].status == COMPLETED
    with pytest.raises(ValueError):
        sim.inject(0, 5)


def test_alibaba_loading_and_cleaning(tmp_path):
    f = tmp_path / "pods.csv"; f.write_text(HEADER + ROWS)
    tasks, rep = load_alibaba(f)
    assert rep.rows_read == 4 and rep.kept == 2
    assert rep.dropped == {"no_gpu_request": 1, "never_scheduled": 1}
    a, b = tasks
    assert (a.demand, b.demand, a.priority, a.censored) == (1000, 460, 3, True)
    assert (a.arrival, b.arrival, a.duration) == (0, 427061, 12537496)   # arrival normalized
    scaled, _ = load_alibaba(f, time_scale=3600)
    assert scaled[0].duration == round(12537496 / 3600)


def test_gz_and_schema_errors(tmp_path):
    g = tmp_path / "pods.csv.gz"
    with gzip.open(g, "wt") as h: h.write(HEADER + ROWS)
    assert len(load_workload(g)[0]) == 2
    bad = tmp_path / "bad.csv"; bad.write_text("a,b\n1,2\n")
    with pytest.raises(SchemaError):
        load_workload(bad)


def test_simple_csv_validation(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("id,demand,arrival,duration,priority,user\nA,500,0,10,3,u1\nA,500,1,10,2,u1\nB,-5,0,10,2,u2\nC,500,0,0,2,u2\n")
    tasks, rep = load_workload(f)
    assert [t.id for t in tasks] == ["A"] and sum(rep.dropped.values()) == 3