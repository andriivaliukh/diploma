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
    echo "STUB: run_tcp_p not yet implemented" >&2
    return 1
}

# ---------------------------------------------------------------------------
# lat_load — iperf3 + ping in parallel; capture ping p95
# ---------------------------------------------------------------------------

run_lat_load() {
    echo "STUB: run_lat_load not yet implemented" >&2
    return 1
}

# ---------------------------------------------------------------------------
# udp — iperf3 UDP ramp 50M→800M, report rate below first >1% loss step
# ---------------------------------------------------------------------------

run_udp() {
    echo "STUB: run_udp not yet implemented" >&2
    return 1
}

