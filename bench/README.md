# bench — Slice 2B Benchmark Harness

Orchestrates **4 scenarios × 5 metrics × N=5 runs** between VPS B (DE-FRA1,
`94.237.94.30`) and VPS A (PL-WAW1, `81.27.101.178`).

## Prerequisites

**On VPS B** (tools assumed in PATH):
`iperf3`, `ping`, `mtr`, `mpstat` (sysstat package), `pidstat`,
`wg`, `wg-quick`, `openvpn`, `vpncli`, `ssh`, `rsync`, `jq`, `python3`.

**On VPS A** (deployed by lead, one-time):
```
rsync bench/remote/remote_cpu_capture.sh root@81.27.101.178:/opt/bench/
ssh root@81.27.101.178 'chmod +x /opt/bench/remote_cpu_capture.sh'
```

## Invocation (run from VPS B)

```bash
# Rsync harness to VPS B first (from laptop):
rsync -avz bench/ root@94.237.94.30:/root/bench/

# Then on VPS B:
cd /root/bench
chmod +x run.sh
./run.sh            # all 4 scenarios (~3 h wall-clock)
./run.sh no-vpn     # single scenario (fastest smoke: ~5 min for lat_idle only)
./run.sh wg-plain
./run.sh wg-2fa
./run.sh openvpn
```

## Campaign workflow

Full measurement campaign (~3–4 h wall-clock for 4 scenarios × 7 metrics × N=5).

**Step 1 — pre-flight (from laptop)**
```bash
ssh root@94.237.94.30 'ping -c 1 81.27.101.178'   # VPS B → VPS A reachable
ssh root@81.27.101.178 'pgrep -a iperf3'           # iperf3 server running on VPS A
```

**Step 2 — sync harness to VPS B**
```bash
rsync -avz bench/ root@94.237.94.30:/root/bench/
```

**Step 3 — run campaign (on VPS B, in tmux or screen)**
```bash
ssh root@94.237.94.30
tmux new -s bench
cd /root/bench && BENCH_MODE=measure ./run.sh      # all 4 scenarios, ~3-4 h
# or per-scenario:
BENCH_MODE=measure ./run.sh no-vpn
BENCH_MODE=measure ./run.sh wg-plain
BENCH_MODE=measure ./run.sh openvpn
```

**Step 4 — rsync results back (from laptop)**
```bash
rsync -avz root@94.237.94.30:/root/data/benchmarks/ ./data/benchmarks/
```

**Step 5 — aggregate on laptop**
```bash
python3 bench/aggregate.py
# output: data/benchmarks/tables-for-thesis.md (also printed to stdout)
```

**Step 6 — paste into thesis**
Copy the three markdown tables from `tables-for-thesis.md` into `src/chapters/chapter3.tex` §3.10.
Cells showing `\TODO{fill in after measurement campaign}` mean that scenario × metric
was not measured yet — fill in after running the missing scenario.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `BENCH_MODE` | `measure` | `smoke`: N=1, iperf3 `-t 10`, skip `lat_load` — fast end-to-end sanity check (~5 min/scenario). `measure`: full N=5, iperf3 `-t 60`. |
| `BENCH_N` | `5` | Override run count (ignored when `BENCH_MODE=smoke`, which forces N=1). |
| `BENCH_PYTHON3` | `python3` | Path to Python 3 interpreter (e.g. `/usr/bin/python3.11`). |

```bash
# Smoke run — fast sanity check for one scenario:
BENCH_MODE=smoke ./run.sh wg-plain

# Full run with explicit Python path:
BENCH_PYTHON3=/usr/bin/python3.11 ./run.sh
```

## Output

| Path | Contents |
|---|---|
| `data/benchmarks/results.csv` | Canonical 12-column result set |
| `data/benchmarks/<scenario>-<metric>-run<N>.txt` | Verbatim tool stdout per run |
| `data/benchmarks/cpu-<scenario>-tcp_t-run<N>.txt` | mpstat / pidstat from VPS A |

## CSV schema

```
ts_iso, scenario, metric, run, value, unit, median, p95, stddev, mean, n_samples, notes
```

- **scenario** ∈ `no-vpn` / `wg-plain` / `wg-2fa` / `openvpn`
- **metric** ∈ `lat_idle` / `tcp_t` / `tcp_p` / `lat_load` / `udp` / `onboard` / `cpu_tcp_t`
- **value** — primary scalar: ms (latency), mbps (throughput), pct (CPU)
- **run** — 1..5; `onboard` is always run=1

## Idempotency policy

Re-running `./run.sh <scenario>` first removes all prior rows for that scenario
from `results.csv` (no backup rotation; old rows are permanently deleted).
Raw `.txt` artefacts are overwritten per run. The CSV header is preserved.

## Aggregation (on laptop, post-rsync)

```bash
# On laptop, after rsync-back:
rsync root@94.237.94.30:/root/data/benchmarks/ ./data/benchmarks/
python3 bench/aggregate.py
# output: data/benchmarks/tables-for-thesis.md
```

## Sanity-gate thresholds

### Pre-flight (per scenario, fail-fast)

| Scenario | Gate |
|---|---|
| `no-vpn` | `ping -c 1 -W 2 81.27.101.178` succeeds |
| `wg-plain` | After `wg-quick up wg-bench`: `wg show wg-bench` has peer + handshake < 60 s ago |
| `wg-2fa` | After `vpncli connect`: `ip -4 addr show | grep 10.10.0.` present; `ping -c 1 10.10.0.1` succeeds |
| `openvpn` | `allow-deprecated-insecure-static-crypto` in client conf; tun0 shows 10.99.1.2; `ping -c 1 10.99.1.1` succeeds |

### Post-run cross-scenario gates (emit WARN, continue)

1. `tcp_t` wg-plain vs wg-2fa within ±5 % (same kernel data-plane).
2. All `tcp_t` < 900 Mbps (1 vCPU virtio NIC ceiling; ≥ 900 = WARN, ≥ 950 = hard-flag). Empirically calibrated: wg-plain smoke run yielded 885 Mbps, so 900/950 gives a ~2%/7% headroom above observed baseline.
3. `lat_idle` mean within 5 ms of no-vpn baseline (pre-captured at harness start).
4. Per-cell `stddev/mean > 20 %` → bump to N=10 + `iperf3 -t 120` for that cell only.
5. `openvpn lat_idle.median − wg-plain lat_idle.median` in (0, 1.5] ms; outside range = WARN.
