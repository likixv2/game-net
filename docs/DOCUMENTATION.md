# Game-Net: Multiplayer Game Communication Network
### UDP socket programming + dynamic SDN traffic prioritization (Mininet, Open vSwitch, Ryu)

SDN-Socket Programming mini project, Computer Networks.
Team: [Name 1 – SRN], [Name 2 – SRN], [Name 3 – SRN], [Name 4 – SRN], [Name 5 – SRN].
Repository: https://github.com/likixv2/game-net

---

## 0. How this document maps to the evaluation criteria

| Component (marks) | Where to look | Evidence in the repository |
|---|---|---|
| Problem understanding & architecture (2) | Section 1 | topology diagram, component table, data-flow description |
| UDP socket implementation (4) | Section 2 | `common/packet.py`, `server/server.py`, `client/client.py`, tests |
| Mininet + SDN implementation (4) | Section 3 | `sdn/topology.py`, `sdn/controller.py`, flow rules, queues |
| Socket–SDN integration (3) | Section 4 | control channel in `server/server.py`, handler in `sdn/controller.py`, `controller_events.csv` |
| Initial testing & demo (2) | Section 8 | 26 automated tests, manual test cases, demo script |
| Complete application functionality (4) | Section 2 | registration, state updates, multiple players, loss handling, RTT |
| Dynamic SDN functionality (6) | Section 5 | congestion detection, on-demand priority rules, player-based rules, removal |
| Challenging scenario / robustness (4) | Section 6 | congestion, congestion burst, packet loss, player timeout, controller absent |
| Performance evaluation & comparison (5) | Section 7 | 7 scenarios, baseline vs static vs dynamic, graphs, tables |
| Documentation, final demo & viva (6) | Sections 9–11 | reproduction steps, demo script, `docs/VIVA_QA.md` |

**Honest status of the measurements.** Scenarios 1–4 (baseline, congested without priority, congested with static priority, 5% loss) were measured on the team's Ubuntu VM. The dynamic controller and the three burst scenarios (5–7) were added afterwards; their code is unit-tested but their Mininet results must still be measured on the VM. Those cells are marked **[measure]** in Section 7 and must be filled in before submission.

---

## 1. Problem understanding and architecture

### 1.1 Problem

In an online multiplayer game, each player sends its state (position) to a server many times per second, and the server broadcasts the combined state back. The game is only playable if updates arrive **quickly (low latency)** and **evenly (low jitter)**. When other traffic fills a shared link, game packets queue behind it and both metrics degrade. A software-defined network can fix this by giving game traffic priority. A fixed rule does that, but a better controller reacts **when** congestion actually happens and **for whom** (the players that really registered with the game).

### 1.2 Objectives

1. Players exchange real-time state with a server over UDP sockets (registration, sequence numbers, packet-loss handling).
2. An SDN controller prioritizes game traffic on a congested link.
3. The controller is **dynamic**: it reacts to network conditions (bottleneck utilization) and to application events (players joining and leaving).
4. Measure latency, jitter and packet loss, and compare no priority, static priority and dynamic priority under congestion.

### 1.3 Components

| Component | File | Role |
|---|---|---|
| Packet format | `common/packet.py` | Pack/unpack functions and constants shared by everyone |
| Game server | `server/server.py` | Registration, state tracking, WORLD broadcast, logging, **notifies the SDN controller** |
| Game client (bot) | `client/client.py` | Registers, sends positions, detects loss, measures RTT, logs |
| Topology | `sdn/topology.py` | Mininet network, 10 Mbps bottleneck, OVS HTB queues |
| SDN controller | `sdn/controller.py` | Ryu OpenFlow 1.3 app: learning switch, static and dynamic priority |
| Controller decision logic | `sdn/policy.py` | Congestion detector, player registry, control-message parser (no Ryu dependency, unit tested) |
| Noise generator | `tools/noise.py` | UDP background traffic that creates congestion |
| Analyzer / plots | `metrics/analyze.py`, `metrics/plot.py` | Latency, jitter, loss, burst-reaction metrics, graphs |
| Experiment runner | `experiments/run_experiment.py`, `run_all.sh` | Runs each scenario end to end |
| Tests | `tests/test_protocol.py`, `tests/test_dynamic_sdn.py` | 26 automated tests |

