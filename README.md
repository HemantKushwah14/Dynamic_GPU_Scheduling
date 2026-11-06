<img width="1920" height="1080" alt="Screenshot 2026-11-06 223835" src="https://github.com/user-attachments/assets/19ac2542-ebad-49c5-8999-f8d3417a6c0b" />
<img width="1920" height="1080" alt="Screenshot 2026-11-06 223843" src="https://github.com/user-attachments/assets/93f2ad58-b8bc-4d43-bd30-b7831911bbc7" />
<img width="1920" height="1080" alt="Screenshot 2026-11-06 224057" src="https://github.com/user-attachments/assets/15a25531-9d7b-43c5-99ce-eca5b884c9a0" />
<img width="1920" height="1080" alt="Screenshot 2026-11-06 224111" src="https://github.com/user-attachments/assets/5bd28505-afdb-4af9-97da-e306f5c4bf53" />
<img width="1920" height="1080" alt="Screenshot 2026-11-06 224126" src="https://github.com/user-attachments/assets/2241c7c1-9dd4-42fa-a6eb-61b34588364c" />
<img width="1920" height="1080" alt="Screenshot 2026-11-06 224243" src="https://github.com/user-attachments/assets/12dc569a-a33a-44d7-bc15-77d17479e8c9" />
<img width="1920" height="1080" alt="Screenshot 2026-11-06 224254" src="https://github.com/user-attachments/assets/c2332cdb-d3fe-462c-9db5-4fa096136b3d" />
<img width="1920" height="1080" alt="Screenshot 2026-11-06 224259" src="https://github.com/user-attachments/assets/7f149265-8794-4c0b-817d-536aab542134" />
<img width="1920" height="1080" alt="Screenshot 2026-11-06 224322" src="https://github.com/user-attachments/assets/6726a586-f524-41f2-8b41-e473f7e25bb5" />
<img width="1920" height="1080" alt="Screenshot 2026-11-06 224332" src="https://github.com/user-attachments/assets/334e48e7-806a-4efe-a31c-8843a504c4e7" />
<img width="1920" height="1080" alt="Screenshot 2026-11-06 224339" src="https://github.com/user-attachments/assets/f638a5ef-762a-49a2-9920-51760972e396" />

# Dynamic GPU Resource Allocation and Scheduling — Virtual Lab

An interactive web lab that simulates how a cloud GPU cluster schedules and allocates jobs.
It replays **real production GPU traces** (Alibaba 2023 and SenseTime Helios 2020) through a
discrete-event simulator and compares four scheduling policies side by side.

> IT700 Advanced Algorithms team project · inspired by the IEEE paper by Sedighi et al. on
> dynamic task scheduling and adaptive GPU resource allocation in the cloud.

---

## Features

- **Virtual Lab**: step through the simulation or play it at 0.5×–10× speed, watch tasks move between
  queue → GPU partition → completed, inject new tasks, and see live utilization.
- **Algorithm visualizer**: the pipeline stage by stage: grouping (First-Fit Decreasing), resource analysis,
  partitioning, wastage, and best-fit allocation.
- **Four schedulers** on the identical workload and cluster: FIFO, Shortest Job First, an IEEE-inspired
  baseline, and the **proposed priority-aware + aging** policy.
- **Two real datasets**: Alibaba `cluster-trace-gpu-v2023` and SenseTime **Helios** 2020, plus a synthetic workload.
- **Datasets tab**: Alibaba vs Helios under the same relative load, with grouped bar charts.
- **Experiments**: workload scaling, GPU scaling and load scaling, exportable as CSV.
- **Load presets**: Light (100%), Moderate (60%), Heavy (40%) and Overloaded (25%) of the workload's own peak
  demand, so the policies are compared under real contention.
- Every chart has labelled axes with units, fixed ranges (utilization 0–100%, waiting time from 0–50),
  value labels on bars, and the title underneath.

## Tech stack

