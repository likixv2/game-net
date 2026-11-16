"""
Tests for the dynamic SDN part (Lead 5). Run:  python3 -m unittest discover -s tests -v

  * policy.py logic (congestion detector with hysteresis, control-message parser, player registry)
  * the game server really sends REGISTER / LEAVE events to the controller's control socket
  * the Ryu controller logic, driven with fake switches (skipped automatically if Ryu is not installed)

Needs no Mininet and no root.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "sdn"))
from common import packet as pk  # noqa: E402
import policy                    # noqa: E402


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestPolicy(unittest.TestCase):
    def test_rate_bps(self):
        self.assertAlmostEqual(policy.rate_bps(0, 1250000, 1.0), 10e6)
        self.assertEqual(policy.rate_bps(100, 50, 1.0), 0.0)         # counter reset
        self.assertEqual(policy.rate_bps(0, 100, 0), 0.0)

    def test_detector_needs_consecutive_samples_to_turn_on(self):
        d = policy.CongestionDetector(capacity_bps=10e6, up_samples=2)
        self.assertIsNone(d.update(9e6))          # first high sample: not yet
        self.assertIsNone(d.update(1e6))          # a dip resets the counter
        self.assertIsNone(d.update(9e6))
        self.assertEqual(d.update(9.5e6), "on")   # two in a row
        self.assertTrue(d.congested)

    def test_detector_turns_off_only_after_quiet_period(self):
        d = policy.CongestionDetector(capacity_bps=10e6, up_samples=2, down_samples=3)
        d.update(9e6)
        d.update(9e6)
        self.assertIsNone(d.update(1e6))
        self.assertIsNone(d.update(1e6))
        self.assertIsNone(d.update(7e6))          # between 50% and 80%: stays on and resets the quiet counter
        self.assertIsNone(d.update(1e6))
        self.assertIsNone(d.update(1e6))
        self.assertEqual(d.update(1e6), "off")
        self.assertFalse(d.congested)

    def test_detector_reports_only_transitions(self):
        d = policy.CongestionDetector(up_samples=1)
        self.assertEqual(d.update(10e6), "on")
        self.assertIsNone(d.update(10e6))
        self.assertIsNone(d.update(10e6))

    def test_parse_control(self):
        self.assertEqual(policy.parse_control(b"REGISTER 10.0.0.1 3"), ("REGISTER", "10.0.0.1", 3))
        self.assertEqual(policy.parse_control("LEAVE 10.0.0.2 7\n"), ("LEAVE", "10.0.0.2", 7))
        for bad in (b"", b"HELLO 10.0.0.1 1", b"REGISTER 10.0.0.1", b"REGISTER 999.0.0.1 1",
                    b"REGISTER 10.0.0.1 0", b"REGISTER 10.0.0.1 x", b"\xff\xfe"):
            self.assertIsNone(policy.parse_control(bad), bad)

    def test_registry(self):
        r = policy.PlayerRegistry()
        self.assertTrue(r.add("10.0.0.2", 2))
        self.assertFalse(r.add("10.0.0.2", 2))     # heartbeat: not new
        self.assertTrue(r.add("10.0.0.1", 1))
        self.assertEqual(r.ips(), ["10.0.0.1", "10.0.0.2"])
        self.assertTrue(r.remove("10.0.0.1"))
        self.assertFalse(r.remove("10.0.0.1"))


class TestServerNotifiesController(unittest.TestCase):
    """The application -> SDN link: the server must tell the controller when players join and leave."""

    def test_register_and_leave_events(self):
        tmp = tempfile.mkdtemp()
        ctrl_path = os.path.join(tmp, "ctrl.sock")
        ctrl = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        ctrl.bind(ctrl_path)
        ctrl.settimeout(1.0)
        port = free_port()
        server = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server", "server.py"), "--ip", "127.0.0.1", "--port", str(port),
             "--log", os.path.join(tmp, "server_log.csv"), "--duration", "14", "--control-sock", ctrl_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            time.sleep(0.5)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(pk.pack_msg(pk.REGISTER, 0, 0, time.time()), ("127.0.0.1", port))
            msg = ctrl.recv(512)
            self.assertEqual(policy.parse_control(msg), ("REGISTER", "127.0.0.1", 1))
            # the client now goes silent: after the 5 s timeout the server must announce LEAVE
            seen = []
            deadline = time.time() + 9
            while time.time() < deadline:
                try:
                    seen.append(policy.parse_control(ctrl.recv(512)))
                except socket.timeout:
                    continue
                if seen[-1] and seen[-1][0] == "LEAVE":
                    break
            self.assertIn(("LEAVE", "127.0.0.1", 1), seen)
        finally:
            server.terminate()
            server.wait(timeout=5)

    def test_server_runs_without_a_controller(self):
        """No controller listening on the socket must not disturb the game."""
        tmp = tempfile.mkdtemp()
        port = free_port()
        server = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server", "server.py"), "--ip", "127.0.0.1", "--port", str(port),
             "--log", os.path.join(tmp, "server_log.csv"), "--duration", "3",
             "--control-sock", os.path.join(tmp, "nobody-listens.sock")],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        time.sleep(0.5)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(pk.pack_msg(pk.REGISTER, 0, 0, time.time()), ("127.0.0.1", port))
        s.settimeout(1)
        got_ack = False
        for _ in range(10):
            data, _ = s.recvfrom(2048)
            if pk.peek_type(data) == pk.REGISTER_ACK:
                got_ack = True
                break
        server.terminate()
        server.wait(timeout=5)
        self.assertTrue(got_ack)
        self.assertEqual(server.returncode is not None, True)


try:
    from ryu.ofproto import ofproto_v1_3, ofproto_v1_3_parser
    HAVE_RYU = True
except Exception:       # Ryu not installed in this Python
    HAVE_RYU = False


class FakeDatapath:
    """Just enough of a Ryu datapath: records every message and checks it can be serialised."""

    def __init__(self, dpid):
        self.id = dpid
        self.ofproto = ofproto_v1_3
        self.ofproto_parser = ofproto_v1_3_parser
        self.sent = []

    def send_msg(self, msg):
        if msg.xid is None:
            msg.xid = 1
        msg.serialize()                 # raises if the message is malformed
        self.sent.append(msg)


@unittest.skipUnless(HAVE_RYU, "Ryu is not installed in this Python (the VM has it)")
class TestControllerLogic(unittest.TestCase):
    SRC, DST = "00:00:00:00:00:01", "00:00:00:00:00:0a"

    def make(self, mode):
        os.environ["PRIORITY"] = mode
        os.environ["CTRL_SOCK"] = os.path.join(tempfile.mkdtemp(), "c.sock")
        os.environ["CTRL_LOG"] = os.path.join(tempfile.mkdtemp(), "events.csv")
        import importlib
        import controller
        importlib.reload(controller)
        c = controller.GamePriorityController()
        dp = FakeDatapath(1)
        c.datapaths[1] = dp
        c.known_flows[(1, 1, self.SRC, self.DST)] = 5
        return controller, c, dp

    @staticmethod
    def prio_mods(dp, controller):
        return [m for m in dp.sent if getattr(m, "cookie", 0) == controller.PRIO_COOKIE and m.priority == 10
                and m.command == 0]

    def test_static_mode_installs_two_rules_for_any_player(self):
        controller, c, dp = self.make("on")
        self.assertTrue(c.prio_active)
        c.apply_prio()
        mods = self.prio_mods(dp, controller)
        self.assertEqual(len(mods), 2)                               # udp_dst 5005 and udp_src 5005
        self.assertEqual(sorted(("udp_dst" in m.match, "udp_src" in m.match) for m in mods),
                         [(False, True), (True, False)])

    def test_dynamic_mode_starts_without_priority_rules(self):
        controller, c, dp = self.make("dynamic")
        self.assertFalse(c.prio_active)
        c.apply_prio()
        self.assertEqual(self.prio_mods(dp, controller), [])

    def test_dynamic_rules_only_for_registered_players(self):
        controller, c, dp = self.make("dynamic")
        c.set_priority(True, "test")
        self.assertEqual(self.prio_mods(dp, controller), [])         # nobody registered: nothing is prioritised
        c.handle_control(b"REGISTER 10.0.0.1 1")                      # application event while congested
        mods = self.prio_mods(dp, controller)
        self.assertEqual(len(mods), 2)
        self.assertEqual({m.match["ipv4_src"] for m in mods if "ipv4_src" in m.match}, {"10.0.0.1"})
        self.assertEqual({m.match["ipv4_dst"] for m in mods if "ipv4_dst" in m.match}, {"10.0.0.1"})
        actions = mods[0].instructions[0].actions
        self.assertEqual(actions[0].queue_id, controller.GAME_QUEUE)  # set_queue:1
        self.assertEqual(actions[1].port, 5)                          # then output to the learned port

    def test_leave_removes_player_rules(self):
        controller, c, dp = self.make("dynamic")
        c.handle_control(b"REGISTER 10.0.0.1 1")
        c.handle_control(b"REGISTER 10.0.0.2 2")
        c.set_priority(True, "test")
        dp.sent.clear()
        c.handle_control(b"LEAVE 10.0.0.1 1")
        mods = self.prio_mods(dp, controller)
        self.assertEqual(len(mods), 2)                                # only player 2 is left
        self.assertTrue(all("10.0.0.1" not in (m.match.get("ipv4_src"), m.match.get("ipv4_dst")) for m in mods))

    def test_congestion_turns_priority_on_and_off(self):
        controller, c, dp = self.make("dynamic")
        c.handle_control(b"REGISTER 10.0.0.1 1")
        c.rates = {1: 9.9e6, 2: 0.2e6}
        c.evaluate()
        self.assertFalse(c.prio_active)                               # one sample is not enough
        c.evaluate()
        self.assertTrue(c.prio_active)
        self.assertEqual(len(self.prio_mods(dp, controller)), 2)
        c.rates = {1: 0.3e6, 2: 0.2e6}
        for _ in range(3):
            c.evaluate()
        self.assertFalse(c.prio_active)
        deletes = [m for m in dp.sent if m.command == dp.ofproto.OFPFC_DELETE]
        self.assertGreaterEqual(len(deletes), 1)
        self.assertEqual(deletes[-1].cookie, controller.PRIO_COOKIE)  # removes only OUR rules
        events = open(os.environ["CTRL_LOG"]).read()
        for name in ("congestion_detected", "priority_on", "congestion_cleared", "priority_off", "player_register"):
            self.assertIn(name, events)

    def test_static_mode_ignores_congestion_detector(self):
        controller, c, dp = self.make("on")
        c.rates = {1: 0.1e6}
        for _ in range(5):
            c.evaluate()
        self.assertTrue(c.prio_active)                                # static: always on

    def test_off_mode_never_prioritises(self):
        controller, c, dp = self.make("off")
        c.handle_control(b"REGISTER 10.0.0.1 1")
        c.rates = {1: 10e6}
        for _ in range(4):
            c.evaluate()
        self.assertFalse(c.prio_active)
        self.assertEqual(self.prio_mods(dp, controller), [])

    def test_bad_control_message_is_ignored(self):
        controller, c, dp = self.make("dynamic")
        c.handle_control(b"garbage")
        self.assertEqual(c.registry.ips(), [])


if __name__ == "__main__":
    unittest.main()
