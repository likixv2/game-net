# Lead 4 - Measurement & Experiments

**Your files:** `metrics/analyze.py`, `metrics/plot.py`, `tools/noise.py`, `experiments/run_experiment.py`, `experiments/run_all.sh`
**Your mission:** produce the numbers and graphs that prove the project works: latency, jitter, packet loss, in four scenarios.
Your output is the "Results" chapter of the report.

All code is written and the analyzer is tested. You can start **right now**, before the network is ready.

---

## The three metrics (learn these definitions - they are the viva)
- **Latency (one-way)** = `recv_ts - send_ts`. Valid in Mininet because all hosts share one clock. Plus **RTT** from PING/PONG.
- **Jitter** = how much latency *changes* from packet to packet. We use the RFC 3550 estimator:
  `D = (recv_j - recv_i) - (send_j - send_i)`, then `J = J + (|D| - J) / 16`. Constant delay -> jitter 0.
- **Packet loss %** = share of sequence numbers between the first and last that never arrived.

Uplink = player -> server (`server_log.csv`). Downlink = server -> player (`client_*_log.csv`).

## Step 0 - Setup (5 min)
```bash
cd game-net
python3 -m unittest discover -s tests -v          # the analyzer tests are in there
pip3 install matplotlib
```

## Step 1 - Practise on fake data BEFORE the network is ready (20 min)
Run the game on one laptop and analyse it:
```bash
mkdir -p results/local
python3 server/server.py --port 5005 --log results/local/server_log.csv --duration 25 &
python3 client/client.py --name p1 --duration 15 --logdir results/local &
python3 client/client.py --name p2 --duration 15 --logdir results/local &
sleep 18
python3 metrics/analyze.py results/local
```
You get a table of latency mean/p95/max, jitter, loss (uplink and downlink) and RTT, and `results/local/summary.json`.
On one laptop everything is about 0.1 ms with 0% loss. That is correct: no network, no problem.

## Step 2 - Understand the analyzer (30 min)
Open `metrics/analyze.py`:
- `read_rows` reads a CSV into numbers.
- `stream_metrics(rows)` works on ONE player's packets in ONE direction: latencies, final jitter, received vs expected.
- `combine(streams)` merges the players: mean/p95/max latency over all packets, average of the jitters, total loss.
- `analyze(folder)` does uplink + downlink + RTT and writes `summary.json`.
Why p95? The mean hides bad moments. "95% of updates arrived within X ms" is what game developers quote.

Try breaking it: edit a copy of `server_log.csv`, delete 10% of the rows, re-run - loss should be about 10%.

## Step 3 - The noise generator (10 min)
`tools/noise.py` creates congestion without iperf:
```bash
python3 tools/noise.py sink --port 6000 &                       # receiver
python3 tools/noise.py send --ip 127.0.0.1 --port 6000 --mbps 15 --duration 5
```
In the experiment, 15 Mbps is sent in **both directions** across a **10 Mbps** link, so the link is overloaded.
Optional: the same with iperf (`iperf -s -u` on n2, `iperf -c 10.0.0.5 -u -b 15M -t 30` on n1).

## Step 4 - Run the real experiments (needs Lead 3's network; do it together) (30-40 min)
```bash
sudo bash experiments/run_all.sh          # runs baseline, congested_noprio, congested_prio, loss5, then plots
# or one at a time:
sudo python3 experiments/run_experiment.py --scenario congested_prio
```
(`sudo bash experiments/run_all.sh none` if Lead 3 is using the no-Ryu fallback.)
Each scenario takes about 1 minute. Results land in `results/<scenario>/` including `summary.json` and `ovs_queue_stats.txt`.
Then: `python3 metrics/plot.py` produces in `results/`: `latency.png`, `jitter.png`, `loss.png`, `latency_over_time.png`, `results_table.md`.

**What you should expect to see** (if the numbers do not look like this, tell Lead 3):
- `baseline`: latency a few ms, jitter tiny, loss ~0%.
- `congested_noprio`: latency and jitter much higher (queues fill), and loss.
- `congested_prio`: close to baseline again. **This difference is the key result.**
- `loss5`: loss about 5% (uplink and downlink), the game keeps running.

