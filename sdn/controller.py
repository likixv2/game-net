"""
controller.py - the SDN brain (Lead 3). A Ryu OpenFlow 1.3 app.

It is a normal "learning switch" (learns which MAC lives behind which port) with ONE extra trick:

  PRIORITY=on  -> for every destination it learns, it installs TWO flow rules:
        high priority (10): "UDP packet with src or dst port 5005" -> use QUEUE 1 (game queue)
        low  priority (1) : "everything else"                      -> use QUEUE 0 (best effort)
  PRIORITY=off -> only the plain forwarding rule (no queue selection; everything shares queue 0)

The queues themselves are created by sdn/topology.py (Open vSwitch HTB QoS on the bottleneck link).
Queue 1 has a guaranteed bandwidth and higher HTB priority, queue 0 is the leftover.

Run:   PRIORITY=on  ryu-manager sdn/controller.py          (default port 6653)
       PRIORITY=off ryu-manager sdn/controller.py
"""
import os

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib.packet import ethernet, ether_types, packet
from ryu.ofproto import ofproto_v1_3

GAME_PORT = 5005
GAME_QUEUE = 1
DEFAULT_QUEUE = 0


class GamePriorityController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(GamePriorityController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}   # dpid -> {mac: port}
        self.priority_on = os.environ.get("PRIORITY", "on").lower() in ("on", "1", "true", "yes")
        self.logger.info("=== game traffic prioritisation is %s ===", "ON" if self.priority_on else "OFF")

    # ---------- helper ----------
    def add_flow(self, dp, priority, match, actions, idle_timeout=0):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                      instructions=inst, idle_timeout=idle_timeout))

    # ---------- switch connects: install the table-miss rule ----------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, match, actions)     # unknown packet -> ask the controller
        self.logger.info("switch %s connected", dp.id)

    # ---------- packet the switch did not know what to do with ----------
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
        table[src] = in_port                      # learn where the sender is

        out_port = table.get(dst, ofp.OFPP_FLOOD)  # known -> that port, unknown -> flood

        if out_port != ofp.OFPP_FLOOD:
            # 1) normal rule for all traffic to this destination (priority 1)
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self.add_flow(dp, 1, match,
                          [parser.OFPActionSetQueue(DEFAULT_QUEUE), parser.OFPActionOutput(out_port)]
                          if self.priority_on else [parser.OFPActionOutput(out_port)],
                          idle_timeout=60)

            # 2) game rules (priority 10) - only when prioritisation is enabled
            if self.priority_on:
                for field in ("udp_dst", "udp_src"):
                    match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src,
                                            eth_type=0x0800, ip_proto=17, **{field: GAME_PORT})
                    self.add_flow(dp, 10, match,
                                  [parser.OFPActionSetQueue(GAME_QUEUE), parser.OFPActionOutput(out_port)],
                                  idle_timeout=60)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
                                        actions=[parser.OFPActionOutput(out_port)], data=data))
