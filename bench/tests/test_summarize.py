import pytest
from summarize import (
    parse_ping_rtts, compute_stats,
    parse_iperf3_sender_mbps, parse_mpstat_soft_pct,
    parse_udp_ramp,
)


def make_ping_output(rtts):
    lines = ["PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data."]
    for i, rtt in enumerate(rtts, 1):
        lines.append(
            f"64 bytes from 10.0.0.1: icmp_seq={i} ttl=64 time={rtt} ms"
        )
    lines.extend([
        "",
        "--- 10.0.0.1 ping statistics ---",
        f"{len(rtts)} packets transmitted, {len(rtts)} received, 0% packet loss",
        "rtt min/avg/max/mdev = 23.500/24.000/24.500/0.150 ms",
    ])
    return "\n".join(lines)


KNOWN_RTTS = [23.9, 24.1, 24.0, 23.8, 24.2]
PING_SAMPLE = make_ping_output(KNOWN_RTTS)

PING_ALL_LOST = "\n".join([
    "PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.",
    "",
    "--- 10.0.0.1 ping statistics ---",
    "5 packets transmitted, 0 received, 100% packet loss",
])


def test_parse_ping_rtts_extracts_known_values():
    rtts = parse_ping_rtts(PING_SAMPLE)
    assert rtts == pytest.approx(KNOWN_RTTS)


def test_parse_ping_rtts_count_matches_lines():
    output = make_ping_output(list(range(1, 301)))
    rtts = parse_ping_rtts(output)
    assert len(rtts) == 300


def test_parse_ping_rtts_all_lost_returns_empty():
    rtts = parse_ping_rtts(PING_ALL_LOST)
    assert rtts == []


def test_compute_stats_mean():
    stats = compute_stats([1.0, 2.0, 3.0, 4.0, 5.0])
    assert stats["mean"] == pytest.approx(3.0)


def test_compute_stats_median_odd_count():
    stats = compute_stats([5.0, 1.0, 3.0, 2.0, 4.0])
    assert stats["median"] == pytest.approx(3.0)


def test_compute_stats_median_even_count():
    stats = compute_stats([1.0, 2.0, 3.0, 4.0])
    assert stats["median"] == pytest.approx(2.5)


def test_compute_stats_stddev_zero_for_uniform():
    stats = compute_stats([5.0] * 10)
    assert stats["stddev"] == pytest.approx(0.0)


def test_compute_stats_p95_bounds():
    values = list(range(1, 21))
    stats = compute_stats(values)
    assert 18.0 <= stats["p95"] <= 20.0


def test_compute_stats_p95_all_same():
    stats = compute_stats([7.0] * 50)
    assert stats["p95"] == pytest.approx(7.0)


def test_compute_stats_empty_raises_value_error():
    with pytest.raises(ValueError):
        compute_stats([])


def test_parse_ping_rtts_skips_malformed_lines():
    output = make_ping_output(KNOWN_RTTS) + \
        "\nFrom 10.0.0.99 icmp_seq=99 Destination Net Unreachable\n"
    rtts = parse_ping_rtts(output)
    assert rtts == pytest.approx(KNOWN_RTTS)


IPERF3_SINGLE_STREAM = "\n".join([
    "Connecting to host 81.27.101.178, port 5201",
    "[  5] local 10.0.0.2 port 44312 connected to 81.27.101.178 port 5201",
    "[ ID] Interval           Transfer     Bitrate         Retr  Cwnd",
    "[  5]   0.00-1.00   sec  90.8 MBytes   761 Mbits/sec    0    939 KBytes",
    "[  5]   1.00-2.00   sec  90.3 MBytes   758 Mbits/sec    0    939 KBytes",
    "[  5]   2.00-3.00   sec  90.5 MBytes   759 Mbits/sec    0    939 KBytes",
    "- - - - - - - - - - - - - - - - - - - - - - - - -",
    "[ ID] Interval           Transfer     Bitrate         Retr",
    "[  5]   0.00-3.00   sec   272 MBytes   761 Mbits/sec    0             sender",
    "[  5]   0.00-3.00   sec   272 MBytes   759 Mbits/sec                  receiver",
    "",
    "iperf Done.",
])

IPERF3_TWO_SENDER_LINES = "\n".join([
    "Connecting to host 81.27.101.178, port 5201",
    "[  4] local 10.0.0.2 port 44313 connected to 81.27.101.178 port 5201",
    "[  6] local 10.0.0.2 port 44314 connected to 81.27.101.178 port 5201",
    "[ ID] Interval           Transfer     Bitrate         Retr  Cwnd",
    "[  4]   0.00-3.00   sec   136 MBytes   380 Mbits/sec    0    470 KBytes       sender",
    "[  6]   0.00-3.00   sec   136 MBytes   381 Mbits/sec    0    470 KBytes       sender",
    "[SUM]   0.00-3.00   sec   272 MBytes   778 Mbits/sec    0                     sender",
    "[SUM]   0.00-3.00   sec   272 MBytes   776 Mbits/sec                          receiver",
    "",
    "iperf Done.",
])

IPERF3_ERROR = "\n".join([
    "iperf3: error - unable to connect to server: Connection refused",
])

