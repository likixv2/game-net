"""
controller.py - the SDN brain (Lead 3). A Ryu OpenFlow 1.3 app.

It is a normal "learning switch" plus game-traffic prioritisation. Three modes (environment variable PRIORITY):

  PRIORITY=off      plain forwarding, everything shares queue 0                        (baseline)
  PRIORITY=on       STATIC: priority rules for UDP port 5005 are always installed      (static approach)
  PRIORITY=dynamic  DYNAMIC (default for the final project): the controller reacts to
                      1. APPLICATION events - the game server tells the controller which players are
                         registered (REGISTER / LEAVE on a control socket). Only registered players'
                         game packets are eligible for the priority queue.
                      2. NETWORK conditions - the controller polls the byte counters of the bottleneck
                         port every second. When utilisation stays >= 80 % it installs the priority
                         rules; when it stays < 50 % it removes them again.

Flow rules (OpenFlow 1.3):
    priority 0  : table miss -> controller
    priority 1  : L2 forwarding for a (in_port, src MAC, dst MAC) learned by the controller
    priority 10 : UDP src/dst port 5005 -> set_queue:1 -> output     (cookie 0x5005, so it can be removed)
                  in dynamic mode the rule also matches the registered player's IP

The queues are created by sdn/topology.py (OVS HTB on the bottleneck link):
    queue 1 = game (min 8 Mbps, higher priority), queue 0 = everything else.

Environment variables
    PRIORITY      on | off | dynamic                      (default on)
    CTRL_SOCK     Unix datagram socket the game server writes to   (default /tmp/gamenet_ctrl.sock)
    CTRL_LOG      CSV file for controller events (time,event,detail) (default: no file)
    BOTTLENECK    "dpid:port,dpid:port" bottleneck ports            (default "1:5,2:3" = s1-eth5, s2-eth3)
    POLL_SECONDS  statistics polling interval                       (default 1.0)

Run:   PRIORITY=dynamic ryu-manager sdn/controller.py          (OpenFlow port 6653)
"""
import csv
import os
import socket
import sys
import time

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.lib.packet import ethernet, ether_types, packet
from ryu.ofproto import ofproto_v1_3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from policy import CongestionDetector, PlayerRegistry, parse_control, rate_bps  # noqa: E402

GAME_PORT = 5005
GAME_QUEUE = 1
DEFAULT_QUEUE = 0
PRIO_COOKIE = 0x5005
COOKIE_MASK = 0xFFFFFFFFFFFFFFFF
BOTTLENECK_BPS = 10e6


