#!/usr/bin/env python3
"""
plot.py - makes the report graphs from results/<scenario>/summary.json (Lead 4).

Usage:  python3 metrics/plot.py            (after running analyze.py on each scenario folder)
Output: results/latency.png, results/jitter.png, results/loss.png, results/latency_over_time.png,
        results/results_table.md
"""
import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results")
ORDER = ["baseline", "congested_noprio", "congested_prio", "loss5"]
BURST = ["burst_noprio", "burst_static", "burst_dynamic"]
LABELS = {"baseline": "Baseline (no noise)", "congested_noprio": "Congestion, no priority",
          "congested_prio": "Congestion, SDN priority", "loss5": "5% random loss",
          "burst_noprio": "Burst, no priority", "burst_static": "Burst, static priority",
          "burst_dynamic": "Burst, dynamic SDN"}
COLORS = {"baseline": "#7a7f87", "congested_noprio": "#d9622b",
          "congested_prio": "#2a6fdb", "loss5": "#7b5ea7",
          "burst_noprio": "#d9622b", "burst_static": "#7a7f87", "burst_dynamic": "#2a6fdb"}


def load(names=ORDER):
    data = {}
    for name in names:
        p = os.path.join(ROOT, name, "summary.json")
        if os.path.exists(p):
            with open(p) as f:
                data[name] = json.load(f)
    return data


def style(ax, title, ylabel):
    ax.set_title(title, fontsize=12, loc="left")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def grouped_bars(data, getters, title, ylabel, fname):
    """getters = [(label, function(summary)->number), ...]; one cluster per scenario."""
    names = list(data)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    width = 0.8 / len(getters)
    shades = [1.0, 0.55]
    for gi, (glabel, fn) in enumerate(getters):
        xs = [i + gi * width for i in range(len(names))]
        vals = [fn(data[n]) or 0 for n in names]
        bars = ax.bar(xs, vals, width * 0.92, color=[COLORS[n] for n in names], alpha=shades[gi % 2],
                      edgecolor="white", linewidth=1.5)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), "%.2f" % v, ha="center", va="bottom", fontsize=8)
    ax.set_xticks([i + width * (len(getters) - 1) / 2 for i in range(len(names))])
    ax.set_xticklabels([LABELS[n] for n in names], fontsize=9)
    # legend explains the light/dark bar meaning (colour = scenario, shade = metric)
    handles = [plt.Rectangle((0, 0), 1, 1, color="#444444", alpha=shades[i % 2]) for i in range(len(getters))]
    ax.legend(handles, [g[0] for g in getters], frameon=False, loc="upper left")
    style(ax, title, ylabel)
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, fname), dpi=160)
    plt.close(fig)


def latency_over_time(data):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for name in data:
        path = os.path.join(ROOT, name, "server_log.csv")
        if not os.path.exists(path):
            continue
        pts = []
        with open(path) as f:
            for row in csv.DictReader(f):
                pts.append((float(row["recv_ts"]), (float(row["recv_ts"]) - float(row["send_ts"])) * 1000))
        if not pts:
            continue
        pts.sort()
        t0 = pts[0][0]
        # average into 1-second buckets so the line is readable
        buckets = {}
        for t, l in pts:
            buckets.setdefault(int(t - t0), []).append(l)
        xs = sorted(buckets)
        ax.plot(xs, [sum(buckets[x]) / len(buckets[x]) for x in xs], color=COLORS[name],
                linewidth=2, label=LABELS[name])
    ax.set_xlabel("time (s)")
    ax.legend(frameon=False)
    style(ax, "Game update latency over time (client to server, 1 s average)", "latency (ms)")
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, "latency_over_time.png"), dpi=160)
    plt.close(fig)


def read_events(name):
    """controller_events.csv -> list of (epoch, event, detail)"""
    path = os.path.join(ROOT, name, "controller_events.csv")
    out = []
    if os.path.exists(path):
        with open(path) as f:
            for row in csv.DictReader(f):
                out.append((float(row["time"]), row["event"], row["detail"]))
    return out


