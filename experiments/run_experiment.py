#!/usr/bin/env python3
"""
run_experiment.py - runs ONE scenario end to end (Lead 4). Needs sudo, Mininet, Open vSwitch, Ryu.

    sudo python3 experiments/run_experiment.py --scenario baseline
    sudo python3 experiments/run_experiment.py --scenario congested_noprio
    sudo python3 experiments/run_experiment.py --scenario congested_prio
    sudo python3 experiments/run_experiment.py --scenario loss5

What it does: starts Ryu (priority on/off) -> builds the network -> starts server, 3 clients and
(for congestion scenarios) noise in both directions -> waits -> stops everything -> runs analyze.py.
Logs end up in results/<scenario>/.

Use --controller none to skip Ryu and use static OVS rules instead (fallback if Ryu will not install).
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "sdn"))
sys.path.insert(0, ROOT)

from mininet.log import setLogLevel  # noqa: E402
from topology import build_net       # noqa: E402

SCENARIOS = {
    #                  priority, noise, random loss %
    "baseline":         ("off", False, 0),
    "congested_noprio": ("off", True, 0),
    "congested_prio":   ("on",  True, 0),
    "loss5":            ("off", False, 5),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=list(SCENARIOS), required=True)
    ap.add_argument("--duration", type=int, default=40, help="seconds the clients play")
    ap.add_argument("--controller", choices=["ryu", "none"], default="ryu")
    ap.add_argument("--noise-mbps", type=float, default=15)
    args = ap.parse_args()

    prio, noise, loss = SCENARIOS[args.scenario]
    out = os.path.join(ROOT, "results", args.scenario)
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):                 # clean old logs of this scenario
        os.remove(os.path.join(out, f))

    setLogLevel("warning")
    subprocess.run("mn -c > /dev/null 2>&1", shell=True)   # clean leftovers of old runs

    ryu = None
    if args.controller == "ryu":
        env = dict(os.environ, PRIORITY=prio)
        ryu = subprocess.Popen(["ryu-manager", os.path.join(ROOT, "sdn", "controller.py")], env=env,
                               stdout=open(os.path.join(out, "ryu.log"), "w"), stderr=subprocess.STDOUT)
        time.sleep(3)                         # let it start listening

    net = build_net(args.controller, prio)
    procs = []
    try:
        time.sleep(3)                         # let switches connect to the controller
        p1, p2, p3 = net.get("p1", "p2", "p3")
        n1, n2, srv = net.get("n1", "n2", "srv")
        srv_ip = srv.IP()
        players = [p1, p2, p3]

        print("[exp] connectivity check:")
        print(net.pingAll())

        if loss:                              # random loss on every player and on the server
            for h in players + [srv]:
                h.cmd("tc qdisc add dev %s-eth0 root netem loss %d%%" % (h.name, loss))

        total = args.duration + 8
        procs.append(srv.popen("python3 %s/server/server.py --ip 0.0.0.0 --port 5005 --log %s/server_log.csv --duration %d"
                               % (ROOT, out, total),
                               stdout=open(out + "/server.out", "w"), stderr=subprocess.STDOUT))
        time.sleep(1)

        if noise:                             # sinks first, then floods in BOTH directions
            procs.append(n2.popen("python3 %s/tools/noise.py sink --port 6000" % ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            procs.append(n1.popen("python3 %s/tools/noise.py sink --port 6000" % ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            time.sleep(1)
            procs.append(n1.popen("python3 %s/tools/noise.py send --ip %s --port 6000 --mbps %s --duration %d"
                                  % (ROOT, n2.IP(), args.noise_mbps, args.duration + 4), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            procs.append(n2.popen("python3 %s/tools/noise.py send --ip %s --port 6000 --mbps %s --duration %d"
                                  % (ROOT, n1.IP(), args.noise_mbps, args.duration + 4), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            time.sleep(2)                     # let the queues fill up before the game starts

        clients = []
        for h in players:
            clients.append(h.popen("python3 %s/client/client.py --server-ip %s --name %s --duration %d --logdir %s"
                                   % (ROOT, srv_ip, h.name, args.duration, out),
                                   stdout=open("%s/%s.out" % (out, h.name), "w"), stderr=subprocess.STDOUT))
        print("[exp] playing for %d s ..." % args.duration)
        for c in clients:
            c.wait()
        time.sleep(3)

        # peek at the switch counters for the report (queue usage)
        with open(out + "/ovs_queue_stats.txt", "w") as f:
            f.write(subprocess.run("ovs-vsctl list queue; ovs-ofctl -O OpenFlow13 dump-flows s1; "
                                   "ovs-ofctl -O OpenFlow13 queue-stats s1", shell=True,
                                   capture_output=True, text=True).stdout)
    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        net.stop()
        if ryu:
            ryu.terminate()
        subprocess.run("mn -c > /dev/null 2>&1", shell=True)

    subprocess.run([sys.executable, os.path.join(ROOT, "metrics", "analyze.py"), out])


if __name__ == "__main__":
    if os.geteuid() != 0:
        sys.exit("run me with sudo")
    main()