Python 3 · Flask · standard library only for the simulator · Chart.js 4.4.1 · vanilla HTML/CSS/JS · pytest

---

## Quick start

### 1. Clone and create a virtual environment

**Windows (PowerShell)**
```powershell
git clone https://github.com/HemantKushwah14/Dynamic_GPU_Scheduling.git
cd Dynamic_GPU_Scheduling
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
If activation is blocked, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**Linux / macOS**
```bash
git clone https://github.com/HemantKushwah14/Dynamic_GPU_Scheduling.git
cd Dynamic_GPU_Scheduling
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Add the datasets

| Dataset | Where to get it | Put it here |
|---|---|---|
| Alibaba GPU trace v2023 | [alibaba/clusterdata → cluster-trace-gpu-v2023](https://github.com/alibaba/clusterdata/tree/master/cluster-trace-gpu-v2023) | `data/alibaba/openb_pod_list_default.csv` *(included in this repo)* |
| SenseTime Helios 2020 | [S-Lab-System-Group/HeliosData](https://github.com/S-Lab-System-Group/HeliosData) → download `data.zip` | `data/helios/cluster_log.csv` |

For Helios, unzip `data.zip` and copy **one** cluster's log (we use **Venus**):

```powershell
mkdir data\helios -Force
Expand-Archive data.zip -DestinationPath data\helios
Copy-Item data\helios\data\Venus\cluster_log.csv data\helios\cluster_log.csv
```

The synthetic workload needs no download.

### 3. Run

```powershell
python app.py
```
The browser opens **http://127.0.0.1:5000** automatically.

### 4. Test

```powershell
python -m pytest -q             # unit + API tests
python verify_calculations.py   # recomputes every displayed metric independently
```

---

## How to use

1. **Workload Lab**: load *Synthetic*, *Alibaba 2023* or *Helios 2020*. Scale `3600` turns trace seconds into
   hours. *Max tasks* limits the slice (default 300). The cleaning report shows every dropped row and why.
2. **Virtual Lab**: choose a policy and a **Load preset** (try *Heavy 40%* or *Overloaded 25%*), press **Apply**,
   then **▶ Run**, **Next step** or **Run to end**.
3. **Comparison**: all four policies on one dataset. Green cells mark the best value in each column.
4. **Datasets**: Alibaba vs Helios under the same relative load.
5. **Experiments**: sweep task count, node count or load level.
6. **Documentation**: formulas, pseudocode, complexity and limitations inside the app.

---

## Datasets and preprocessing

| Field | Alibaba cluster-trace-gpu-v2023 | SenseTime Helios 2020 |
|---|---|---|
| GPU demand (milli-GPU) | `num_gpu × gpu_milli` (fractional GPUs) | `gpu_num × 1000` (whole GPUs) |
| Arrival | `creation_time − first creation_time` | `submit_time − first submit_time` |
| Duration | `deletion_time − scheduled_time` | `end_time − start_time` |
| Priority | QoS: LS = 3, Burstable = 2, BE = 1 | no column → all 2 |
| User | not in trace | hashed user id |
| Censored | pod still `Running` at trace end | state `TIMEOUT` (cluster time limit) |
| Dropped | no GPU, never scheduled, bad times | 0 GPUs, never started, bad times, > 8 GPUs (multi-node) |

Each dropped row is counted by reason, so nothing is silently removed.

**Units:** both traces store times in seconds and are divided by *Scale* (3600 → **hours**, shown as `h`).
Synthetic data uses abstract time units (`t`). Demand is in milli-GPU (1000 = one GPU).

---

## Scheduling policies

| Policy | Ordering rule |
|---|---|
| **FIFO** | earliest arrival first |
| **SJF** | shortest true duration first (oracle, needs future knowledge) |
| **IEEE-inspired baseline** | largest demand first, no priority, no aging (an approximation of the reference paper) |
| **Proposed** | weighted score with priority, aging, shortness, size and fit, plus a starvation guard |

**Proposed score**
```
score = 0.30·P + 0.30·A + 0.15·S + 0.10·G + 0.15·E
P = (priority − 1) / 2               A = min(1, wait / ref)          (aging)
S = 1 / (1 + duration / ref)         G = 1 − demand / largest_partition
E = demand / free space of the best-fit partition   (1 = perfect fit)
ref = median task duration
Starvation guard: if wait ≥ 5·ref then score += 10 + wait / ref
```

**Simulator:** discrete events in a heap; at equal timestamps completions are processed before arrivals;
placement is best fit (least leftover space); dispatch skips tasks that do not fit and retries them later.
Each node is split into partitions of ½, ¼, ⅛ and ⅛ of its capacity.

**Complexity** (T tasks, P partitions, E ≈ 2T events, R scheduling rounds, W waiting tasks):
full simulation O(E log E + R·(W log W + W·P)); grouping O(T log T + T·groups).

---

## Metrics

| Metric | Meaning | Better |
|---|---|---|
| Utilization (%) | time-weighted busy GPU capacity | higher |
| Wastage (%) | 100 − utilization | lower |
| Avg / max wait | time from arrival to start | lower |
| Avg turnaround | time from arrival to finish | lower |
| Throughput | tasks per time unit | higher |
| Fairness | Jain's index over slowdown (0–1) | higher |
| Starved | tasks that waited more than 5 × median duration | lower |

Every policy processes the same total GPU work, so **utilization, wastage and throughput depend only on the
makespan** (when the last task finishes). Policies that finish the last task at the same time show identical
values in these columns; this is expected, not an error. The ordering decisions show up in **waiting time,
maximum wait and fairness**.

---

## Project structure

```
├── app.py                    Flask API and server state
├── requirements.txt
├── verify_calculations.py    independent re-computation of displayed metrics
├── inspect_dataset.py        quick look at a trace file
├── core/
│   ├── models.py             Task and its state machine
│   ├── dataset.py            Alibaba / Helios / simple CSV loaders and the cleaning report
│   ├── synthetic.py          synthetic workload (60 tasks, seed 42)
│   ├── gpu_manager.py        nodes and partitions
│   ├── partitioning.py       partition layout
│   ├── grouping.py           First-Fit Decreasing grouping
│   ├── allocation.py         best-fit placement
│   ├── simulator.py          discrete-event simulator and playback
│   ├── schedulers.py         FIFO, SJF, IEEE-inspired, Proposed
│   ├── metrics.py            utilization, wait, fairness and more
│   └── experiments.py        policy comparison, scaling, load presets, dataset comparison
├── static/                   index.html, app.js, style.css, bg.webp
├── tests/                    test_core.py, test_api.py, test_helios.py
└── data/
    ├── alibaba/              openb_pod_list_default.csv
    └── helios/               cluster_log.csv (download, see above)
```

---

## Limitations

- Alibaba v2023 has no user id or priority column; priority is derived from QoS.
- Helios has no priority information, so the proposed policy's priority term has no effect there.
- Running pods (Alibaba) and TIMEOUT jobs (Helios) have censored durations; they are flagged.
- Helios jobs needing more than one node (> 8 GPUs) are dropped, because a task is placed on one partition.
- Partitions are fixed; no preemption, reservation or backfilling. Under heavy load a few tasks can still wait long.
- The Algorithm visualizer shows at most 100 tasks; the simulation always runs every loaded task.
- Results on synthetic data do not generalize to real traces.

## References

- Alibaba Cluster Trace Program, `cluster-trace-gpu-v2023`: https://github.com/alibaba/clusterdata
- Q. Hu et al., *Characterization and Prediction of Deep Learning Workloads in Large-Scale GPU Datacenters*, SC '21 (Helios traces): https://github.com/S-Lab-System-Group/HeliosData
- Sedighi et al., IEEE paper on dynamic task scheduling and adaptive GPU resource allocation in the cloud (reference paper for this project)