### 1.4 Topology

```
 p1 \                                        / srv  (game server 10.0.0.10, UDP 5005, 2 ms link delay)
 p2 --- s1 ====== 10 Mbps bottleneck ====== s2
 p3 /    |                                   \ n2   (noise host 10.0.0.5)
        n1 (noise host 10.0.0.4)

        Ryu controller (OpenFlow 1.3, port 6653) controls s1 and s2
        srv --Unix datagram socket--> Ryu : REGISTER / LEAVE events (Section 4)
```

Players `p1`–`p3` (10.0.0.1–3) and noise host `n1` attach to switch `s1`; `srv` and `n2` attach to `s2`. The `s1`–`s2` link (`s1-eth5`, `s2-eth3`) is the **bottleneck**: 10 Mbps with two OVS HTB queues:

| Queue | Used by | Min rate | Max rate | HTB priority |
|---|---|---|---|---|
| 1 | game traffic | 8 Mbps | 10 Mbps | 1 (higher) |
| 0 | everything else | 1 Mbps | 10 Mbps | 2 |

### 1.5 Data flow (normal operation)

1. A client sends REGISTER to the server; the server assigns an id, replies REGISTER_ACK, and **tells the controller** (`REGISTER <ip> <id>`).
2. Every 50 ms each client sends a STATE packet; the server accepts it only if its sequence number is newer, logs it, and updates the player's position.
3. Every 50 ms the server sends each player a WORLD snapshot of all positions.
4. Once per second each client sends PING; the server echoes PONG (round-trip time).
5. Every second the controller reads the byte counters of the bottleneck ports. If utilization stays high it installs priority rules for the registered players' game packets; when the link calms down it removes them.

### 1.6 Expected network behaviour

Without competing traffic latency is about 2.5 ms. With 15 Mbps of noise in each direction on the 10 Mbps link, game packets queue behind the noise and latency rises to tens of milliseconds. When the controller puts game packets into the guaranteed queue, latency returns to the uncongested value.

---

## 2. UDP socket implementation and application functionality

### 2.1 Packet format

All numbers are big-endian.

**Client → server (22 bytes, `struct` format `"!BBIdff"`):** type (1), player_id (1), seq (4), timestamp (8), x (4), y (4).

**Server → client WORLD snapshot:** header `"!BIdB"` (14 bytes: type, seq, timestamp, count), then `count` entries `"!Bff"` (9 bytes: player_id, x, y).

**Types:** 1 REGISTER, 2 REGISTER_ACK, 3 STATE, 4 PING, 5 PONG, 6 WORLD. Game port UDP 5005, noise port UDP 6000.

Malformed packets (wrong length or type) raise `ValueError` and are ignored.

### 2.2 Registration of multiple players

- The client sends REGISTER and waits up to 1 s for REGISTER_ACK, retrying up to **3 times**. It ignores other packet types (such as an early WORLD packet) while waiting.
- The server assigns the next player id and remembers the client's address. A repeated REGISTER from the same address returns the **same id**, so a lost ACK is harmless. The default limit is 32 players.
- A player silent for **5 s** is removed.

### 2.3 Sequence numbers

Each client numbers its STATE packets 1, 2, 3, … The server keeps the newest accepted number per player and drops packets with `seq <= last_seq` (counted as *stale*). The server keeps a separate WORLD counter per player, and clients apply the same rule. Sequence numbers drive stale-packet rejection and loss measurement.

### 2.4 Periodic updates

Clients send STATE at 20 Hz; the server broadcasts WORLD at 20 Hz. Each WORLD packet is a **full snapshot**, so no packet depends on an earlier one.

### 2.5 Concurrency

The server is a **single-threaded, non-blocking event loop**: it waits at most 5 ms for a datagram, handles it, and every 50 ms sends the WORLD snapshots. All players share one UDP socket and are told apart by source address, so any number of clients are served concurrently without threads or locks. Each client is a separate process (one per Mininet host) with its own loop that sends, receives and pings without blocking. Using one event loop avoids data races on the shared player table.

### 2.6 Packet loss handling

