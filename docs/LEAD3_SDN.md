# Lead 3 - SDN & Network (the hardest role - start first)

**Your files:** `sdn/topology.py`, `sdn/controller.py`
**Your mission:** build the emulated network (Mininet), make the middle link a real 10 Mbps bottleneck with two queues,
and make an SDN controller (Ryu) put game traffic (UDP port 5005) in the high-priority queue.

> Honest note: the UDP game code was tested on a laptop. The Mininet/Ryu parts need Linux with Mininet and Open vSwitch,
> so they must be tested on **your** Ubuntu VM. If something fails, the "Common errors" table and the fallback below
> cover the usual causes. Tell Lead 5 early if you have to use the fallback.

## Words you must know
- **Mininet**: creates virtual hosts and switches inside one Linux machine.
- **Open vSwitch (OVS)**: a software switch. Understands OpenFlow.
- **SDN**: the switch does not decide by itself; a **controller** (Ryu) tells it what to do with flow rules.
- **Flow rule**: "if packet matches X then do Y". Higher priority number wins.
- **Queue / HTB**: a switch port can have several queues with different guaranteed rates. A rule can say "put this packet in queue 1".

---

## Step 0 - Setup (30-45 min; do this FIRST, it is where people lose time)
Use **Ubuntu 20.04 / 22.04** (VM or WSL2). On macOS/Windows use a VM (VirtualBox/UTM).
```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3-pip iperf
sudo service openvswitch-switch start
sudo ovs-vsctl show                      # must print something, not an error
pip3 install matplotlib
sudo mn --test pingall                   # Mininet works if it says 0% dropped
```
Install Ryu in a **virtual environment**. This recipe was tested on Ubuntu 22.04.5 with Python 3.10.12 (Ryu 4.34, Open vSwitch 2.17.12):
```bash
python3 -m venv ~/ryuenv && source ~/ryuenv/bin/activate
pip install "setuptools<66" wheel
pip install eventlet==0.33.3 dnspython==2.2.1 ryu
# Ryu's REST helper imports ALREADY_HANDLED, which newer eventlet removed. Patch that one line:
sed -i 's/from eventlet.wsgi import ALREADY_HANDLED/ALREADY_HANDLED = b""/' \
  ~/ryuenv/lib/python3.10/site-packages/ryu/app/wsgi.py
ryu-manager --version                    # must print: ryu-manager 4.34
```
Why these versions (Python 3.10): `eventlet==0.30.2` crashes with `cannot set 'is_timeout' attribute of immutable type 'TimeoutError'`;
an old `dnspython` crashes with `module 'collections' has no attribute 'MutableMapping'`; and newer eventlet has no `ALREADY_HANDLED`, hence the patch
(our controller does not use Ryu's REST helper, so this is safe). On Python 3.8/3.9 the older pin `eventlet==0.30.2` also works.
`ryu-manager` only exists inside the venv: run `source ~/ryuenv/bin/activate` in every terminal that starts the controller
(or call `~/ryuenv/bin/ryu-manager`). If nothing works, use the **fallback** below.

## Step 1 - Start the network with the controller (10 min)
Terminal 1 (project root):
```bash
PRIORITY=on ryu-manager sdn/controller.py
```
Terminal 2 (project root):
```bash
sudo mn -c                                  # clean old runs
sudo python3 sdn/topology.py --controller ryu
mininet> pingall                            # expect 0% dropped
```
Terminal 1 should print `switch 1 connected`, `switch 2 connected`, and `game traffic prioritisation is ON`.

## Step 2 - Check the queues exist (10 min)
In a third terminal:
```bash
sudo ovs-vsctl list-ports s1                # shows s1-eth1 ... s1-eth5 ; the LAST one (s1-eth5) goes to s2
sudo ovs-vsctl list qos
sudo ovs-vsctl list queue                   # you should see queue 0 (min 1M) and queue 1 (min 8M)
sudo tc -s class show dev s1-eth5           # the HTB classes
```

## Step 3 - See prioritisation working by hand (20 min)
In the Mininet prompt (`mininet>`), from the project root:
```
mininet> srv python3 server/server.py --duration 100 --log /tmp/server_log.csv &
mininet> n2 python3 tools/noise.py sink --port 6000 &
mininet> n1 python3 tools/noise.py send --ip 10.0.0.5 --port 6000 --mbps 15 --duration 40 &
mininet> p1 python3 client/client.py --server-ip 10.0.0.10 --name p1 --duration 20 --logdir /tmp
```
Then in the other terminal: `sudo ovs-ofctl -O OpenFlow13 dump-flows s1`. You should see a rule with `udp_dst=5005` ... `set_queue:1`, and
`n_packets` going up. Check the queues: `sudo tc -s class show dev s1-eth5` - bytes should appear in BOTH classes
(game in the guaranteed one, noise in the other).

**Tip:** write each run into its own folder (`mkdir -p /tmp/on`, then `--log /tmp/on/server_log.csv` and `--logdir /tmp/on`), then
`sudo cp /tmp/on/* results/prio_on/ && sudo chown -R $USER results && python3 metrics/analyze.py results/prio_on`.

**Proof it matters**: restart everything with `PRIORITY=off`, repeat Step 3, and compare the client's `lost=` and the latency
(`python3 metrics/analyze.py /tmp` after copying the logs). With priority OFF the game suffers badly; with ON it stays almost unaffected.
Show this to Lead 4 - it is the main result of the project.

## Step 4 - Understand the code (30 min)

### `topology.py`
- Hosts: `p1 p2 p3` (players) and `n1` on switch `s1`; `srv` and `n2` on `s2`; `s1`-`s2` is the bottleneck.
- `net.staticArp()` fills ARP tables so there is no ARP flooding to confuse the controller.
- `setup_qos()` runs `ovs-vsctl` to create one **QoS** (type `linux-htb`, max 10 Mbps) with two **queues** on both ends of the s1-s2 link:
  queue 0 = best effort (min 1 Mbps), queue 1 = game (min 8 Mbps, higher HTB priority).
- The bottleneck link is deliberately created without Mininet's own bandwidth option, because OVS QoS and Mininet's `tc` shaping would clash.

### `controller.py`
- On a new switch it installs the *table-miss* rule: "unknown packet -> send to controller".
- `packet_in_handler` learns `source MAC -> port`. If it knows the destination port it installs flow rules:
  - priority 1: everything for that destination, using queue 0
  - priority 10 (only if `PRIORITY=on`): UDP with `udp_dst=5005` or `udp_src=5005`, using **queue 1**
- `udp_src=5005` matters too: it covers the server's replies back to the players.

## Fallback (no Ryu)
```bash
sudo python3 sdn/topology.py --controller none --priority on
```
Uses plain OVS rules (`set_queue:1,normal`) instead of the controller. The queues and the behaviour are identical, but explain
honestly in the report that this is the "static flow rules" version of SDN. Use `--priority off` for the no-priority runs. The experiment runner accepts it: `sudo bash experiments/run_all.sh none`
(note: in `none` mode the priority switch comes from the scenario automatically).

## Measured result (our VM, 15 Mbps noise, one client, 20 s)
| | priority OFF | priority ON |
|---|---|---|
| uplink latency mean / p95 | 71.2 / 91.8 ms | 2.3 / 2.6 ms |
| uplink jitter | 4.73 ms | 0.09 ms |
| loss | 0 % | 0 % |
Use this as a sanity check: if your OFF and ON runs look the same, the priority rule or the noise is not working.

## You are DONE when
- [ ] `pingall` shows 0% dropped
- [ ] `ovs-vsctl list queue` shows two queues
- [ ] `dump-flows s1` shows the `udp_dst=5005 ... set_queue:1` rule when `PRIORITY=on`, and no such rule when `off`
- [ ] with 15 Mbps noise, game packet loss is clearly lower / latency clearly lower with priority ON than OFF
- [ ] you can draw the topology and explain the rules on a whiteboard

---

## LLM prompt pack (paste PROJECT CONTEXT from README.md first)

**P1 - Explain SDN to me**
> Explain SDN, OpenFlow, flow rules, and the role of a controller to a beginner, using my project as the example (game traffic on UDP 5005
> must get priority over noise on UDP 6000). Draw a simple text diagram of what happens when the first packet of a new flow reaches the switch.

**P2 - Explain my controller**
> Here is my Ryu controller: ```<paste sdn/controller.py>```. Explain it line by line. Specifically: what is the table-miss rule, what does
> `set_queue` do, why are there two game rules (udp_dst and udp_src), and why does the game rule have priority 10 and the normal rule priority 1?

**P3 - Explain the QoS commands**
> Explain this `ovs-vsctl` command piece by piece (qos, queue, linux-htb, min-rate, max-rate, priority): ```<paste the command from setup_qos in topology.py>```.
> How do I verify with `tc` and `ovs-ofctl` that packets really go into queue 1?

**P4 - Fix install problems**
> I am on <Ubuntu version / WSL2 / VM> with Python <version>. When I run <command> I get this error: ```<paste full error>```.
> Give me exact commands to fix it. Prefer solutions that keep Mininet and Ryu working; suggest a virtualenv if Python is too new for Ryu.

**P5 - It does not prioritise**
> My game traffic is NOT getting priority. Output of `sudo ovs-ofctl -O OpenFlow13 dump-flows s1`: ```<paste>```.
> Output of `sudo tc -s class show dev s1-eth5`: ```<paste>```. Output of `sudo ovs-vsctl list queue`: ```<paste>```. My controller: ```<paste>```.
> Tell me what is wrong and what to change.

**P6 - Viva practice**
> Be my examiner on the SDN part of my Computer Networks project. Ask one question at a time: control plane vs data plane, what a flow rule is,
> how my controller identifies game traffic, what a queue is, why I need a bottleneck for priority to matter. Give feedback after each answer.

---

## Common errors
| Problem | Fix |
|---|---|
| `Exception: Error creating interface pair` / leftovers | `sudo mn -c` then retry |
| `pingall` shows 100% dropped | Ryu not running (Terminal 1) or wrong port; Ryu listens on 6653, topology uses 6653. Check Terminal 1 printed `switch ... connected` |
| Ryu crash `cannot import name 'ALREADY_HANDLED'` | apply the one-line `wsgi.py` patch in Step 0 (do not downgrade eventlet on Python 3.10) |
| Ryu crash `cannot set 'is_timeout' attribute of immutable type 'TimeoutError'` | eventlet too old for Python 3.10: `pip install eventlet==0.33.3` |
| Ryu crash `module 'collections' has no attribute 'MutableMapping'` | `pip install dnspython==2.2.1` |
| `ryu-manager: command not found` | the venv is not active: `source ~/ryuenv/bin/activate` |
| `pingall` shows all `X`, nothing is listening on port 6653 (check with `ss -ltnp`) | the controller is not running; start Ryu first, then the topology |
| client prints `no ACK, retry` / `could not register` | the network is not forwarding yet: wait for `pingall` to show 0% dropped before starting the server and client |
| `rm: cannot remove ... Operation not permitted` in `/tmp` | Mininet runs as root, so its files are root-owned. Use a new log folder per run (`mkdir -p /tmp/on`, `--log /tmp/on/server_log.csv`, `--logdir /tmp/on`) instead of deleting |
| `analyze.py` shows `n/a` for downlink / RTT | the client logs are named `client_<IP>_log.csv` / `client_<IP>_rtt.csv` (for example `client_10.0.0.1_log.csv`), not `client_p1_*`; copy `/tmp/on/*` as a whole |
| `ovs-vsctl: unix:/var/run/openvswitch/db.sock: database connection failed` | `sudo service openvswitch-switch start` |
| `dump-flows` shows nothing | use `-O OpenFlow13`; and send some traffic first (flows are installed on demand) |
| queue stats all in one class | rule not matched: verify the game UDP port really is 5005 (`--server-port`) and that `PRIORITY=on` was set in the SAME terminal as ryu-manager |
| nothing works after 30 min | use the fallback (`--controller none`) and tell Lead 5 |

## Viva questions (practice answers)
1. **What is SDN?** Separation of the control plane (the controller that decides) from the data plane (switches that forward). The controller programs switches with flow rules via OpenFlow.
2. **How does your controller prioritise game traffic?** It matches UDP packets with port 5005 and uses the `set_queue` action so they leave through the guaranteed, higher-priority HTB queue; everything else uses the best-effort queue.
3. **Why do you need a bottleneck?** Priority only matters when a link is congested. With spare capacity nothing queues, so there is nothing to prioritise.
4. **Why match both src and dst port?** Players send to port 5005; the server's replies come *from* port 5005.
5. **What happens to the first packet of a flow?** No rule matches, so the switch sends it to the controller (packet-in); the controller learns the MAC, installs rules, and forwards the packet (packet-out).
6. **What are the limits of your design?** It is static classification by port, not per-flow bandwidth estimation; the queues are only on the bottleneck link; one controller (single point of failure).
