# Demo script (10 minutes, 5 speakers)

> The final, rubric-aligned demo (with the **dynamic** controller) is Section 10 of `docs/DOCUMENTATION.md`. This older script shows the static-priority demo and is kept as a fallback.

**Golden rule:** live Mininet demos fail more often than anything else. Record the full run as a video the day before and keep the four graphs open in a browser tab. If anything breaks, say "let me show the recorded run" and keep going. Never debug in front of the examiner.

## Setup (do this 15 minutes before, on Lead 3's VM)
```bash
cd game-net && git checkout main && git pull origin main
source ~/ryuenv/bin/activate
sudo mn -c
mkdir -p /tmp/demo && rm -rf /tmp/demo/*
```
Open 3 terminals in the `game-net` folder, all with the venv active in terminal 1, and a browser with the four graphs (`results/*.png`) and the report.

## Run of show

| Min | Speaker | What to do | What to say |
|---|---|---|---|
| 0:00-1:00 | Lead 5 | Show the topology diagram from the report | "Our project is a multiplayer game network. Players send their positions to a server over UDP, and an SDN controller gives game packets priority over background traffic. We measure latency, jitter and loss under congestion." |
| 1:00-2:30 | Lead 1 + Lead 2 | Show the packet table in the report, then `python3 -m unittest discover -s tests -v` in terminal 3 | "Every update is 22 bytes: type, player id, sequence number, timestamp and position. The server accepts a packet only if its sequence number is newer, so duplicates and late packets are dropped. The client counts gaps in the server's sequence numbers as lost packets and just keeps showing the last known state. Ten automated tests pass, including one with 20% packet loss." |
| 2:30-4:30 | Lead 3 | Terminal 1: `PRIORITY=on ryu-manager sdn/controller.py`. Terminal 2: `sudo python3 sdn/topology.py --controller ryu`, then `mininet> pingall` | "This is Mininet with two Open vSwitch switches and a Ryu controller. The link between the switches is limited to 10 Mbps and has two queues: queue 1 for game traffic with 8 Mbps guaranteed, queue 0 for everything else. The controller installs a rule: UDP port 5005 goes to queue 1." |
| 4:30-6:30 | Lead 3 | In the Mininet prompt, run the four commands under "Live commands" below, then in terminal 3: `sudo ovs-ofctl -O OpenFlow13 dump-flows s1 \| grep 5005` | "I'm starting the server, three players, and 15 Mbps of noise in each direction, which is more than the link can carry. This flow table shows the game rule matching packets, and the counters grow while we talk." |
| 6:30-8:30 | Lead 4 | Browser: show `results_table.md` and the latency, jitter and loss graphs | "Without priority, mean latency rises from 2.5 ms to 72 ms and jitter from 0.12 to 5.8 ms. With priority, it stays at 2.3 ms and 0.13 ms, the same as with no congestion. Latency is the receive time minus the send time, which is valid because Mininet hosts share one clock. Jitter uses the RFC 3550 estimator. Loss was zero in the congested runs because the switch queue absorbs packets, so congestion shows up as delay here." |
| 8:30-9:30 | Lead 5 | Show the limitations slide or section | "Limits: classification is by port only, loss was zero under congestion because of the deep queue, one-way latency needs a shared clock, and the network is small. Next steps would be OpenFlow meters and selective reliability for important events." |
| 9:30-10:00 | Lead 5 | Conclusion | "SDN priority protects what game traffic needs most: low and steady delay. Thank you, we're happy to take questions." |

## Live commands (Lead 3, in the `mininet>` prompt)
```
srv python3 server/server.py --duration 60 --log /tmp/demo/server_log.csv &
n2 python3 tools/noise.py sink --port 6000 &
n1 python3 tools/noise.py send --ip 10.0.0.5 --port 6000 --mbps 15 --duration 40 &
p1 python3 client/client.py --server-ip 10.0.0.10 --name p1 --duration 25 --logdir /tmp/demo &
p2 python3 client/client.py --server-ip 10.0.0.10 --name p2 --duration 25 --logdir /tmp/demo &
p3 python3 client/client.py --server-ip 10.0.0.10 --name p3 --duration 25 --logdir /tmp/demo &
```
After about 30 seconds: `python3 metrics/analyze.py /tmp/demo` in terminal 3 prints the latency, jitter and loss table.

**Optional live comparison (only if rehearsed):** stop everything, restart Ryu with `PRIORITY=off`, and repeat. Latency should jump to about 70 ms.

## Backup video checklist
- [ ] Record the whole run once, screen and voice, at least a day before.
- [ ] Keep the four PNGs and `results_table.md` ready.
- [ ] Keep the report open at the results section.
- [ ] Everyone knows who says which line. Rehearse twice with a timer.