UDP gives no delivery guarantee, so the design assumes packets can be lost, delayed, duplicated or reordered.

**Strategy.** For real-time state only the newest information is useful: a retransmitted position would arrive late and add load to a congested link. Loss is therefore **tolerated** for state updates and **retried** only where one lost packet would block a player entirely (registration).

| Situation | Handling |
|---|---|
| Lost REGISTER or REGISTER_ACK | Client retries up to 3 times at 1 s intervals; the server returns the same id to a repeated REGISTER |
| Lost STATE (client → server) | Not retransmitted; the next STATE (50 ms later) carries a fresh position; the gap is visible in sequence numbers |
| Lost WORLD (server → client) | Detected by a gap in WORLD sequence numbers (7 → 10 means 8 and 9 lost) and counted; the client keeps showing the last known positions until the next snapshot replaces them |
| Duplicate or out-of-order packet | `seq <= last_seq` → dropped and counted as stale |
| Lost PING or PONG | One RTT sample is skipped |
| Silent or crashed player | Removed after 5 s so the server stops sending to it |
| Malformed packet | Length and type checks; ignored |

**Loss measurement.** `expected = last_seq − first_seq + 1`, `loss % = (expected − received) / expected × 100`, per stream (player, direction) and then combined. Uplink loss comes from the server log; downlink loss from the client logs. Losses at the very end of a run are not counted.

**Loss and congestion.** In the congested runs, game-packet loss was 0% with and without priority, because the switch queue is deep and congestion turned into delay. Priority therefore improves **latency and jitter**, not loss. We do not claim otherwise.

### 2.7 Complete functionality checklist

Multiple players register (distinct ids); state updates flow in both directions at 20 Hz; stale and duplicate packets are rejected; loss is detected and tolerated; round-trip time is measured; players that go silent are removed; all packets are logged for analysis; and the server reports application events to the SDN controller.

---

## 3. Mininet and SDN implementation

### 3.1 Topology and connectivity

`sdn/topology.py` builds the network above with `TCLink` hosts and Open vSwitch switches (OpenFlow 1.3). `staticArp()` removes ARP so packets are plain unicast. The runner executes `pingAll` before each experiment to verify connectivity.

### 3.2 Queues on the bottleneck

`setup_qos()` creates the HTB queues on **both** ends of the `s1`–`s2` link (`s1-eth5`, `s2-eth3`), so both directions are shaped to 10 Mbps. Queue 1 guarantees the game traffic 8 Mbps with higher priority; queue 0 carries everything else.

### 3.3 Controller modes (`PRIORITY` environment variable)

| Mode | Behaviour | Role in the evaluation |
|---|---|---|
| `off` | Plain learning switch; everything uses queue 0 | baseline (no SDN prioritization) |
| `on` | Priority rules for UDP port 5005 are **always** installed | static approach |
| `dynamic` | Priority rules appear only under congestion and only for registered players | proposed approach |

### 3.4 Flow rules (OpenFlow 1.3)

| Priority | Match | Actions |
|---|---|---|
| 0 | anything (table miss) | send to controller |
| 1 | `in_port`, `eth_src`, `eth_dst` learned by the controller | `set_queue:0`, output to the learned port (idle timeout 60 s) |
| 10 (static) | UDP, `udp_dst=5005` or `udp_src=5005`, plus the learned in_port/MACs | `set_queue:1`, output |
| 10 (dynamic) | as above **plus** `ipv4_src=<player>` with `udp_dst=5005`, or `ipv4_dst=<player>` with `udp_src=5005` | `set_queue:1`, output; cookie `0x5005` so these rules can be removed as a group |

Both directions are matched because players send **to** port 5005 and the server replies **from** port 5005. Evidence from an earlier static-priority run: queue 1 carried 2,520 packets and queue 0 carried 45,436 packets on `s1`, and the flow table shows the port-5005 rules matching.

### 3.5 Fallback

`--controller none` installs static OVS rules with the same queues, for machines where Ryu will not install. It supports only the baseline and static scenarios.

---

## 4. Socket–SDN integration

The game application and the SDN controller are connected, so application events change network behaviour and network decisions can be observed in the application results.

### 4.1 Application → controller: player events

