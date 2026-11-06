"""Tests for the Helios loader, the dataset comparison and the time units."""
import app as webapp
from core import experiments as ex
from core.dataset import load_workload, detect_format
from core.synthetic import generate

HELIOS = """job_id,user,vc,gpu_num,cpu_num,node_num,state,submit_time,start_time,end_time,duration,queue
363167,u1Eem,vccJW,32,160,4,TIMEOUT,2020-03-18 04:01:39,2020-03-18 04:01:39,2020-04-01 04:01:54,1209615,0
394656,uBFjQ,vcefl,0,4,1,TIMEOUT,2020-03-25 11:08:58,2020-03-25 11:08:58,2020-04-08 11:09:06,1209608,0
394948,uhSlK,vcHvQ,8,1,1,FAILED,2020-03-25 17:00:06,2020-03-25 17:00:06,2020-04-04 12:40:45,848439,0
396689,uLoqx,vcEwI,4,16,1,COMPLETED,2020-03-26 13:42:30,2020-03-26 13:42:30,2020-04-02 21:36:47,633257,0
400000,uX,vc1,2,1,1,CANCELLED,2020-03-26 14:00:00,,,0,0
400001,uY,vc1,1,1,1,TIMEOUT,2020-03-26 15:00:00,2020-03-26 15:30:00,2020-03-26 16:30:00,3600,1800
"""
ALIBABA = """name,cpu_milli,memory_mib,num_gpu,gpu_milli,gpu_spec,qos,pod_phase,creation_time,deletion_time,scheduled_time
p1,1000,1,1,500,,LS,Succeeded,0,7200,10
p2,1000,1,2,1000,,BE,Succeeded,3600,20000,3700
p3,1000,1,1,1000,,Burstable,Running,5000,30000,5000
"""


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_helios_detect_and_mapping(tmp_path):
    path = _write(tmp_path, "cluster_log.csv", HELIOS)
    assert detect_format(path)[0] == "helios"
    tasks, rep = load_workload(path, time_scale=1)
    assert [t.id for t in tasks] == ["HEL-394948", "HEL-396689", "HEL-400001"]
    first = tasks[0]
    assert first.demand == 8 * 1000 and first.duration == 848439 and first.arrival == 0
    assert first.user == "uhSlK" and first.priority == 2
    assert tasks[1].arrival == 74544                     # 2020-03-26 13:42:30 - 2020-03-25 17:00:06
    assert rep.dropped == {"exceeds_max_gpus": 1, "no_gpu_request": 1, "never_started": 1}
    assert rep.kept == 3 and rep.rows_read == 6
    assert [t.censored for t in tasks] == [False, False, True]   # TIMEOUT -> censored


def test_helios_scale_and_gpu_limit(tmp_path):
    path = _write(tmp_path, "cluster_log.csv", HELIOS)
    tasks, rep = load_workload(path, time_scale=3600, max_gpus=32)
    assert tasks[0].id == "HEL-363167" and tasks[0].duration == round(1209615 / 3600)
    assert "exceeds_max_gpus" not in rep.dropped
    assert rep.notes["time_scale"] == 3600


def test_alibaba_ignores_helios_option(tmp_path):
    path = _write(tmp_path, "pods.csv", ALIBABA)
    tasks, _ = load_workload(path, time_scale=1, max_gpus=8)
    assert len(tasks) == 3


def test_compare_datasets_rows():
    a, b = generate(20, 1), generate(25, 2)
    rows = ex.compare_datasets({"A": a, "B": b}, percent=40)
    assert len(rows) == 2 * len(ex.POLICIES)
    assert {r["dataset"] for r in rows} == {"A", "B"}
    assert all(r["tasks"] in (20, 25) for r in rows)


def test_time_units():
    assert webapp.time_unit(3600) == {"short": "h", "long": "hours"}
    assert webapp.time_unit(60)["short"] == "min"
    assert webapp.time_unit(None)["long"] == "time units"


def test_api_helios_and_dataset_compare(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "HELIOS_DEFAULT", _write(tmp_path, "cluster_log.csv", HELIOS))
    monkeypatch.setattr(webapp, "ALIBABA_DEFAULT", _write(tmp_path, "pods.csv", ALIBABA))
    webapp.lab.cache.clear()
    c = webapp.app.test_client()
    s = c.post("/api/load", json={"source": "helios", "scale": 3600, "max_tasks": 300}).get_json()
    assert s["source"] == "helios" and s["summary"]["count"] == 3 and s["unit"]["short"] == "h"
    r = c.post("/api/dataset_compare", json={"load_percent": 40, "scale": 3600, "max_tasks": 300})
    assert r.status_code == 200
    d = r.get_json()
    assert {x["dataset"] for x in d["rows"]} == {"Alibaba 2023", "Helios 2020"}
    assert d["unit"]["long"] == "hours"
    assert c.get("/api/export/datasets.csv").status_code == 200
    r = c.post("/api/compare", json={"dataset": "helios", "load_percent": 60, "scale": 3600})
    assert r.status_code == 200 and r.get_json()[0]["unit"] == "h"
    webapp.lab.set_workload(generate(), None, "synthetic")      # leave the shared app state as other tests expect