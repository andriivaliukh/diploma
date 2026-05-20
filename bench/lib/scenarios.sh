#!/usr/bin/env bash
# scenarios.sh — setup_<scenario> / teardown_<scenario> / SRV resolution.
# Sourced by run.sh.  Each setup sets the exported SRV variable.

SRV=""

# ---------------------------------------------------------------------------
# no-vpn — raw inter-DC baseline; no tunnel
# ---------------------------------------------------------------------------

setup_no_vpn() {
    log "pre-flight [no-vpn]: checking reachability to 81.27.101.178"
    if ! ping -c 1 -W 2 81.27.101.178 >/dev/null 2>&1; then
        die "no-vpn pre-flight failed: cannot reach 81.27.101.178"
    fi
    SRV="81.27.101.178"
    export SRV
    log "no-vpn ready, SRV=$SRV"
}

teardown_no_vpn() {
    SRV=""
}

# ---------------------------------------------------------------------------
# wg-plain — kernel WireGuard, no auth
# ---------------------------------------------------------------------------

setup_wg_plain() {
    wg-quick down wg-bench 2>/dev/null || true

    local start_ns
    start_ns=$(date +%s%N)

    log "pre-flight [wg-plain]: bringing up wg-bench"
    if ! wg-quick up wg-bench; then
        die "wg-plain: wg-quick up wg-bench failed"
    fi

    # Trigger initial handshake; ignore failure (peer may not reply to first ping)
    ping -c 1 -W 5 10.99.0.1 >/dev/null 2>&1 || true

    local hs_ts now age
    hs_ts=$(wg show wg-bench latest-handshakes | awk 'NR==1 {print $2}')
    now=$(date +%s)
    age=$(( now - ${hs_ts:-0} ))
    if [[ ${hs_ts:-0} -eq 0 || $age -gt 60 ]]; then
        wg-quick down wg-bench 2>/dev/null || true
        die "wg-plain pre-flight failed: no fresh handshake (age=${age}s)"
    fi

    local end_ns
    end_ns=$(date +%s%N)
    ONBOARD_MS=$(( (end_ns - start_ns) / 1000000 ))
    SRV="10.99.0.1"
    export SRV ONBOARD_MS
    log "wg-plain ready, SRV=$SRV, ONBOARD_MS=${ONBOARD_MS}ms"
}

teardown_wg_plain() {
    wg-quick down wg-bench 2>/dev/null || true
    SRV=""
}

# ---------------------------------------------------------------------------
# wg-2fa — this thesis's stack (WG + 2FA via vpncli)
#
# Architecture note: the vpncli VPN server runs inside a Docker container on
# VPS A (vpnservice-vpn-server-1).  wg0 (10.10.0.1/24) lives inside that
# container, not on the host.  The bench-side iperf3 server that works for
# wg-plain (host, 10.99.0.1) is therefore unreachable from the wg-2fa tunnel
# because port 5201 is not exposed by Docker.  Fix: copy the host iperf3 binary
# into the container and start it there for the duration of the bench run.
# See architect-1/observations.md for the §3.10 methodology footnote.
# ---------------------------------------------------------------------------

_setup_container_iperf3() {
    local container="vpnservice-vpn-server-1"

    ssh "$VPS_A" "docker inspect '$container' >/dev/null 2>&1" \
        || die "wg-2fa: container '$container' not running on VPS A (check docker ps)"

    # docker cp approach was attempted but the container (Debian 13) is missing
    # libiperf.so.0 and libsctp.so.1 required by the host binary.  Use apt-get
    # install instead; the Debian apt cache is pre-warmed so this takes ~2-3 s on
    # the first run and is a no-op on subsequent runs (packages stay installed for
    # the container's lifetime; container restart wipes everything back to image
    # state, so no production-config change is made).
    ssh "$VPS_A" "docker exec '$container' apt-get install -y -q iperf3" \
        || die "wg-2fa: apt-get install iperf3 in container failed"

    # Start server; write PID to file so teardown can kill it without pkill/pgrep
    # (neither procps tool is in the slim Debian image).
    ssh "$VPS_A" "docker exec '$container' sh -c \
        'iperf3 -s --logfile /tmp/iperf3-bench.log & echo \$! > /tmp/iperf3-bench.pid'"

    sleep 0.5

    # Listen probe via bash /dev/tcp (works without netstat/ss on Debian slim).
    if ! ssh "$VPS_A" "docker exec '$container' bash -c \
            'timeout 2 bash -c \"echo > /dev/tcp/127.0.0.1/5201\" 2>/dev/null'"; then
        _teardown_container_iperf3
        die "wg-2fa: iperf3 not listening on :5201 in container after start"
    fi

    log "wg-2fa: iperf3 listening on container:5201 (10.10.0.1:5201)"
}