When the server registers a player it sends the controller a text datagram `REGISTER <ip> <id>`; when a player times out it sends `LEAVE <ip> <id>`. It also repeats `REGISTER` for every registered player every 2 s as a heartbeat, so a controller that starts later (or restarts) learns the current players.

| Property | Value |
|---|---|
| Channel | Unix datagram socket `/tmp/gamenet_ctrl.sock` (`--control-sock` on the server, `CTRL_SOCK` for the controller) |
| Why a Unix socket | Mininet hosts have separate network namespaces but share one filesystem, so the server (in `srv`) can reach the controller (in the root namespace) without extra links. It models an out-of-band control channel, like the OpenFlow channel itself |
| Messages | `REGISTER <ipv4> <id>`, `LEAVE <ipv4> <id>`; anything else is logged as `bad_control_message` and ignored |
| Failure behaviour | Sending never blocks or raises; with no controller listening the game runs unchanged (tested) |

### 4.2 Effect on the network

In dynamic mode the controller builds priority rules **per registered player IP**: a player that has not registered (or has left) gets **no** priority, even if it sends to port 5005. If a player registers while congestion is active, the controller installs its rules immediately; if a player leaves, its rules are removed.

### 4.3 Network → application (observability)

The controller logs every decision with a timestamp to `controller_events.csv` (`player_register`, `player_leave`, `rate_mbps`, `congestion_detected`, `priority_on`, `congestion_cleared`, `priority_off`). The analyzer and plots align these events with the game logs, so the effect of a network decision on the application is visible end to end.

### 4.4 End-to-end sequence (dynamic scenario)

```
t = 0 s    clients REGISTER -> server ACKs -> server sends "REGISTER ip id" -> controller registers players
t = 10 s   noise starts; bottleneck utilization rises; game latency rises
t = 11-12  controller sees >= 80% utilization for 2 samples -> "congestion_detected"
           -> installs priority-10 rules for each registered player -> game packets use queue 1
t = 12-13  game latency falls back to about the uncongested value
t = 35 s   noise stops; utilization drops below 50% for 3 samples
           -> "congestion_cleared" -> priority rules are removed
```

---

## 5. Dynamic SDN functionality

### 5.1 Mechanism

Every `POLL_SECONDS` (1 s) the controller sends an `OFPPortStatsRequest` for the bottleneck port of each switch and computes the transmit rate from the change in `tx_bytes`. The busiest direction is fed to a **hysteresis detector** (`sdn/policy.py`):

| Parameter | Value | Meaning |
|---|---|---|
| Capacity | 10 Mbps | bottleneck rate |
| High threshold | 80% (8 Mbps) | counts toward turning priority **on** |
| Samples to turn on | 2 consecutive | avoids reacting to a single burst |
| Low threshold | 50% (5 Mbps) | counts toward turning priority **off** |
| Samples to turn off | 3 consecutive | avoids flapping |

While priority is active the link stays saturated (noise plus game packets), so the detector keeps priority on until the noise really ends.

### 5.2 Rule lifecycle

- **Enable:** for every flow the controller has learned and every registered player, install the two priority-10 rules (cookie `0x5005`).
- **Disable:** one flow-delete with `cookie = 0x5005` and a full cookie mask removes all game priority rules and nothing else.
- **New flows** learned while priority is active get their rules immediately.
- **Player joins or leaves while active:** the rule set is rebuilt.

### 5.3 What makes it dynamic

| Condition | Controller response |
|---|---|
| Utilization high for 2 s | enable priority |
| Utilization low for 3 s | disable priority |
| Player registers | include it in the priority rules |
| Player leaves or times out | remove its rules |
| Unregistered sender uses port 5005 | no priority |

### 5.4 Unit-tested behaviour

The controller is exercised with simulated switches that use Ryu's real OpenFlow 1.3 message classes (each message is serialized to check it is well formed): dynamic mode starts without priority rules; rules appear only after two high samples; rules exist only for registered players and match their IP; priority turns off after three quiet samples and removes only the controller's own rules; leave removes a player's rules; static mode ignores the detector; off mode never prioritizes.

---

## 6. Challenging scenarios and robustness