MPSTAT_SAMPLE = "\n".join([
    "Linux 5.15.0-1055-kvm (vps-a)  05/20/2026  _x86_64_  (1 CPU)",
    "",
    "10:05:01 AM  CPU    %usr   %nice    %sys %iowait    %irq   %soft  %steal  %guest  %gnice   %idle",
    "10:05:02 AM  all    0.00    0.00    1.00    0.00    0.00    2.00    0.00    0.00    0.00   97.00",
    "10:05:02 AM    0    0.00    0.00    1.00    0.00    0.00    2.00    0.00    0.00    0.00   97.00",
    "10:05:03 AM  all    1.00    0.00    0.00    0.00    0.00    6.00    0.00    0.00    0.00   93.00",
    "10:05:03 AM    0    1.00    0.00    0.00    0.00    0.00    6.00    0.00    0.00    0.00   93.00",
    "",
    "Average:     CPU    %usr   %nice    %sys %iowait    %irq   %soft  %steal  %guest  %gnice   %idle",
    "Average:     all    0.50    0.00    0.50    0.00    0.00    4.00    0.00    0.00    0.00   95.00",
    "Average:       0    0.50    0.00    0.50    0.00    0.00    4.00    0.00    0.00    0.00   95.00",
])

MPSTAT_NO_AVERAGE = "\n".join([
    "Linux 5.15.0-1055-kvm (vps-a)  05/20/2026  _x86_64_  (1 CPU)",
    "",
    "10:05:01 AM  CPU    %usr   %nice    %sys %iowait    %irq   %soft  %steal  %guest  %gnice   %idle",
    "10:05:02 AM  all    0.00    0.00    1.00    0.00    0.00    2.00    0.00    0.00    0.00   97.00",
])


def test_parse_iperf3_sender_mbps_extracts_value():
    mbps = parse_iperf3_sender_mbps(IPERF3_SINGLE_STREAM)
    assert mbps == pytest.approx(761.0)


def test_parse_iperf3_sender_mbps_returns_float():
    mbps = parse_iperf3_sender_mbps(IPERF3_SINGLE_STREAM)
    assert isinstance(mbps, float)


def test_parse_iperf3_sender_mbps_raises_on_missing():
    with pytest.raises(ValueError):
        parse_iperf3_sender_mbps(IPERF3_ERROR)


def test_parse_iperf3_sender_mbps_uses_last_sender_line():
    mbps = parse_iperf3_sender_mbps(IPERF3_TWO_SENDER_LINES)
    assert mbps == pytest.approx(778.0)


def test_parse_mpstat_soft_pct_returns_average_all():
    pct = parse_mpstat_soft_pct(MPSTAT_SAMPLE)
    assert pct == pytest.approx(4.0)


def test_parse_mpstat_soft_pct_returns_float():
    pct = parse_mpstat_soft_pct(MPSTAT_SAMPLE)
    assert isinstance(pct, float)


def test_parse_mpstat_soft_pct_raises_if_no_average_block():
    with pytest.raises(ValueError):
        parse_mpstat_soft_pct(MPSTAT_NO_AVERAGE)


def make_iperf3_udp_band(target_mbps, rx_mbps, loss_pct):
    total = 100000
    lost = int(total * loss_pct / 100)
    return "\n".join([
        "Connecting to host 10.99.0.1, port 5201",
        "[ ID] Interval           Transfer     Bitrate         Total Datagrams",
        f"[  5]   0.00-30.00  sec  1.00 GBytes  {target_mbps:.1f} Mbits/sec  0.000 ms  0/{total} (0%)          sender",
        f"[  5]   0.00-30.13  sec  1.00 GBytes  {rx_mbps:.1f} Mbits/sec  0.043 ms  {lost}/{total} ({loss_pct:.1f}%)  receiver",
        "",
        "iperf Done.",
    ])


IPERF3_UDP_RAMP_LOSS_AT_400M = "\n".join([
    make_iperf3_udp_band(50.0, 49.8, 0.0),
    make_iperf3_udp_band(100.0, 99.6, 0.0),
    make_iperf3_udp_band(200.0, 198.7, 0.0),
    make_iperf3_udp_band(400.0, 344.0, 13.8),
])

IPERF3_UDP_RAMP_LOSS_AT_FIRST_STEP = make_iperf3_udp_band(50.0, 35.0, 15.0)

IPERF3_UDP_RAMP_NO_LOSS = "\n".join([
    make_iperf3_udp_band(50.0, 49.8, 0.0),
    make_iperf3_udp_band(100.0, 99.6, 0.0),
    make_iperf3_udp_band(200.0, 198.7, 0.0),
    make_iperf3_udp_band(400.0, 397.2, 0.0),
    make_iperf3_udp_band(800.0, 793.5, 0.0),
])


def test_parse_udp_ramp_returns_last_clean_rate():
    rate, note = parse_udp_ramp(IPERF3_UDP_RAMP_LOSS_AT_400M)
    assert rate == pytest.approx(198.7)
    assert note == ""


def test_parse_udp_ramp_first_step_lossy():
    rate, note = parse_udp_ramp(IPERF3_UDP_RAMP_LOSS_AT_FIRST_STEP)
    assert rate == pytest.approx(0.0)
    assert note == "first-step-lossy"


def test_parse_udp_ramp_no_loss_returns_last_rate():
    rate, note = parse_udp_ramp(IPERF3_UDP_RAMP_NO_LOSS)
    assert rate == pytest.approx(793.5)
    assert note == "no-loss-at-top"


def test_parse_udp_ramp_returns_tuple():
    result = parse_udp_ramp(IPERF3_UDP_RAMP_LOSS_AT_400M)
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_parse_udp_ramp_exactly_one_pct_is_clean():
    band = make_iperf3_udp_band(100.0, 99.0, 1.0)
    rate, note = parse_udp_ramp(band)
    assert rate == pytest.approx(99.0)
    assert note == "no-loss-at-top"