_teardown_container_iperf3() {
    local container="vpnservice-vpn-server-1"
    if ssh "$VPS_A" "docker inspect '$container' >/dev/null 2>&1" 2>/dev/null; then
        ssh "$VPS_A" "docker exec '$container' sh -c \
            'kill \$(cat /tmp/iperf3-bench.pid 2>/dev/null) 2>/dev/null || true; \
             rm -f /tmp/iperf3-bench.pid'" \
            2>/dev/null || true
    fi
}

setup_wg_2fa() {
    if [[ -n "${WG2FA_PID:-}" ]]; then
        kill -TERM "$WG2FA_PID" 2>/dev/null || true
        wait "$WG2FA_PID" 2>/dev/null || true
        unset WG2FA_PID
    fi

    local vpncli_bin="${VPNCLI:-$(command -v vpncli 2>/dev/null || echo /opt/vpncli/.venv/bin/vpncli)}"
    if [[ ! -x "$vpncli_bin" ]]; then
        die "wg-2fa: vpncli not found at $vpncli_bin (set VPNCLI= to override)"
    fi

    local user="benchuser$(date +%s)"
    local pass
    pass="$(openssl rand -hex 16)"
    local server="${VPN_SERVER:-https://vpn.loreo.xyz}"

    local start_ns
    start_ns=$(date +%s%N)

    # NOTE: --password and --totp-secret are visible in `ps aux` during the
    # ~2-5s lifetime of each vpncli invocation. Credentials are randomly-
    # generated per-invocation throwaway values; process-table visibility is an
    # acceptable trade-off for this bench scenario.
    log "wg-2fa: registering ${user}"
    local secret
    secret=$("$vpncli_bin" register --server "$server" --username "$user" --password "$pass" --auto-totp 2>&1 >/dev/null \
                 | grep -oE '^TOTP_SECRET=[A-Z2-7]+$' | head -1 | cut -d= -f2)
    if [[ -z "$secret" ]]; then
        die "wg-2fa: vpncli register failed (no TOTP_SECRET= line on stderr)"
    fi

    log "wg-2fa: logging in"
    if ! "$vpncli_bin" login --server "$server" --username "$user" --password "$pass" --totp-secret "$secret"; then
        die "wg-2fa: vpncli login failed"
    fi

    log "wg-2fa: connecting tunnel"
    "$vpncli_bin" connect --server "$server" &
    WG2FA_PID=$!

    local i
    for i in $(seq 1 100); do
        if ip -4 addr show 2>/dev/null | grep -q '10\.10\.0\.'; then
            break
        fi
        sleep 0.1
    done

    if ! ip -4 addr show 2>/dev/null | grep -q '10\.10\.0\.'; then
        kill -TERM "$WG2FA_PID" 2>/dev/null || true
        wait "$WG2FA_PID" 2>/dev/null || true
        unset WG2FA_PID
        die "wg-2fa pre-flight failed: no 10.10.0.x addr after 10s"
    fi

    local wg_iface
    wg_iface=$(ip -o link show 2>/dev/null | awk -F': ' '/vpncli-/{print $2}' | head -1)
    if [[ -n "$wg_iface" ]]; then
        ip route replace 10.10.0.0/24 dev "$wg_iface" 2>/dev/null || true
    fi

    local j
    for j in $(seq 1 10); do
        if ping -c 1 -W 2 10.10.0.1 >/dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done

    if ! ping -c 1 -W 2 10.10.0.1 >/dev/null 2>&1; then
        kill -TERM "$WG2FA_PID" 2>/dev/null || true
        wait "$WG2FA_PID" 2>/dev/null || true
        unset WG2FA_PID
        die "wg-2fa pre-flight failed: cannot ping 10.10.0.1 after retries"
    fi

    local end_ns
    end_ns=$(date +%s%N)
    ONBOARD_MS=$(( (end_ns - start_ns) / 1000000 ))
    SRV="10.10.0.1"
    export SRV ONBOARD_MS WG2FA_PID

    log "wg-2fa ready, SRV=$SRV, ONBOARD_MS=${ONBOARD_MS}ms (user=$user)"

    # Deploy iperf3 into the VPN container on VPS A.  wg0 (10.10.0.1) lives
    # inside Docker so the host iperf3 server is unreachable from this tunnel;
    # we start a per-run server inside the container instead.  ONBOARD_MS is
    # already recorded above so this step does not inflate the onboard metric.
    _setup_container_iperf3
}