| Scenario | How it is produced | Expected and observed system response |
|---|---|---|
| Sustained congestion | 15 Mbps of UDP noise in each direction on a 10 Mbps link for the whole run | Without priority latency rises to 72 ms; with priority it stays at 2.3 ms (measured) |
| **Congestion burst** | Noise starts 10 s into the run and lasts 25 s | Dynamic controller detects it and enables priority within seconds, then removes it after the burst (Section 7, to measure) |
| Random packet loss | `tc netem loss 5%` on every player and the server link | Clients detect gaps and keep playing; loss is measured from sequence numbers |
| Lost registration packets | Lossy proxy in the tests | Registration retries succeed |
| Player disappears | Client stops sending | Server removes it after 5 s and tells the controller (`LEAVE`) |
| Controller absent or late | Server runs with no listener on the control socket | Game unaffected; heartbeat informs a later controller (tested) |
| Malformed packets | Garbage or truncated datagrams | Ignored by server, client and controller |

**Limitation of the 5% loss test.** The measured run applied loss to the uplink only (uplink loss 5.33% against 5% configured; downlink 0.00%): the server link already had a netem delay qdisc, so `tc qdisc add` failed silently there. The runner now uses `tc qdisc replace` and saves `tc_loss_setup.txt` as evidence. **The scenario must be rerun** before the downlink loss result is cited.

---

## 7. Performance evaluation and comparison

### 7.1 Method

- **Latency (one-way)** = receive time − send time. Valid because every Mininet host uses one machine clock. We report mean, 95th percentile and maximum.
- **Jitter** (RFC 3550): for consecutive packets `D = (recv₂ − recv₁) − (send₂ − send₁)` and `J ← J + (|D| − J) / 16`.
- **Loss:** from sequence-number gaps (Section 2.6).
- **RTT:** the client's PING timestamp echoed in PONG.
- **Uplink** = player → server (server log); **downlink** = server → player (client logs).
- **Burst metrics** (burst scenarios only): latency during the noise window, latency in its first 5 s and last 15 s, controller reaction time (noise start → `priority_on`) and removal delay (noise stop → `priority_off`).

### 7.2 Scenarios

Three players, 40 s per run (burst scenarios 45 s).

| # | Scenario | Noise | Priority mode | Loss | Purpose |
|---|---|---|---|---|---|
| 1 | `baseline` | none | off | 0 | reference without congestion |
| 2 | `congested_noprio` | constant 15 Mbps each way | off | 0 | congestion without SDN help |
| 3 | `congested_prio` | constant | on (static) | 0 | static SDN priority |
| 4 | `loss5` | none | off | 5% | loss handling |
| 5 | `burst_noprio` | burst 10–35 s | off | 0 | burst without SDN help |
| 6 | `burst_static` | burst | on (static) | 0 | static priority under a burst |
| 7 | `burst_dynamic` | burst | **dynamic** | 0 | **proposed approach** |

Comparisons: **no priority** (2, 5) is the baseline approach; **static priority** (3, 6) is the static approach; **dynamic** (7) is the proposed approach. The dynamic approach should match static priority on latency during congestion while installing rules only when and for whom they are needed.

### 7.3 Results, scenarios 1–4 (measured on the team VM)

| Scenario | Uplink latency mean / p95 (ms) | Uplink jitter (ms) | Uplink loss | Downlink latency (ms) | Downlink jitter (ms) | RTT mean (ms) |
|---|---|---|---|---|---|---|
| Baseline | 2.49 / 2.72 | 0.12 | 0% | 2.54 | 0.11 | 4.98 |
| Congested, no priority | 72.37 / 93.25 | 5.76 | 0% | 72.81 | 5.56 | 149.52 |
| Congested, static priority | **2.33 / 2.51** | **0.13** | 0% | 2.42 | 0.15 | **4.68** |
| 5% loss (uplink only, see Section 6) | 2.48 / 2.68 | 0.13 | 5.33% | 2.55 | 0.15 | 5.05 |

Interpretation: static SDN priority cut mean uplink latency from **72.37 ms to 2.33 ms**, matching the uncongested baseline (2.49 ms); jitter fell from 5.76 ms to 0.13 ms and RTT from 149.52 ms to 4.68 ms. Loss was 0% in both congested runs, so priority improved delay and jitter, not loss.

