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
# ---------------------------------------------------------------------------

setup_wg_2fa() {
    if [[ -n "${WG2FA_PID:-}" ]]; then
        kill -TERM "$WG2FA_PID" 2>/dev/null || true
        wait "$WG2FA_PID" 2>/dev/null || true
        unset WG2FA_PID
    fi

    local user="bench-user-$(date +%s)"
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
    secret=$(vpncli register --server "$server" --username "$user" --password "$pass" --auto-totp 2>&1 >/dev/null \
                 | grep -oE '^TOTP_SECRET=[A-Z2-7]+$' | head -1 | cut -d= -f2)
    if [[ -z "$secret" ]]; then
        die "wg-2fa: vpncli register failed (no TOTP_SECRET= line on stderr)"
    fi

    log "wg-2fa: logging in"
    if ! vpncli login --server "$server" --username "$user" --password "$pass" --totp-secret "$secret"; then
        die "wg-2fa: vpncli login failed"
    fi

    log "wg-2fa: connecting tunnel"
    vpncli connect --server "$server" &
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

    if ! ping -c 1 -W 5 10.10.0.1 >/dev/null 2>&1; then
        kill -TERM "$WG2FA_PID" 2>/dev/null || true
        wait "$WG2FA_PID" 2>/dev/null || true
        unset WG2FA_PID
        die "wg-2fa pre-flight failed: cannot ping 10.10.0.1"
    fi

    local end_ns
    end_ns=$(date +%s%N)
    ONBOARD_MS=$(( (end_ns - start_ns) / 1000000 ))
    SRV="10.10.0.1"
    export SRV ONBOARD_MS WG2FA_PID

    log "wg-2fa ready, SRV=$SRV, ONBOARD_MS=${ONBOARD_MS}ms (user=$user)"
}

teardown_wg_2fa() {
    if [[ -n "${WG2FA_PID:-}" ]]; then
        kill -TERM "$WG2FA_PID" 2>/dev/null || true
        wait "$WG2FA_PID" 2>/dev/null || true
        unset WG2FA_PID
    fi

    local iface
    for iface in $(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | sort -u); do
        if [[ "$iface" =~ ^wg- ]] && [[ "$iface" != "wg-bench" ]]; then
            ip link delete "$iface" 2>/dev/null || true
        fi
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
