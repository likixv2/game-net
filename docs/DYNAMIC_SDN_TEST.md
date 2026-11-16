# Lead 3: test the dynamic controller on the VM

The dynamic SDN controller (`sdn/controller.py`, `sdn/policy.py`) and the three burst scenarios were written and
unit tested away from the VM. They have **not yet run in Mininet**. Your job: run them, fix anything that needs
adjusting, and send back the results. Budget about 45 minutes.

## 1. Update and check the environment
```bash
cd game-net && git checkout main && git pull origin main
source ~/ryuenv/bin/activate
python3 -m unittest discover -s tests -v          # all 26 tests must run (none skipped) and end with OK
```
If 8 tests are skipped, Ryu is not importable in the venv; fix that first.

## 2. Check the bottleneck port numbers
The controller assumes s1 = datapath 1 with the bottleneck on port 5, and s2 = datapath 2 with it on port 3.
```bash
sudo python3 sdn/topology.py --controller none       # leave it running; use a second terminal
sudo ovs-ofctl -O OpenFlow13 show s1 | grep "s1-eth"
sudo ovs-ofctl -O OpenFlow13 show s2 | grep "s2-eth"
```
`s1-eth5` and `s2-eth3` must be the s1–s2 link. If not, start Ryu with `BOTTLENECK="1:<port>,2:<port>"`
(and tell Lead 5). Exit Mininet (`exit`, then `sudo mn -c`).

## 3. Quick manual check of the dynamic behaviour
Terminal 1: `PRIORITY=dynamic CTRL_LOG=/tmp/ctrl.csv ryu-manager sdn/controller.py`
Terminal 2: `sudo python3 sdn/topology.py --controller ryu`, then at `mininet>`:
```
srv python3 server/server.py --duration 80 --log /tmp/s.csv --control-sock /tmp/gamenet_ctrl.sock &
n1 python3 tools/noise.py sink --port 6000 &
n2 python3 tools/noise.py sink --port 6000 &
p1 python3 client/client.py --server-ip 10.0.0.10 --name p1 --duration 60 --logdir /tmp &
p2 python3 client/client.py --server-ip 10.0.0.10 --name p2 --duration 60 --logdir /tmp &
```
Terminal 3 (each check):
```bash
tail -5 /tmp/ctrl.csv                                           # expect player_register for 10.0.0.1 and 10.0.0.2
sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep 5005         # expect NOTHING yet
```
Start noise at the `mininet>` prompt:
```
n1 python3 tools/noise.py send --ip 10.0.0.5 --port 6000 --mbps 15 --duration 25 &
n2 python3 tools/noise.py send --ip 10.0.0.4 --port 6000 --mbps 15 --duration 25 &
```
After about 5 s: `tail /tmp/ctrl.csv` must show `rate_mbps` near 10, `congestion_detected`, `priority_on`;
`dump-flows s1 | grep 5005` must show priority=10 rules with `nw_src`/`nw_dst` and `set_queue:1`.
About 8 s after the noise ends: `priority_off` is logged and the rules are gone.

## 4. If something does not work
| Symptom | Likely cause and fix |
|---|---|
| `rate_mbps` stays near 0 during the noise | wrong bottleneck port numbers (step 2) |
| `rate_mbps` high but no `congestion_detected` | `tx_bytes` counts less than expected; lower the threshold: edit `high=0.8` to `0.6` in `CongestionDetector(...)` in `sdn/controller.py` |
| No `player_register` | server started without `--control-sock /tmp/gamenet_ctrl.sock`, or Ryu not running yet |
| `priority_on` logged but no rules in `dump-flows` | read `ryu.log`; the match may be rejected by OVS (send us the error text) |
| Rules appear but latency stays high | check `queue-stats s1`: game packets must increase in queue 1 |

## 5. Run the real experiments and send results
```bash
sudo env "PATH=$PATH" bash experiments/run_all.sh
```
Send to Lead 5: the whole `results/` folder as a tar.gz (`tar czf results.tar.gz results`), especially
`results/burst_table.md`, `results/dynamic_timeline.png`, `results/results_table.md`,
`results/loss5/tc_loss_setup.txt`, `results/burst_dynamic/controller_events.csv`,
`results/burst_dynamic/flows_during_burst.txt`, `results/burst_dynamic/flows_after_burst.txt`.
Also tell Lead 5 anything you had to change.
