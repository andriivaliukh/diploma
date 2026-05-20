#!/usr/bin/env bash
# metrics.sh — per-metric measurement functions.
# Sourced by run.sh.  All functions write raw output to stdout.
# SRV must be set (exported by setup_<scenario> in scenarios.sh).

# ---------------------------------------------------------------------------
# lat_idle — ping -c 300 -i 0.2, parse rtt time= series
# ---------------------------------------------------------------------------

run_lat_idle() {
    ping -c 300 -i 0.2 "$SRV"
}

# ---------------------------------------------------------------------------
# tcp_t — iperf3 single stream, 60 s
# ---------------------------------------------------------------------------

run_tcp_t() {
    local duration=60
    [[ "${BENCH_MODE:-measure}" == "smoke" ]] && duration=10
    iperf3 -c "$SRV" -t "$duration" -P 1
}

# ---------------------------------------------------------------------------
# tcp_p — iperf3 4 parallel streams, 60 s
# ---------------------------------------------------------------------------

run_tcp_p() {
    local duration=60
    [[ "${BENCH_MODE:-measure}" == "smoke" ]] && duration=10
    iperf3 -c "$SRV" -t "$duration" -P 4
}

# ---------------------------------------------------------------------------
# lat_load — iperf3 (load generator) + ping (metric) in parallel.
#
# Design: run_lat_load writes the iperf3 secondary file directly using
# BENCH_CURRENT_SCENARIO / BENCH_CURRENT_RUN (set by run_metric_safely before
# each metric call).  Ping stdout is the primary metric source and flows to the
# primary raw file via run_metric_safely's stdout redirect.  No special-casing
# needed in run_metric_safely.
#
# Primary raw:   ${scenario}-lat_load-runN.txt  — ping output (value=p95 ms)
# Secondary raw: ${scenario}-lat_load_iperf-runN.txt — iperf3 load (forensic)
# ---------------------------------------------------------------------------

run_lat_load() {
    local iperf3_raw="${DATA_DIR}/${BENCH_CURRENT_SCENARIO}-lat_load_iperf-run${BENCH_CURRENT_RUN}.txt"
    iperf3 -c "$SRV" -t 60 -P 1 > "$iperf3_raw" 2>&1 &
    local iperf3_pid=$!
    ping -c 300 -i 0.2 "$SRV"
    wait "$iperf3_pid" || true
}

# ---------------------------------------------------------------------------
# udp — iperf3 UDP ramp 50M→800M, report rate below first >1% loss step
# ---------------------------------------------------------------------------

run_udp() {
    if [[ "${BENCH_MODE:-measure}" == "smoke" ]]; then
        iperf3 -u -c "$SRV" -t 5 -b 50M
    else
        for b in 50M 100M 200M 400M 800M; do
            iperf3 -u -c "$SRV" -t 30 -b "$b"
        done
    fi
}