### 7.4 Results, burst scenarios 5–7 (to be measured)

Fill from `results/burst_table.md` after running the scenarios on the VM.

| Scenario | Latency during burst mean / p95 / max (ms) | First 5 s of burst mean (ms) | Last 15 s of burst mean (ms) | Controller reaction (s) | Priority removed after burst (s) |
|---|---|---|---|---|---|
| Burst, no priority | [measure] | [measure] | [measure] | – | – |
| Burst, static priority | [measure] | [measure] | [measure] | – | – |
| Burst, dynamic SDN | [measure] | [measure] | [measure] | [measure] | [measure] |

What the measurement should show if the design works (a hypothesis to confirm, not a result): no-priority latency stays high for the whole burst; static priority stays low throughout; dynamic shows a short spike at the start of the burst (before the controller reacts) and then falls to the static value, with priority removed a few seconds after the noise stops. The graph `results/dynamic_timeline.png` plots latency over time for all three burst scenarios, the noise window, the controller's `priority_on` / `priority_off` events, and the bottleneck utilization the controller saw.

### 7.5 Graphs and tables

`results/latency.png`, `jitter.png`, `loss.png`, `latency_over_time.png`, `dynamic_timeline.png`; `results/results_table.md`, `results/burst_table.md`. Per-scenario evidence: `summary.json`, `controller_events.csv`, `ovs_queue_stats.txt`, `flows_during_burst.txt`, `flows_after_burst.txt`, `tc_loss_setup.txt`.

---

## 8. Testing

### 8.1 Automated tests (26)

Run with `python3 -m unittest discover -s tests -v`. Expected last line: `OK`. The 8 controller-logic tests need Ryu and are skipped automatically where it is not installed (the VM runs all 26).

| Area | Test cases |
|---|---|
| Packet format | message and WORLD round trips; malformed packets rejected |
| Metrics | constant delay gives zero jitter; loss detected from gaps; varying delay gives jitter |
| Registration | distinct ids for several players; repeated REGISTER returns the same id |
| Sequence numbers | stale and duplicate packets dropped, order preserved |
| Ping/pong | timestamp echoed |
| Packet loss | client survives 20% loss through a lossy proxy and counts it |
| Congestion detector | needs 2 consecutive high samples; turns off only after 3 quiet samples; reports only transitions; rate calculation; counter reset |
| Control messages | valid and invalid REGISTER/LEAVE messages; player registry |
| Socket–SDN link | server sends REGISTER then LEAVE (after the 5 s timeout) on the control socket; server unaffected when no controller listens |
| Controller logic | rule set per mode (static, dynamic, off); rules only for registered players; leave removes rules; congestion on/off cycle and event log; bad messages ignored |

### 8.2 Manual and system test cases

| # | Test | Expected |
|---|---|---|
| T1 | `pingall` in Mininet | 0% dropped |
| T2 | Start server and 3 clients | 3 registrations, ids 1–3, state flowing |
| T3 | Port-5005 rule present after congestion starts (`ovs-ofctl dump-flows s1`) | priority-10 rules with `set_queue:1`, packet counters growing |
| T4 | Queue counters (`queue-stats`) | game packets in queue 1, noise in queue 0 |
| T5 | Noise stops | rules disappear after a few seconds; `priority_off` in the controller log |
| T6 | Kill a client | `player_leave` in the controller log after about 5 s |
| T7 | Run with no controller listening | game works |
| T8 | `analyze.py` on each result folder | table with latency, jitter, loss |

### 8.3 Issues found and fixed

| Issue | Fix |
|---|---|
| Flaky loss test: lossy proxy dropped registration packets | proxy never drops REGISTER or REGISTER_ACK |
| Test read a queued WORLD packet as the ACK | registration loops until a REGISTER_ACK arrives |
| `loss5` applied loss on the uplink only | `tc qdisc replace`, including the server's delay |
| Ryu fails on Python 3.10 | virtual environment, `eventlet==0.33.3`, `dnspython==2.2.1`, one-line `wsgi.py` patch |
| Corrupted `run_experiment.py` and truncated test file on branches | restored from known-good commits |

