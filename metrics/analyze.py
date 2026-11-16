#!/usr/bin/env python3
"""
analyze.py - turns the CSV logs of ONE experiment into latency / jitter / loss numbers (Lead 4).

Usage:   python3 metrics/analyze.py results/baseline
Reads:   <dir>/server_log.csv          (STATE packets that reached the server  = UPLINK)
         <dir>/client_*_log.csv        (WORLD packets that reached the clients = DOWNLINK)
         <dir>/client_*_rtt.csv        (PING/PONG round-trip times)
Writes:  <dir>/summary.json   and prints a table

Definitions
  latency (one-way) = recv_ts - send_ts   (valid because every Mininet host uses the same clock)
  jitter  (RFC 3550) : for packets i, j that arrived one after the other
                         D = (recv_j - recv_i) - (send_j - send_i)      (= change in latency)
                         J = J + (|D| - J) / 16                         (smoothed average of |D|)
  loss %  : among seq numbers min..max, the share that never arrived
"""
import csv
import glob
import json
import os
import sys


def percentile(values, p):
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1)))))
    return s[k]


def mean(values):
    return sum(values) / len(values) if values else None


def read_rows(path, fields):
    """Yield dicts of floats for the given columns."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for row in csv.DictReader(f):
            try:
                yield {k: float(row[k]) for k in fields}
            except (KeyError, ValueError):
                continue


def stream_metrics(rows):
    """rows = list of (seq, send_ts, recv_ts) for ONE stream (one player, one direction).
    Returns dict with latencies (ms), final jitter (ms), received, expected."""
    rows = sorted(rows)                       # by seq
    lat = [(r - s) * 1000.0 for _, s, r in rows]
    jitter = 0.0
    for i in range(1, len(rows)):
        d = ((rows[i][2] - rows[i - 1][2]) - (rows[i][1] - rows[i - 1][1])) * 1000.0
        jitter += (abs(d) - jitter) / 16.0
    if rows:
        expected = int(rows[-1][0] - rows[0][0]) + 1
    else:
        expected = 0
    return {"lat": lat, "jitter": jitter if rows else None, "received": len(rows), "expected": expected}


def combine(streams):
    """Merge several per-player streams into one summary dict."""
    lat = [x for st in streams for x in st["lat"]]
    jit = [st["jitter"] for st in streams if st["jitter"] is not None]
    received = sum(st["received"] for st in streams)
    expected = sum(st["expected"] for st in streams)
    loss = 100.0 * (expected - received) / expected if expected else None
    return {
        "latency_mean_ms": mean(lat),
        "latency_p95_ms": percentile(lat, 95),
        "latency_max_ms": max(lat) if lat else None,
        "jitter_ms": mean(jit),
        "loss_pct": loss,
        "packets_received": received,
        "packets_expected": expected,
    }


def burst_metrics(folder, rows):
    """Only for burst scenarios (events.json exists): latency while the noise burst was on, and how fast
    the SDN controller reacted (time from the start of the noise to the priority_on event).
    rows = [(send_ts, recv_ts)] of all uplink packets."""
    path = os.path.join(folder, "events.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        ev = json.load(f)
    if "noise_start" not in ev:
        return None
    t0, t1 = ev["noise_start"], ev["noise_stop"]
    window = [(r - s) * 1000.0 for s, r in rows if t0 <= r <= t1]
    first_5s = [(r - s) * 1000.0 for s, r in rows if t0 <= r <= t0 + 5]
    last_15s = [(r - s) * 1000.0 for s, r in rows if t1 - 15 <= r <= t1]
    out = {"noise_seconds": t1 - t0,
           "latency_mean_ms": mean(window), "latency_p95_ms": percentile(window, 95),
           "latency_max_ms": max(window) if window else None,
           "latency_first5s_mean_ms": mean(first_5s),     # includes the time before the controller reacts
           "latency_last15s_mean_ms": mean(last_15s),     # after the controller has reacted
           "reaction_s": None, "priority_off_after_s": None}
    ctl = os.path.join(folder, "controller_events.csv")
    if os.path.exists(ctl):
        with open(ctl) as f:
            for row in csv.DictReader(f):
                t = float(row["time"])
                if row["event"] == "priority_on" and out["reaction_s"] is None and t >= t0:
                    out["reaction_s"] = t - t0
                if row["event"] == "priority_off" and out["priority_off_after_s"] is None and t >= t1:
                    out["priority_off_after_s"] = t - t1
    return out


def analyze(folder):
    # ---- uplink: server_log.csv, grouped by player_id ----
    per_player = {}
    for r in read_rows(os.path.join(folder, "server_log.csv"), ["player_id", "seq", "send_ts", "recv_ts"]):
        per_player.setdefault(int(r["player_id"]), []).append((r["seq"], r["send_ts"], r["recv_ts"]))
    uplink = combine([stream_metrics(v) for v in per_player.values()])

    # ---- downlink: one log per client ----
    down_streams = []
    for path in sorted(glob.glob(os.path.join(folder, "client_*_log.csv"))):
        rows = [(r["seq"], r["send_ts"], r["recv_ts"]) for r in read_rows(path, ["seq", "send_ts", "recv_ts"])]
        down_streams.append(stream_metrics(rows))
    downlink = combine(down_streams)

    # ---- RTT from PING/PONG ----
    rtts = []
    for path in glob.glob(os.path.join(folder, "client_*_rtt.csv")):
        rtts += [r["rtt_ms"] for r in read_rows(path, ["rtt_ms"])]
    rtt = {"mean_ms": mean(rtts), "p95_ms": percentile(rtts, 95),
           "max_ms": max(rtts) if rtts else None, "samples": len(rtts)}

    summary = {"scenario": os.path.basename(os.path.normpath(folder)),
               "players": len(per_player), "uplink": uplink, "downlink": downlink, "rtt": rtt}
    all_rows = [(sd, rv) for v in per_player.values() for _, sd, rv in v]
    burst = burst_metrics(folder, all_rows)
    if burst:
        summary["burst"] = burst
    with open(os.path.join(folder, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    return summary


def fmt(v, nd=2):
    return "n/a" if v is None else ("%.*f" % (nd, v))


def print_summary(s):
    print("Scenario: %s   (players seen: %d)" % (s["scenario"], s["players"]))
    print("%-22s %10s %10s" % ("", "UPLINK", "DOWNLINK"))
    for key, label in [("latency_mean_ms", "latency mean (ms)"), ("latency_p95_ms", "latency p95 (ms)"),
                       ("latency_max_ms", "latency max (ms)"), ("jitter_ms", "jitter (ms)"),
                       ("loss_pct", "loss (%)")]:
        print("%-22s %10s %10s" % (label, fmt(s["uplink"][key]), fmt(s["downlink"][key])))
    r = s["rtt"]
    print("RTT (ping/pong): mean %s ms, p95 %s ms, max %s ms, %d samples"
          % (fmt(r["mean_ms"]), fmt(r["p95_ms"]), fmt(r["max_ms"]), r["samples"]))
    b = s.get("burst")
    if b:
        print("During the %.0f s noise burst (uplink): latency mean %s ms, p95 %s ms, max %s ms"
              % (b["noise_seconds"], fmt(b["latency_mean_ms"]), fmt(b["latency_p95_ms"]), fmt(b["latency_max_ms"])))
        print("  first 5 s of the burst: mean %s ms;  last 15 s: mean %s ms"
              % (fmt(b["latency_first5s_mean_ms"]), fmt(b["latency_last15s_mean_ms"])))
        if b["reaction_s"] is not None:
            print("  controller enabled priority %.1f s after the burst started" % b["reaction_s"])
        if b["priority_off_after_s"] is not None:
            print("  controller removed priority %.1f s after the burst ended" % b["priority_off_after_s"])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: analyze.py <results/scenario_folder>")
    print_summary(analyze(sys.argv[1]))
