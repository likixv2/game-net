#!/usr/bin/env python3
r"""
topology.py - the emulated network (Lead 3). Must be run with sudo on Linux.

                        p1 \                                   / srv  (game server, 10.0.0.10)
                        p2 -- s1 ====== bottleneck 10 Mbps ====== s2
                        p3 /   |                                   \ n2   (noise host)
                              n1  (noise host)

  * s1, s2 are Open vSwitch switches controlled by the Ryu controller (sdn/controller.py)
  * the s1<->s2 link is the bottleneck. We limit it with OVS QoS (HTB) on BOTH ends and create
        queue 0 = best effort (everything), queue 1 = game traffic (guaranteed 8 of 10 Mbps, higher priority)
  * the controller decides who goes in queue 1 (only when PRIORITY=on)

Interactive use (to play around):
    sudo python3 sdn/topology.py --controller ryu       # start ryu-manager in another terminal first
    mininet> pingall
    mininet> srv python3 server/server.py &
Fallback with no Ryu at all (static OVS rules, same queues):
    sudo python3 sdn/topology.py --controller none --priority on
"""
import argparse
import subprocess
import time

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController

BOTTLENECK_BPS = 10000000     # 10 Mbps
GAME_MIN_BPS = 8000000        # game queue is guaranteed at least 8 Mbps
GAME_PORT = 5005


def sh(cmd):
    """Run a shell command, return its output (stripped)."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def build_net(controller="ryu", priority="on"):
    """Create and START the network. Returns the Mininet object.
    controller: 'ryu' (remote OpenFlow controller on 127.0.0.1:6653) or 'none' (static rules)."""
    use_ryu = controller == "ryu"
    if use_ryu:
        net = Mininet(switch=lambda name, **kw: OVSSwitch(name, protocols="OpenFlow13", **kw),
                      link=TCLink, controller=None, autoSetMacs=True)
        net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
    else:
        net = Mininet(switch=lambda name, **kw: OVSSwitch(name, failMode="standalone", **kw),
                      link=TCLink, controller=None, autoSetMacs=True)

    s1 = net.addSwitch("s1")
    s2 = net.addSwitch("s2")
    p1 = net.addHost("p1", ip="10.0.0.1/24")
    p2 = net.addHost("p2", ip="10.0.0.2/24")
    p3 = net.addHost("p3", ip="10.0.0.3/24")
    n1 = net.addHost("n1", ip="10.0.0.4/24")
    n2 = net.addHost("n2", ip="10.0.0.5/24")
    srv = net.addHost("srv", ip="10.0.0.10/24")

    for h in (p1, p2, p3, n1):
        net.addLink(h, s1)
    net.addLink(srv, s2, delay="2ms")      # a little realistic delay near the server
    net.addLink(n2, s2)
    net.addLink(s1, s2)                    # the bottleneck; NO tc params here, OVS QoS shapes it

    net.start()
    net.staticArp()                        # skip ARP so every packet is plain unicast
    setup_qos(net)
    if not use_ryu:
        install_static_rules(priority)
    return net


def setup_qos(net):
    """Create HTB queues on the s1<->s2 link, on both switches."""
    s1, s2 = net.get("s1"), net.get("s2")
    link = net.linksBetween(s1, s2)[0]
    ports = (link.intf1.name, link.intf2.name)
    for intf in ports:                              # start clean (old runs may have left QoS behind)
        sh("ovs-vsctl clear port %s qos" % intf)
    sh("ovs-vsctl --all destroy qos")
    sh("ovs-vsctl --all destroy queue")
    for intf in ports:
        cmd = (
            "ovs-vsctl set port {i} qos=@newqos -- "
            "--id=@newqos create qos type=linux-htb other-config:max-rate={mx} queues:0=@q0 queues:1=@q1 -- "
            "--id=@q0 create queue other-config:min-rate=1000000 other-config:max-rate={mx} other-config:priority=2 -- "
            "--id=@q1 create queue other-config:min-rate={gm} other-config:max-rate={mx} other-config:priority=1"
        ).format(i=intf, mx=BOTTLENECK_BPS, gm=GAME_MIN_BPS)
        out = sh(cmd)
        print("[qos] configured %s -> %s" % (intf, out.splitlines()[0] if out else "ok"))


def install_static_rules(priority):
    """Fallback (no controller): normal L2 switching + a rule that puts game UDP in queue 1."""
    for sw in ("s1", "s2"):
        sh("ovs-ofctl del-flows %s" % sw)
        sh("ovs-ofctl add-flow %s priority=0,actions=normal" % sw)
        if priority == "on":
            for field in ("tp_dst", "tp_src"):
                sh("ovs-ofctl add-flow %s priority=10,udp,%s=%d,actions=set_queue:1,normal"
                   % (sw, field, GAME_PORT))
    print("[sdn] static rules installed (priority=%s)" % priority)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--controller", choices=["ryu", "none"], default="ryu")
    ap.add_argument("--priority", choices=["on", "off"], default="on", help="only used with --controller none")
    args = ap.parse_args()
    setLogLevel("info")
    net = build_net(args.controller, args.priority)
    time.sleep(2)
    CLI(net)
    net.stop()


if __name__ == "__main__":
    main()