### 8.4 Pre-submission check

`bash scripts/fresh_clone_check.sh` clones the repository into a clean folder and checks required files, no junk files, compilation, tests, and a short local game run with the analyzer.

---

## 9. Reproducing the results

### 9.1 Local game, no Mininet (any machine)

```bash
python3 -m unittest discover -s tests -v
mkdir -p results/local
python3 server/server.py --port 5005 --log results/local/server_log.csv --duration 20 &
python3 client/client.py --name p1 --duration 10 --logdir results/local &
python3 client/client.py --name p2 --duration 10 --logdir results/local &
sleep 12
python3 metrics/analyze.py results/local
```

### 9.2 Environment for the full experiment (Ubuntu 22.04 VM)

```bash
sudo apt update && sudo apt install -y mininet openvswitch-switch python3-pip python3-venv
sudo service openvswitch-switch start
python3 -m venv ~/ryuenv && source ~/ryuenv/bin/activate
pip install ryu eventlet==0.33.3 dnspython==2.2.1 matplotlib
# Python 3.10 only: patch Ryu once (the controller does not use the REST API)
sed -i 's/from eventlet.wsgi import ALREADY_HANDLED/ALREADY_HANDLED = b""/' \
  ~/ryuenv/lib/python3.10/site-packages/ryu/app/wsgi.py
```

### 9.3 Check the bottleneck port numbers (once)

The controller assumes switch `s1` is datapath 1 with the bottleneck on port 5, and `s2` is datapath 2 with the bottleneck on port 3. Verify:

```bash
sudo python3 sdn/topology.py --controller none      # then in another terminal:
sudo ovs-ofctl -O OpenFlow13 show s1 | grep -E "s1-eth5|s1-eth"
sudo ovs-ofctl -O OpenFlow13 show s2 | grep -E "s2-eth3|s2-eth"
```

If different, start the controller with `BOTTLENECK="<dpid>:<port>,<dpid>:<port>"`.

### 9.4 Run everything

```bash
cd game-net && source ~/ryuenv/bin/activate
sudo env "PATH=$PATH" bash experiments/run_all.sh        # 7 scenarios, about 10 minutes, then the graphs
```

Single scenario: `sudo env "PATH=$PATH" python3 experiments/run_experiment.py --scenario burst_dynamic`, then `python3 metrics/analyze.py results/burst_dynamic`.

Outputs per scenario are in `results/<scenario>/`; the graphs and tables are in `results/`.

### 9.5 Troubleshooting

| Problem | Fix |
|---|---|
| `ryu-manager: command not found` under sudo | use `sudo env "PATH=$PATH" …` with the venv active |
| Controller never enables priority | check `controller_events.csv`: if `rate_mbps` stays near 0, the bottleneck port numbers are wrong (Section 9.3) |
| No `player_register` events | the server was started without `--control-sock`, or the socket path differs (`CTRL_SOCK`) |
| Leftover Mininet state | `sudo mn -c` |

---

## 10. Final demonstration (about 10 minutes)

Golden rule: record the full run as a video the day before and keep the graphs open in a browser. If anything breaks, play the recording.

**Setup (15 minutes before)**

```bash
cd game-net && git checkout main && git pull origin main
source ~/ryuenv/bin/activate
sudo mn -c
mkdir -p /tmp/demo && rm -rf /tmp/demo/*
```

Open three terminals in the repository (venv active in terminal 1) and a browser with `results/*.png`, the tables, and this document.

| Min | Who | Do | Say |
|---|---|---|---|
| 0:00–1:00 | Lead 5 | Show the topology and the criteria table | the problem, the objectives, and that the controller is dynamic |
| 1:00–2:00 | Leads 1 + 2 | Terminal 3: `python3 -m unittest discover -s tests -v` | packet format, registration, sequence numbers, loss handling; 26 tests pass |
| 2:00–3:30 | Lead 3 | T1: `PRIORITY=dynamic CTRL_LOG=/tmp/demo/controller_events.csv ryu-manager sdn/controller.py`; T2: `sudo python3 sdn/topology.py --controller ryu`, then `pingall` | two OVS switches, Ryu, 10 Mbps bottleneck with two queues; controller starts with no priority rules |
| 3:30–6:30 | Lead 3 | Live dynamic demo (below) | players register and the controller learns them; noise starts; controller reacts; noise stops; rules disappear |
| 6:30–8:30 | Lead 4 | Show `dynamic_timeline.png`, `results_table.md`, `burst_table.md` | no priority vs static vs dynamic; 72.37 ms to 2.33 ms; reaction time |
| 8:30–9:30 | Lead 5 | Limitations | port-only classification, deep queue (no loss), shared clock, small network |
| 9:30–10:00 | Lead 5 | Conclusion | priority only when and for whom it is needed |