def dynamic_timeline(burst):
    """Latency over time for the three burst scenarios + bottleneck utilisation seen by the controller.
    Shaded band = noise burst; dashed lines = the dynamic controller switching priority on / off."""
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(9, 6.5), sharex=True, gridspec_kw={"height_ratios": [3, 1.5]})
    t0 = None
    for name in burst:
        path = os.path.join(ROOT, name, "server_log.csv")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            pts = sorted((float(r["recv_ts"]), (float(r["recv_ts"]) - float(r["send_ts"])) * 1000)
                         for r in csv.DictReader(f))
        if not pts:
            continue
        start = pts[0][0]
        buckets = {}
        for t, l in pts:
            buckets.setdefault(int(t - start), []).append(l)
        xs = sorted(buckets)
        ax.plot(xs, [sum(buckets[x]) / len(buckets[x]) for x in xs], color=COLORS[name], linewidth=2, label=LABELS[name])
        ev_path = os.path.join(ROOT, name, "events.json")
        if os.path.exists(ev_path):
            with open(ev_path) as f:
                ev = json.load(f)
            if "noise_start" in ev:
                ax.axvspan(ev["noise_start"] - start, ev["noise_stop"] - start, color="#d9622b", alpha=0.07)
                ax2.axvspan(ev["noise_start"] - start, ev["noise_stop"] - start, color="#d9622b", alpha=0.07)
        if name == "burst_dynamic":
            t0 = start
            for t, e, d in read_events(name):
                if e in ("priority_on", "priority_off"):
                    for a in (ax, ax2):
                        a.axvline(t - start, color="#2a6fdb", linestyle="--", linewidth=1.2)
                    ax.text(t - start + 0.4, ax.get_ylim()[1] * 0.92, e.replace("_", " "), color="#2a6fdb", fontsize=8)
            rates = [(t - start, float(d)) for t, e, d in read_events(name) if e == "rate_mbps"]
            if rates:
                ax2.plot([r[0] for r in rates], [r[1] for r in rates], color="#2a6fdb", linewidth=2)
                ax2.axhline(8, color="#888", linestyle=":", linewidth=1)
                ax2.text(0.5, 8.3, "congestion threshold (80%)", fontsize=8, color="#666")
    ax.legend(frameon=False, loc="upper left")
    style(ax, "Game latency during a noise burst (shaded), 1 s average", "latency (ms)")
    style(ax2, "Bottleneck utilisation seen by the controller", "Mbps")
    ax2.set_xlabel("time (s)")
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, "dynamic_timeline.png"), dpi=160)
    plt.close(fig)


def burst_table(data):
    lines = ["| Scenario | Latency during burst mean / p95 / max (ms) | First 5 s of burst mean (ms) | Last 15 s of burst mean (ms) | Controller reaction (s) | Priority removed after burst (s) |",
             "|---|---|---|---|---|---|"]

    def f(v):
        return "n/a" if v is None else "%.2f" % v
    for n, s in data.items():
        b = s.get("burst")
        if not b:
            continue
        lines.append("| %s | %s / %s / %s | %s | %s | %s | %s |" % (
            LABELS[n], f(b["latency_mean_ms"]), f(b["latency_p95_ms"]), f(b["latency_max_ms"]),
            f(b["latency_first5s_mean_ms"]), f(b["latency_last15s_mean_ms"]),
            f(b["reaction_s"]), f(b["priority_off_after_s"])))
    with open(os.path.join(ROOT, "burst_table.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


def table(data):
    lines = ["| Scenario | Uplink latency mean / p95 (ms) | Uplink jitter (ms) | Uplink loss (%) | Downlink latency mean (ms) | Downlink jitter (ms) | Downlink loss (%) | RTT mean (ms) |",
             "|---|---|---|---|---|---|---|---|"]

    def f(v):
        return "n/a" if v is None else "%.2f" % v
    for n, s in data.items():
        u, d, r = s["uplink"], s["downlink"], s["rtt"]
        lines.append("| %s | %s / %s | %s | %s | %s | %s | %s | %s |" % (
            LABELS[n], f(u["latency_mean_ms"]), f(u["latency_p95_ms"]), f(u["jitter_ms"]), f(u["loss_pct"]),
            f(d["latency_mean_ms"]), f(d["jitter_ms"]), f(d["loss_pct"]), f(r["mean_ms"])))
    with open(os.path.join(ROOT, "results_table.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    burst_data = load(BURST)
    if burst_data:
        dynamic_timeline(list(burst_data))
        burst_table(burst_data)
        print("wrote dynamic_timeline.png and burst_table.md")
    data = load()
    if not data:
        if burst_data:
            raise SystemExit(0)
        raise SystemExit("no summary.json found - run analyze.py on your result folders first")
    grouped_bars(data, [("mean", lambda s: s["uplink"]["latency_mean_ms"]),
                        ("95th percentile", lambda s: s["uplink"]["latency_p95_ms"])],
                 "Game update latency, client to server", "latency (ms)", "latency.png")
    grouped_bars(data, [("uplink", lambda s: s["uplink"]["jitter_ms"]),
                        ("downlink", lambda s: s["downlink"]["jitter_ms"])],
                 "Jitter (RFC 3550)", "jitter (ms)", "jitter.png")
    grouped_bars(data, [("uplink", lambda s: s["uplink"]["loss_pct"]),
                        ("downlink", lambda s: s["downlink"]["loss_pct"])],
                 "Packet loss", "loss (%)", "loss.png")
    latency_over_time(data)
    table(data)
    print("wrote graphs and results_table.md into", os.path.abspath(ROOT))
