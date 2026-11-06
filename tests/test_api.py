"""Every Flask endpoint, through the test client (no browser needed)."""
import io
import pytest
from app import app

HEADER = "name,cpu_milli,memory_mib,num_gpu,gpu_milli,gpu_spec,qos,pod_phase,creation_time,deletion_time,scheduled_time\n"


@pytest.fixture()
def c():
    cl = app.test_client()
    assert cl.post("/api/load", json={"source": "synthetic"}).status_code == 200
    assert cl.post("/api/config", json={"policy": "proposed", "nodes": 4, "capacity": 8000}).status_code == 200
    return cl


def test_state_shape(c):
    s = c.get("/api/state").get_json()
    for k in ("clock", "cluster", "counts", "policy", "playback", "summary", "upcoming", "recent_done", "avg_utilization"):
        assert k in s
    assert s["counts"]["PENDING"] == 60


def test_step_run_reset(c):
    assert c.post("/api/step", json={"n": 3}).get_json()["clock"] > 0
    done = c.post("/api/run").get_json()
    assert done["counts"]["COMPLETED"] == 60 and done["done"] and done["avg_utilization"] > 0
    assert c.post("/api/reset").get_json()["clock"] == 0


def test_play_pause_speed(c):
    assert c.post("/api/play").get_json()["playback"]["running"]
    assert not c.post("/api/pause").get_json()["playback"]["running"]
    assert c.post("/api/speed", json={"speed": 5}).get_json()["playback"]["interval"] == 0.2
    assert c.post("/api/speed", json={"speed": 3}).status_code == 400


def test_config_validation(c):
    assert c.post("/api/config", json={"nodes": 0}).status_code == 400
    assert c.post("/api/config", json={"sizes": [99999]}).status_code == 400
    assert c.post("/api/config", json={"policy": "nope"}).status_code == 400
    for pol in ("fifo", "sjf", "ieee", "proposed"):
        assert c.post("/api/config", json={"policy": pol}).get_json()["policy"] == pol


def test_inject_and_tasks_paging(c):
    c.post("/api/step")
    assert c.post("/api/inject", json={"demand": 500, "duration": 10, "priority": 3}).get_json()["log"][-1]["event"] == "INJECT"
    assert c.post("/api/inject", json={"demand": 0}).status_code == 400
    page = c.get("/api/tasks?limit=5&priority=3").get_json()
    assert page["total"] > 0 and len(page["rows"]) <= 5


def test_plan_scopes(c):
    for scope in ("auto", "all"):
        p = c.get("/api/plan?scope=" + scope).get_json()
        assert p["groups"] and {"analysis", "placements", "wastage", "source"} <= set(p)
    assert c.get("/api/plan?scope=x").status_code == 400


def test_compare_and_exports(c):
    rows = c.post("/api/compare", json={"load_percent": 25}).get_json()
    assert len(rows) == 4 and len({r["avg_wait"] for r in rows}) > 1      # heavy load: policies differ
    assert c.post("/api/compare", json={"nodes": 4, "capacity": 6000}).status_code == 200
    assert c.get("/api/export/compare.csv").data.startswith(b"utilization") or b"policy" in c.get("/api/export/compare.csv").data
    assert c.get("/api/export/nope.csv").status_code == 400


@pytest.mark.parametrize("kind,vals", [("workload", [20, 40]), ("gpu", [1, 2]), ("load", [100, 40])])
def test_experiments(c, kind, vals):
    rows = c.post("/api/experiment", json={"kind": kind, "values": vals}).get_json()
    assert len(rows) == 4 * len(vals)
    assert c.get("/api/export/experiment.csv").status_code == 200


def test_upload_clean_and_reject(c):
    good = HEADER + "p0,1,1,1,1000,,LS,Running,0,5000,0\np1,1,1,0,0,,BE,Succeeded,1,50,1\n"
    r = c.post("/api/upload", data={"file": (io.BytesIO(good.encode()), "a.csv")}, content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["report"]["dropped"] == {"no_gpu_request": 1}
    bad = c.post("/api/upload", data={"file": (io.BytesIO(b"a,b\n1,2\n"), "x.csv")}, content_type="multipart/form-data")
    assert bad.status_code == 400
    assert c.post("/api/upload", data={}, content_type="multipart/form-data").status_code == 400


def test_home_page_and_static(c):
    assert b"GPU Resource Allocation" in c.get("/").data
    for f in ("style.css", "app.js", "bg.webp"):
        assert c.get("/static/" + f).status_code == 200