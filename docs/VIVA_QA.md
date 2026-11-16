# Viva questions with model answers (whole team)

Everyone reads all of it. Each lead must be able to answer their own section without notes. Lead 5 asks the questions in random order.

## General (anyone can be asked)
1. **What does the project do?** Players send game state to a server over UDP. An SDN controller prioritizes game packets over background traffic. We measure latency, jitter and loss under congestion.
2. **Why UDP and not TCP?** TCP retransmits and delivers in order, so one lost packet delays everything behind it. A game wants the newest state, not an old one delivered late. UDP has no such delay.
3. **Why is Mininet valid for the timing measurements?** All hosts share one machine clock, so receive time minus send time is a true one-way delay. On a real network you would use round-trip time or synchronized clocks.
4. **What was your key result?** Under 15 Mbps of noise in each direction on a 10 Mbps link, mean latency was 72 ms without priority and 2.3 ms with it; jitter was 5.8 ms vs 0.13 ms. Baseline was 2.5 ms and 0.12 ms.
5. **Why was there no packet loss under congestion?** The switch queue is deep, so packets waited (delay) instead of being dropped. Priority therefore improved delay and jitter, not loss.
6. **What would you improve?** Use OpenFlow meters or per-flow bandwidth estimation, add selective reliability for important events, test more players and more links.

## Lead 1: server and protocol
1. **What is in a packet?** 22 bytes: type, player id, sequence number, timestamp, x, y, packed with `struct` in network byte order.
2. **How does registration work?** The client sends REGISTER; the server assigns the next player id and replies REGISTER_ACK. A repeated REGISTER from the same address returns the same id, so a lost ACK is harmless.
3. **What does the server do with an old sequence number?** If it is not higher than the last accepted one, the packet is dropped and counted as stale.
4. **What does the server broadcast, and how often?** A full WORLD snapshot of all players, 20 times a second, with a separate sequence counter per player.
5. **What happens to a silent player?** It is removed after 5 seconds.
6. **Why log every packet?** The logs (player id, seq, send time, receive time) are what the analyzer uses for latency, jitter and loss.

## Lead 2: client and reliability
1. **How do you detect loss?** A jump in the server's WORLD sequence numbers: after 7, receiving 10 means 8 and 9 were lost.
2. **What do you do with a late or duplicate packet?** Discard it; applying it would move players back in time.
3. **Do you retransmit?** No, by design. Each WORLD packet is a full snapshot, so the next one replaces a lost one. Only registration is retried (3 times, 1 s each).
4. **What does the client show while packets are missing?** The last known positions.
5. **How is round-trip time measured?** The client sends PING with its time; the server echoes it in PONG; RTT is arrival time minus the echoed time.

## Lead 3: SDN
1. **What is SDN?** Separating the control plane (the controller that decides) from the data plane (switches that forward), with the controller programming switches through OpenFlow flow rules.
2. **How does your controller prioritize game traffic?** It matches UDP packets with source or destination port 5005 at priority 10 and applies `set_queue:1`; everything else uses queue 0.
3. **Why do you need a bottleneck?** Priority only matters when a link is congested. With spare capacity nothing queues, so there is nothing to prioritize.
4. **Why match both source and destination port?** Players send to port 5005; the server's replies come from port 5005.
5. **What happens to the first packet of a flow?** No rule matches, so the switch sends it to the controller; the controller learns the sender's port, installs rules and forwards the packet.
6. **How do you know it works?** The queue counters show game packets in queue 1 and noise in queue 0 (2,520 vs 45,436 packets in our run), and the flow table shows the port-5005 rules matching.
7. **What were the installation problems?** Ryu on Python 3.10 needs eventlet 0.33.3, dnspython 2.2.1 and a one-line patch to Ryu's REST helper, which our controller does not use.

## Lead 4: measurement
1. **How is latency computed?** Receive time minus send time per packet; we report mean, 95th percentile and maximum.
2. **What is jitter and how do you compute it?** Variation in delay. For consecutive packets D = (recv2 - recv1) - (send2 - send1), and J = J + (|D| - J) / 16 (RFC 3550). A constant delay gives zero jitter.
3. **How is loss computed?** Expected = last sequence number - first + 1; loss = (expected - received) / expected. Losses at the very end of a run are not counted.
4. **Why the 95th percentile?** The mean hides bad moments; p95 says 95% of updates arrived within that time.
5. **What are uplink and downlink?** Uplink: player to server, logged at the server. Downlink: server to player, logged at each client.
6. **How did you create congestion?** UDP noise at 15 Mbps in each direction between two hosts, crossing the 10 Mbps bottleneck.
7. **Anything wrong in your results?** In the 5% loss scenario only the uplink loss was applied (5.33%); the server link's existing delay rule made the second rule fail silently. The runner now replaces the rule, and the scenario should be rerun.

## Lead 5: integration
1. **How did you test the system?** Ten automated tests (packet format, metric calculations, registration, stale packets, ping/pong, loss) plus four experiment scenarios in Mininet.
2. **What bugs did you find?** Two flaky tests (the lossy test proxy dropped registration packets; a queued broadcast was read instead of the ACK), a truncated test file on one branch, and the one-direction loss rule.
3. **How is the work split?** Server and protocol; client and reliability; SDN; measurement; integration and report.
4. **How do you reproduce the results?** `sudo env "PATH=$PATH" bash experiments/run_all.sh` on the VM, then `python3 metrics/plot.py`.

## Dynamic SDN and integration (Lead 3 and Lead 5 must both be able to answer)
1. **What makes your controller dynamic?** It reads the byte counters of the bottleneck port every second. After 2 samples above 80% utilization it installs priority rules; after 3 samples below 50% it removes them. It also reacts to players joining and leaving.
2. **How does the application influence the SDN?** The game server sends `REGISTER <ip> <id>` and `LEAVE <ip> <id>` to the controller on a Unix datagram socket. The controller installs priority rules only for registered players' IPs.
3. **Why a Unix socket?** Mininet hosts have separate network namespaces but share the filesystem, so the server in `srv` can reach the controller in the root namespace without extra links. It models an out-of-band control channel.
4. **What if the controller is not running?** The server's send never blocks or raises; the game runs unchanged, and the 2-second heartbeat informs a controller that starts later. This is tested.
5. **Why hysteresis (2 samples up, 3 down)?** One noisy sample should not toggle rules; and while priority is on the link stays saturated, so the controller keeps it on until the noise really ends.
6. **How are the priority rules removed?** They carry cookie 0x5005; one flow-delete with that cookie and a full mask removes them and nothing else.
7. **Static vs dynamic priority: what is the difference and what do the results show?** Static always has the port-5005 rules; dynamic installs them only during congestion and only for registered players. (Quote the burst table once it is measured: latency during the burst, controller reaction time.)
8. **What is the weakness of the dynamic approach?** There is a short delay before the controller reacts (polling interval plus 2 samples), during which latency is high; fixed thresholds; port-and-IP classification only.
9. **How does the server handle many clients concurrently?** One single-threaded non-blocking loop on one UDP socket; players are told apart by source address; no locks needed.
10. **What would you do with a real network?** Use a management API (REST or gRPC) for the control channel, OpenFlow meters, and per-flow bandwidth estimation.
