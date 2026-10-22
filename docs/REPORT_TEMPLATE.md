# Multiplayer Game Communication Network using UDP and SDN
Computer Networks Project Report
Team: <names and SRNs>   Date: <date>

> Replace every `<...>`. Do not leave the template text in the final report. Do not invent numbers: copy them from `results/results_table.md`.

## 1. Introduction
Real-time multiplayer games exchange small state updates many times per second. For such traffic, timeliness matters more than perfect
delivery: an old position is useless once a newer one exists. This project builds a simplified multiplayer game communication system in which
players send state updates to a game server over UDP, and a software-defined network (SDN) gives game traffic priority over background traffic.
We measure latency, jitter and packet loss under normal conditions and under congestion.

**Objectives:** UDP game-state updates; registration of multiple players; sequence numbers; packet-loss handling; traffic prioritisation with SDN;
measurement of latency and jitter; testing under congestion.

## 2. System architecture
<Insert the topology diagram from README.md or redraw it.>

| Component | Role |
|---|---|
| Game server (`srv`) | registers players, receives STATE packets, broadcasts WORLD snapshots at 20 Hz, logs packets |
| Game clients (`p1`-`p3`) | send their position at 20 Hz, detect loss, measure RTT |
| Noise hosts (`n1`, `n2`) | generate background UDP traffic to congest the bottleneck |
| Switches (`s1`, `s2`) | Open vSwitch, OpenFlow 1.3, HTB queues on the bottleneck link |
| Controller | Ryu app that installs flow rules and assigns game traffic to the priority queue |

Emulation platform: Mininet on <Ubuntu version>, Python <version>, Open vSwitch <version>, Ryu <version>.

## 3. Protocol design
UDP was chosen because the game needs the newest state with minimum delay, whereas TCP would retransmit lost packets and delay later ones (head-of-line blocking).

**Client to server packet (22 bytes)**

| Field | Size | Meaning |
|---|---|---|
| type | 1 B | 1 REGISTER, 2 REGISTER_ACK, 3 STATE, 4 PING, 5 PONG |
| player_id | 1 B | assigned at registration |
| seq | 4 B | increases by 1 per STATE packet |
| timestamp | 8 B | sender clock, used for latency and jitter |
| x, y | 4 B each | player position |

**Server to client WORLD snapshot:** 14-byte header (type, seq, timestamp, player count) followed by 9 bytes per player (id, x, y). Each client has its own server-side sequence counter.

### 3.1 Registration
<Explain: the client sends REGISTER, waits 1 s, retries up to 3 times. The server assigns the next id and replies REGISTER_ACK; a repeated REGISTER from a known address gets the same id, so a lost ACK is harmless.>

### 3.2 Sequence numbers and loss handling
<Explain: the server accepts a STATE packet only if its seq is higher than the last accepted one, so duplicates and reordered packets are discarded. The client treats a jump in WORLD seq as lost packets and counts them. Because every WORLD packet is a full snapshot, a lost packet needs no retransmission; the next snapshot replaces it, and the client keeps the last known positions in the meantime.>

### 3.3 Latency and jitter measurement
<Explain: each packet carries its send time. One-way latency = receive time - send time, valid because all Mininet hosts share one clock. RTT is measured with PING/PONG. Jitter uses the RFC 3550 estimator J = J + (|D| - J)/16, where D is the change in transit time between consecutive packets. Loss = missing sequence numbers / expected sequence numbers.>

## 4. SDN design
**Topology:** <short description>. The link s1-s2 is limited to 10 Mbps using Open vSwitch HTB QoS on both ends, with two queues: queue 1 (game, guaranteed at least 8 Mbps, higher priority) and queue 0 (best effort, everything else).

**Controller logic:** <Explain: learning switch; table-miss rule sends unknown packets to the controller; for each learned destination the controller installs a priority-1 forwarding rule and, when prioritisation is enabled, priority-10 rules matching UDP with source or destination port 5005 that use `set_queue:1`.>

<Insert screenshots: `ovs-ofctl dump-flows s1` and `ovs-vsctl list queue`.>

## 5. Experiments
Each scenario: 3 players, 40 s of play, <n> runs. Background noise: UDP, 15 Mbps in each direction across the 10 Mbps bottleneck.

| Scenario | Noise | SDN priority | Other |
|---|---|---|---|
| Baseline | none | off | - |
| Congestion, no priority | yes | off | - |
| Congestion, SDN priority | yes | on | - |
| Random loss | none | off | 5% loss on players and server |

## 6. Results
<Paste `results/results_table.md`.>

**Latency** (<insert latency.png>): <Starter: "Without noise the mean uplink latency is X ms. With congestion and no prioritisation it rises to Y ms (95th percentile Z ms), because game packets queue behind noise packets. With SDN prioritisation it falls back to W ms.">

**Jitter** (<insert jitter.png>): <Starter: "Jitter grows from X ms to Y ms under congestion and returns to Z ms with prioritisation, meaning the update stream stays smooth.">

**Packet loss** (<insert loss.png>): <Starter: "Congestion without prioritisation produced X% uplink and Y% downlink loss; with prioritisation the loss was Z%. In the random-loss scenario the measured loss was X%, close to the configured 5%, and the clients continued to run.">

**Over time** (<insert latency_over_time.png>): <Explain the shape of the curves.>

## 7. Testing and issues
<Paste the automated test list (packet round-trip, multi-player registration, duplicate registration, stale-packet rejection, ping/pong, client under 20% loss, metric calculations) and the team bug log.>

## 8. Limitations and future work
- Classification is static (by UDP port); a real deployment could use OpenFlow meters or per-flow bandwidth estimation.
- No retransmission of critical events (UDP only, by design); a game could add selective reliability for important messages.
- One-way latency relies on a shared clock (valid in Mininet; on real networks use RTT or clock synchronisation).
- Small scale (3 players, one bottleneck, one controller).
- Tail packet loss at the end of a run is not counted.

## 9. Conclusion
<Starter: "The system shows that UDP is suitable for real-time game state, that sequence numbers allow loss and reordering to be handled without retransmission, and that SDN-based traffic prioritisation keeps latency, jitter and loss low for game traffic even when the bottleneck link is saturated.">
Only keep this sentence if your numbers actually show that.

## References
- RFC 768 (UDP); RFC 3550 (RTP, jitter estimator); OpenFlow Switch Specification 1.3; Mininet documentation; Ryu documentation; Open vSwitch documentation.