**Live dynamic demo** (at the `mininet>` prompt; `srv` is 10.0.0.10, `n1` 10.0.0.4, `n2` 10.0.0.5)

```
srv python3 server/server.py --duration 90 --log /tmp/demo/server_log.csv --control-sock /tmp/gamenet_ctrl.sock &
n1 python3 tools/noise.py sink --port 6000 &
n2 python3 tools/noise.py sink --port 6000 &
p1 python3 client/client.py --server-ip 10.0.0.10 --name p1 --duration 70 --logdir /tmp/demo &
p2 python3 client/client.py --server-ip 10.0.0.10 --name p2 --duration 70 --logdir /tmp/demo &
p3 python3 client/client.py --server-ip 10.0.0.10 --name p3 --duration 70 --logdir /tmp/demo &
```

Terminal 3: `sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep 5005` → **no rules yet**; `tail /tmp/demo/controller_events.csv` → three `player_register` events.

Start the noise (Mininet prompt):

```
n1 python3 tools/noise.py send --ip 10.0.0.5 --port 6000 --mbps 15 --duration 25 &
n2 python3 tools/noise.py send --ip 10.0.0.4 --port 6000 --mbps 15 --duration 25 &
```

After about 5 s: repeat the `dump-flows | grep 5005` (priority-10 rules with `ipv4_src`/`ipv4_dst` and `set_queue:1`) and `tail /tmp/demo/controller_events.csv` (`congestion_detected`, `priority_on`). About 8 s after the noise ends: the rules are gone and `priority_off` is logged. At the end: `python3 metrics/analyze.py /tmp/demo`.

Backup checklist: video recorded; graphs and tables open; rehearsed twice with a timer; `fresh_clone_check.sh` passes.

---

## 11. Limitations and future work

**Limitations**

- Congestion detection uses bottleneck utilization with fixed thresholds; it reacts after a delay of a few seconds (measured in the burst scenarios).
- Game traffic is identified by UDP port and registered IP, not by deeper inspection.
- Zero loss under congestion comes from the deep switch queue; congestion appears as delay.
- One-way latency assumes a shared clock (valid in Mininet only).
- The control channel is a local Unix socket, which suits an emulated network but would be a network or management API in a real deployment.
- Small topology: 3 players, one bottleneck, one server.
- The downlink result of the 5% loss scenario and the burst results are pending measurement on the VM.

**Future work (not implemented)**

- OpenFlow meters or per-flow bandwidth control instead of fixed queues.
- Selective reliability for important game events.
- Shallower queues to study loss under congestion.
- More players, more links, and multiple bottlenecks.

---

## 12. Repository layout and references

```
common/packet.py          shared packet format
server/server.py          game server (+ control channel to the controller)
client/client.py          game client / bot
sdn/topology.py           Mininet topology and OVS queues
sdn/controller.py         Ryu controller (off / on / dynamic)
sdn/policy.py             congestion detector, player registry, control-message parser
tools/noise.py            background traffic
metrics/analyze.py        latency, jitter, loss, burst metrics
metrics/plot.py           graphs and tables
experiments/              run_experiment.py, run_all.sh
tests/                    test_protocol.py, test_dynamic_sdn.py
scripts/                  fresh_clone_check.sh
docs/                     this document, guides, demo script, viva Q&A
```

**References:** RFC 768 (UDP); RFC 3550 (RTP, jitter estimator); OpenFlow Switch Specification 1.3; Mininet (http://mininet.org); Open vSwitch (https://www.openvswitch.org); Ryu SDN Framework (https://ryu-sdn.org).