Run each scenario 2-3 times if you have time and report the average; one run can be unlucky.

## Step 5 - Write the results (20 min)
Open `results/results_table.md`, paste it into the report, and write 4-5 sentences for each graph: what the axes are, what changed
between scenario 2 and 3, and why (priority queue protected the game traffic). `docs/REPORT_TEMPLATE.md` has sentence starters.

## You are DONE when
- [ ] `results/` contains the four PNGs and `results_table.md`
- [ ] `congested_prio` is clearly better than `congested_noprio` in latency, jitter and loss
- [ ] you can explain how jitter is computed on a whiteboard with 4 packets

---

## LLM prompt pack (paste PROJECT CONTEXT from README.md first)

**P1 - Explain the metrics**
> Explain latency, jitter and packet loss for a beginner. Explain the RFC 3550 jitter formula J = J + (|D| - J)/16 with a worked example using 5
> packets with these (send_ts, recv_ts) pairs: <make up 5 pairs>. Why divide by 16?

**P2 - Explain my analyzer**
> Here is my `analyze.py`: ```<paste>```. Explain every function. Then give me 3 tiny CSV test files with known answers (one with zero jitter, one with
> 10% loss, one with alternating 10 ms / 30 ms latency) and tell me what numbers the script must print.

**P3 - Interpret my results**
> Here are my results for 3 scenarios (baseline, congestion without SDN priority, congestion with SDN priority): ```<paste results_table.md>```.
> Write a short analysis (150 words) for my report: what changed, why, and what it proves about SDN prioritization. Also point out anything
> in the numbers that looks suspicious or contradictory so I can double check it.

**P4 - Make a better graph**
> Here is my plotting script: ```<paste metrics/plot.py>```. Change it so <e.g. "the latency-over-time graph uses a log y-axis" / "it adds error bars from 3 runs">.
> Keep the colours: grey = baseline, orange = congestion without priority, blue = congestion with priority. Give me the full changed file.

**P5 - Priority made no difference**
> In my experiment, congested_prio looks the same as congested_noprio. Numbers: ```<paste>```. Content of results/congested_prio/ovs_queue_stats.txt: ```<paste>```.
> List the most likely causes in order and the exact commands to check each one.

**P6 - Viva practice**
> Be my examiner on measurement for a UDP game network project. One question at a time: how latency is measured, why timestamps work in Mininet but not on
> the real internet, jitter formula, loss calculation from sequence numbers, why p95. Feedback and the ideal answer after each.

---

## Common errors
| Problem | Fix |
|---|---|
| all graphs flat / identical across scenarios | priority not working, or noise not running; open `results/<scenario>/*.out` and `ovs_queue_stats.txt`; ask Lead 3 |
| `summary.json` values are `null` | the logs are empty: the server/clients crashed; read the `.out` files in that folder |
| `ryu-manager: command not found` under sudo | `sudo env "PATH=$PATH" python3 experiments/run_experiment.py ...` or use the `none` fallback |
| `matplotlib` missing | `pip3 install matplotlib` (if using sudo: `sudo pip3 install matplotlib --break-system-packages`) |
| negative latency | clocks differ (not Mininet, or different machines); run everything inside Mininet |

## Viva questions (practice answers)
1. **How do you measure latency?** Every packet carries its send time; the receiver subtracts it from its arrival time. All Mininet hosts share one system clock, so no clock synchronisation problem. RTT via ping/pong avoids needing synchronised clocks at all.
2. **What is jitter and why does it matter for games?** Variation in delay. Even if average latency is fine, uneven arrival makes movement stutter.
3. **How do you compute loss?** Sequence numbers are consecutive per player, so `expected = last - first + 1`, and loss = `(expected - received) / expected`.
4. **Why did congestion hurt without priority?** The 10 Mbps link is overloaded, packets wait in the same queue as the noise (queueing delay) or are dropped when the queue is full.
5. **Why does priority fix it?** Game packets use their own queue with guaranteed bandwidth and higher priority, so they do not wait behind noise packets.
6. **Limitations?** Tail loss (the last packets) is not counted; one-way times only valid on a shared clock; results vary a little between runs.