class GamePriorityController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(GamePriorityController, self).__init__(*args, **kwargs)
        mode = os.environ.get("PRIORITY", "on").lower()
        self.mode = "dynamic" if mode == "dynamic" else ("on" if mode in ("on", "1", "true", "yes") else "off")
        self.prio_active = (self.mode == "on")      # are priority rules installed right now?

        self.datapaths = {}         # dpid -> datapath
        self.mac_to_port = {}       # dpid -> {mac: port}
        self.known_flows = {}       # (dpid, in_port, src, dst) -> out_port   (so rules can be (re)installed)

        self.registry = PlayerRegistry()
        self.detector = CongestionDetector(capacity_bps=BOTTLENECK_BPS)

        self.bottleneck = {}        # dpid -> port number of the s1<->s2 link
        for item in os.environ.get("BOTTLENECK", "1:5,2:3").split(","):
            dpid, port = item.split(":")
            self.bottleneck[int(dpid)] = int(port)
        self.interval = float(os.environ.get("POLL_SECONDS", "1.0"))
        self.last_bytes = {}        # dpid -> (tx_bytes, time)
        self.rates = {}             # dpid -> latest bit rate on the bottleneck port

        self.log_file = None
        self.log_writer = None
        path = os.environ.get("CTRL_LOG")
        if path:
            self.log_file = open(path, "w", newline="")
            self.log_writer = csv.writer(self.log_file)
            self.log_writer.writerow(["time", "event", "detail"])

        self.logger.info("=== mode: %s ===", self.mode.upper())
        self._log("mode", self.mode)
        self.ctrl_path = os.environ.get("CTRL_SOCK", "/tmp/gamenet_ctrl.sock")
        hub.spawn(self._control_loop)
        hub.spawn(self._monitor_loop)

    # ------------------------------------------------------------------ logging
    def _log(self, event, detail=""):
        self.logger.info("%s %s", event, detail)
        if self.log_writer:
            self.log_writer.writerow(["%.3f" % time.time(), event, detail])
            self.log_file.flush()

    # ------------------------------------------------------------------ flow helpers
    def add_flow(self, dp, priority, match, actions, idle_timeout=0, cookie=0):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority, match=match, instructions=inst,
                                      idle_timeout=idle_timeout, cookie=cookie))

    def prio_matches(self, parser, in_port, src, dst):
        """Matches of the priority rules for one learned flow.
        static mode : any UDP packet with src or dst port 5005
        dynamic mode: only packets of registered players (match on their IP)."""
        base = dict(in_port=in_port, eth_src=src, eth_dst=dst, eth_type=0x0800, ip_proto=17)
        if self.mode == "on":
            return [parser.OFPMatch(udp_dst=GAME_PORT, **base), parser.OFPMatch(udp_src=GAME_PORT, **base)]
        matches = []
        for ip in self.registry.ips():
            matches.append(parser.OFPMatch(ipv4_src=ip, udp_dst=GAME_PORT, **base))   # player -> server
            matches.append(parser.OFPMatch(ipv4_dst=ip, udp_src=GAME_PORT, **base))   # server -> player
        return matches

    def install_prio_for_flow(self, dp, in_port, src, dst, out_port):
        parser = dp.ofproto_parser
        actions = [parser.OFPActionSetQueue(GAME_QUEUE), parser.OFPActionOutput(out_port)]
        for match in self.prio_matches(parser, in_port, src, dst):
            self.add_flow(dp, 10, match, actions, idle_timeout=60 if self.mode == "on" else 0, cookie=PRIO_COOKIE)

    def remove_all_prio(self):
        for dp in self.datapaths.values():
            ofp, parser = dp.ofproto, dp.ofproto_parser
            dp.send_msg(parser.OFPFlowMod(datapath=dp, command=ofp.OFPFC_DELETE, out_port=ofp.OFPP_ANY,
                                          out_group=ofp.OFPG_ANY, cookie=PRIO_COOKIE, cookie_mask=COOKIE_MASK,
                                          match=parser.OFPMatch()))

    def apply_prio(self):
        """(Re)install priority rules for every flow the controller knows about."""
        self.remove_all_prio()
        if not self.prio_active:
            return
        for (dpid, in_port, src, dst), out_port in list(self.known_flows.items()):
            dp = self.datapaths.get(dpid)
            if dp is not None:
                self.install_prio_for_flow(dp, in_port, src, dst, out_port)

    def set_priority(self, active, reason):
        if active == self.prio_active:
            return
        self.prio_active = active
        self._log("priority_on" if active else "priority_off", reason)
        self.apply_prio()

    # ------------------------------------------------------------------ switch events
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        self.datapaths[dp.id] = dp
        self.add_flow(dp, 0, parser.OFPMatch(), [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)])
        self._log("switch_connected", "s%s" % dp.id)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        dst, src = eth.dst, eth.src

        table = self.mac_to_port.setdefault(dp.id, {})
        table[src] = in_port
        out_port = table.get(dst, ofp.OFPP_FLOOD)

        if out_port != ofp.OFPP_FLOOD:
            self.known_flows[(dp.id, in_port, src, dst)] = out_port
            # priority 1: normal forwarding (queue 0)
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self.add_flow(dp, 1, match, [parser.OFPActionSetQueue(DEFAULT_QUEUE), parser.OFPActionOutput(out_port)],
                          idle_timeout=60)
            # priority 10: game rules, when prioritisation is active right now
            if self.prio_active:
                self.install_prio_for_flow(dp, in_port, src, dst, out_port)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
                                        actions=[parser.OFPActionOutput(out_port)], data=data))

    # ------------------------------------------------------------------ application events (from the game server)
    def _control_loop(self):
        """Receives REGISTER / LEAVE messages from the game server on a Unix datagram socket."""
        try:
            if os.path.exists(self.ctrl_path):
                os.unlink(self.ctrl_path)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.bind(self.ctrl_path)
            os.chmod(self.ctrl_path, 0o777)
            sock.setblocking(False)
        except OSError as e:
            self.logger.error("control socket %s unavailable: %s", self.ctrl_path, e)
            return
        self.logger.info("listening for game-server events on %s", self.ctrl_path)
        while True:
            try:
                data = sock.recv(512)
            except (BlockingIOError, InterruptedError):
                hub.sleep(0.05)
                continue
            except OSError:
                hub.sleep(0.5)
                continue
            self.handle_control(data)

    def handle_control(self, data):
        parsed = parse_control(data)
        if parsed is None:
            self._log("bad_control_message", repr(data[:40]))
            return
        cmd, ip, pid = parsed
        if cmd == "REGISTER":
            if self.registry.add(ip, pid):
                self._log("player_register", "%s id=%d" % (ip, pid))
                if self.mode == "dynamic" and self.prio_active:
                    self.apply_prio()             # give the new player priority immediately
        else:
            if self.registry.remove(ip):
                self._log("player_leave", "%s id=%d" % (ip, pid))
                if self.mode == "dynamic" and self.prio_active:
                    self.apply_prio()

    # ------------------------------------------------------------------ network conditions (statistics polling)
    def _monitor_loop(self):
        while True:
            hub.sleep(self.interval)
            for dpid, dp in list(self.datapaths.items()):
                port = self.bottleneck.get(dpid)
                if port is not None:
                    dp.send_msg(dp.ofproto_parser.OFPPortStatsRequest(dp, 0, port))
            hub.sleep(0.2)                         # let the replies arrive
            self.evaluate()

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_handler(self, ev):
        dpid = ev.msg.datapath.id
        for st in ev.msg.body:
            if st.port_no != self.bottleneck.get(dpid):
                continue
            now = time.time()
            prev = self.last_bytes.get(dpid)
            if prev is not None:
                self.rates[dpid] = rate_bps(prev[0], st.tx_bytes, now - prev[1])
            self.last_bytes[dpid] = (st.tx_bytes, now)

    def evaluate(self):
        """Called once per polling interval with the freshest rates."""
        if not self.rates:
            return
        rate = max(self.rates.values())                       # busiest direction of the bottleneck
        self._log("rate_mbps", "%.2f" % (rate / 1e6))
        if self.mode != "dynamic":
            return
        change = self.detector.update(rate)
        if change == "on":
            self._log("congestion_detected", "%.2f Mbps" % (rate / 1e6))
            self.set_priority(True, "congestion")
        elif change == "off":
            self._log("congestion_cleared", "%.2f Mbps" % (rate / 1e6))
            self.set_priority(False, "link idle")
