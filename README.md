# Multiplayer Game Communication Network (UDP + SDN)

Computer Networks project. Players exchange real-time game state over **UDP**; an **SDN controller (Ryu + Open vSwitch)**
gives game traffic priority over background traffic. We measure **latency, jitter and packet loss** under congestion.

## What is in this folder

| Path | What | Owner |
|---|---|---|
| `common/packet.py` | packet format shared by everyone | Lead 1 |
| `server/server.py` | game server (registration, state, broadcast, logging) | Lead 1 |
| `client/client.py` | game client/bot (sequence numbers, loss detection, RTT) | Lead 2 |
| `sdn/topology.py` | Mininet network + bottleneck link + OVS queues | Lead 3 |
| `sdn/controller.py` | Ryu OpenFlow app that prioritises game traffic | Lead 3 |
| `tools/noise.py` | background traffic generator (creates congestion) | Lead 4 |
| `metrics/analyze.py` | latency / jitter / loss from the CSV logs | Lead 4 |
| `metrics/plot.py` | graphs and results table | Lead 4 |
| `experiments/run_experiment.py`, `run_all.sh` | runs the 4 test scenarios | Lead 4 |
| `tests/test_protocol.py` | automated tests | Lead 5 |
| `docs/LEAD1..5_*.md` | **step-by-step guide + LLM prompts for each lead** | everyone |
| `docs/REPORT_TEMPLATE.md` | report skeleton with draft text | Lead 5 |

**Everyone: open your own file in `docs/` first.** It tells you exactly what to do, what to run, and gives you prompts for your LLM.

## Architecture

```
 p1 \                                      / srv  (game server, UDP 5005)
 p2 -- s1 ===== 10 Mbps bottleneck ===== s2
 p3 /   |                                  \ n2   (noise)
       n1 (noise)
            ^ both switches are controlled by Ryu (controller.py) and have 2 queues on the bottleneck:
              queue 1 = game traffic (guaranteed 8 Mbps, higher priority), queue 0 = everything else
```

Packets (all UDP, port 5005):

- Client -> server, 22 bytes: `type(1) | player_id(1) | seq(4) | timestamp(8) | x(4) | y(4)`
- Server -> client WORLD snapshot: `type(1) | seq(4) | timestamp(8) | count(1)` + `count` x `player_id(1) | x(4) | y(4)`
- Types: 1 REGISTER, 2 REGISTER_ACK, 3 STATE, 4 PING, 5 PONG, 6 WORLD

## Quick start

### A) Test the game on one laptop (no Mininet needed) - Leads 1, 2, 5
```bash
python3 -m unittest discover -s tests -v            # automated tests, should say OK
mkdir -p results/local
python3 server/server.py --port 5005 --log results/local/server_log.csv --duration 20 &
python3 client/client.py --name p1 --duration 10 --logdir results/local &
python3 client/client.py --name p2 --duration 10 --logdir results/local &
sleep 12; python3 metrics/analyze.py results/local
```

### B) Full experiment (Linux or WSL2 / Ubuntu VM, needs sudo) - Leads 3, 4
```bash
sudo apt update && sudo apt install -y mininet openvswitch-switch python3-pip
sudo service openvswitch-switch start
pip3 install matplotlib
# Ryu needs a venv with pinned packages on Python 3.10 - follow docs/LEAD3_SDN.md Step 0:
#   python3 -m venv ~/ryuenv && source ~/ryuenv/bin/activate
#   pip install "setuptools<66" wheel && pip install eventlet==0.33.3 dnspython==2.2.1 ryu   (+ one-line wsgi.py patch)
sudo bash experiments/run_all.sh                   # ~5 minutes, makes results/*.png
```
If Ryu will not install: `sudo bash experiments/run_all.sh none` uses static OVS rules instead (same queues, no controller).

## PROJECT CONTEXT - paste this at the start of every LLM chat

```
I am working on a university Computer Networks project: "Multiplayer Game Communication Network".
Players (Mininet hosts) send game-state updates to a game server using UDP sockets in Python.
Requirements: UDP game-state updates, register multiple players, sequence numbers, handle packet loss,
SDN traffic prioritization (game traffic must get priority over background traffic), measure latency,
measure jitter, test under congestion.
Tech: Python 3, Mininet, Open vSwitch (OpenFlow 1.3, HTB queues), Ryu controller, Ubuntu.
Topology: players p1,p2,p3 and noise host n1 on switch s1; server srv and noise host n2 on switch s2;
s1-s2 is a 10 Mbps bottleneck. Game UDP port = 5005, noise UDP port = 6000.
Packet format (big-endian): client->server 22 bytes "!BBIdff" = type, player_id, seq, timestamp, x, y.
Server->client WORLD snapshot: header "!BIdB" = type, seq, timestamp, count then count x "!Bff" = player_id, x, y.
Message types: 1 REGISTER, 2 REGISTER_ACK, 3 STATE, 4 PING, 5 PONG, 6 WORLD.
Log files are CSV: server_log.csv (player_id,seq,send_ts,recv_ts), client_<name>_log.csv (seq,send_ts,recv_ts),
client_<name>_rtt.csv (time,rtt_ms).
Repo layout: common/ server/ client/ sdn/ tools/ metrics/ experiments/ tests/ docs/
I am a student and a beginner at networking. Explain simply, give complete copy-paste commands and code,
and tell me how to verify each step worked.
```

## The 4 experiment scenarios

| Scenario | Noise | Priority | Extra | What it shows |
|---|---|---|---|---|
| `baseline` | no | off | - | the best case |
| `congested_noprio` | 2 x 15 Mbps | off | - | what congestion does to the game |
| `congested_prio` | 2 x 15 Mbps | **on** | - | SDN priority fixes it (the key result) |
| `loss5` | no | off | 5% random loss | proves loss handling works |

## Team rules

1. Do not change the packet format (`common/packet.py`) without telling everybody.
2. Work on your own git branch, merge to `main` only at checkpoints, and only code that runs.
3. Stuck for more than 30 minutes? Say so in the group chat immediately.
4. Everybody must be able to explain their own part in the viva (each guide has practice questions).