teardown_wg_2fa() {
    if [[ -n "${WG2FA_PID:-}" ]]; then
        kill -TERM "$WG2FA_PID" 2>/dev/null || true
        wait "$WG2FA_PID" 2>/dev/null || true
        unset WG2FA_PID
    fi

    _teardown_container_iperf3

    ip route del 10.10.0.0/24 2>/dev/null || true

    local conf
    for conf in /etc/wireguard/vpncli-*.conf; do
        [[ -f "$conf" ]] || continue
        local iface="${conf%.conf}"
        iface="${iface##*/}"
        wg-quick down "$conf" 2>/dev/null || true
        rm -f "$conf" 2>/dev/null || true
    done

    SRV=""
}

# ---------------------------------------------------------------------------
# openvpn — static-key AES-256-CBC + SHA256, UDP 1194
# ---------------------------------------------------------------------------

setup_openvpn() {
    systemctl stop openvpn-client@ovpn-bench 2>/dev/null || true

    local ovpn_conf="/etc/openvpn/client/ovpn-bench.conf"
    if [[ ! -f "$ovpn_conf" ]]; then
        die "openvpn: config not found: $ovpn_conf"
    fi
    if ! grep -q '^allow-deprecated-insecure-static-crypto' "$ovpn_conf"; then
        die "openvpn: 2.7+ flag missing in $ovpn_conf; see HLD §E.2"
    fi

    local start_ns
    start_ns=$(date +%s%N)

    log "pre-flight [openvpn]: starting openvpn-client@ovpn-bench"
    if ! systemctl start openvpn-client@ovpn-bench; then
        die "openvpn: systemctl start failed"
    fi

    local i
    for i in $(seq 1 50); do
        if ip -4 addr show tun0 2>/dev/null | grep -q '10\.99\.1\.2'; then
            break
        fi
        sleep 0.1
    done

    if ! ip -4 addr show tun0 2>/dev/null | grep -q '10\.99\.1\.2'; then
        systemctl stop openvpn-client@ovpn-bench 2>/dev/null || true
        die "openvpn pre-flight failed: tun0 10.99.1.2 not assigned after 5s"
    fi

    if ! ping -c 1 -W 5 10.99.1.1 >/dev/null 2>&1; then
        systemctl stop openvpn-client@ovpn-bench 2>/dev/null || true
        die "openvpn pre-flight failed: cannot ping 10.99.1.1"
    fi

    local end_ns
    end_ns=$(date +%s%N)
    ONBOARD_MS=$(( (end_ns - start_ns) / 1000000 ))
    SRV="10.99.1.1"
    export SRV ONBOARD_MS
    log "openvpn ready, SRV=$SRV, ONBOARD_MS=${ONBOARD_MS}ms"
}

teardown_openvpn() {
    systemctl stop openvpn-client@ovpn-bench 2>/dev/null || true
    SRV=""
}

# ---------------------------------------------------------------------------
# Dispatcher helpers (called from run.sh to avoid hyphens in function names)
# ---------------------------------------------------------------------------

setup_scenario() {
    case "$1" in
        no-vpn)   setup_no_vpn ;;
        wg-plain) setup_wg_plain ;;
        wg-2fa)   setup_wg_2fa ;;
        openvpn)  setup_openvpn ;;
        *) die "unknown scenario: $1" ;;
    esac
}

teardown_scenario() {
    case "$1" in
        no-vpn)   teardown_no_vpn ;;
        wg-plain) teardown_wg_plain ;;
        wg-2fa)   teardown_wg_2fa ;;
        openvpn)  teardown_openvpn ;;
        *) log "WARN: teardown unknown scenario: $1"; return 0 ;;
    esac
}
