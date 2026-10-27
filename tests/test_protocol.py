"""
Automated tests (Lead 5).   Run:  python3 -m unittest discover -s tests -v

Needs no Mininet - everything runs on localhost.
"""
import csv
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from common import packet as pk  # noqa: E402
from metrics import analyze      # noqa: E402


class TestPacketFormat(unittest.TestCase):
    def test_msg_roundtrip(self):
        data = pk.pack_msg(pk.STATE, 7, 12345, 1700000000.123, 1.5, -2.5)
        self.assertEqual(len(data), 22)
        t, pid, seq, ts, x, y = pk.unpack_msg(data)
        self.assertEqual((t, pid, seq, x, y), (pk.STATE, 7, 12345, 1.5, -2.5))
        self.assertAlmostEqual(ts, 1700000000.123, places=3)

    def test_world_roundtrip(self):
        data = pk.pack_world(9, 55.5, {1: (1.0, 2.0), 2: (3.0, 4.0)})
        seq, ts, players = pk.unpack_world(data)
        self.assertEqual(seq, 9)
        self.assertEqual(players, {1: (1.0, 2.0), 2: (3.0, 4.0)})

    def test_bad_packets_rejected(self):
        with self.assertRaises(ValueError):
            pk.unpack_msg(b"short")
        with self.assertRaises(ValueError):
            pk.unpack_world(b"\x06\x00")


class TestAnalyzer(unittest.TestCase):
    def test_constant_delay_gives_zero_jitter(self):
        rows = [(i, i * 0.05, i * 0.05 + 0.010) for i in range(1, 101)]   # always 10 ms
        m = analyze.stream_metrics(rows)
        self.assertAlmostEqual(analyze.mean(m["lat"]), 10.0, places=3)
        self.assertAlmostEqual(m["jitter"], 0.0, places=6)
        self.assertEqual(m["expected"], 100)

    def test_loss_is_detected(self):
        rows = [(i, i * 0.05, i * 0.05 + 0.01) for i in range(1, 101) if i % 10 != 0]  # drop every 10th
        m = analyze.stream_metrics(rows)
        s = analyze.combine([m])
        self.assertAlmostEqual(s["loss_pct"], 100.0 * 9 / 99, places=1)   # 9 gaps inside seq 1..99

    def test_varying_delay_gives_jitter(self):
        rows = [(i, i * 0.05, i * 0.05 + (0.010 if i % 2 else 0.030)) for i in range(1, 201)]
        self.assertGreater(analyze.stream_metrics(rows)["jitter"], 5.0)


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class LossyProxy(threading.Thread):
    """Sits between ONE client and the server and drops a share of packets in both directions."""

    def __init__(self, listen_port, server_port, loss):
        super().__init__(daemon=True)
        self.loss, self.server = loss, ("127.0.0.1", server_port)
        self.front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.front.bind(("127.0.0.1", listen_port))
        self.front.settimeout(0.05)
        self.back = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.back.settimeout(0.05)
        self.client = None
        self.running = True

    def run(self):
        while self.running:
            try:
                data, addr = self.front.recvfrom(2048)
                self.client = addr
                if data[0] == pk.REGISTER or random.random() >= self.loss:
                    self.back.sendto(data, self.server)
            except socket.timeout:
                pass
            try:
                data, _ = self.back.recvfrom(2048)
                if self.client and (data[0] == pk.REGISTER_ACK or random.random() >= self.loss):
                    self.front.sendto(data, self.client)
            except socket.timeout:
                pass


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.port = free_port()
        self.server = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server", "server.py"), "--ip", "127.0.0.1",
             "--port", str(self.port), "--log", os.path.join(self.tmp, "server_log.csv"), "--duration", "12"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        time.sleep(0.5)

    def tearDown(self):
        self.server.terminate()
        self.server.wait(timeout=5)

    def _register(self, sock):
        sock.sendto(pk.pack_msg(pk.REGISTER, 0, 0, time.time()), ("127.0.0.1", self.port))
        sock.settimeout(1)
        data, _ = sock.recvfrom(2048)
        return pk.unpack_msg(data)

    def test_multiple_players_get_distinct_ids_and_repeat_gets_same_id(self):
        socks = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(3)]
        ids = [self._register(s)[1] for s in socks]
        self.assertEqual(sorted(ids), [1, 2, 3])
        self.assertEqual(self._register(socks[0])[1], ids[0])      # lost-ACK retry returns the same id
        self.assertEqual(self._register(socks[0])[0], pk.REGISTER_ACK)

    def test_stale_and_duplicate_packets_are_dropped(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        pid = self._register(s)[1]
        for seq in (1, 2, 5, 3, 5, 4, 6):                           # 3, 5(dup), 4 are old
            s.sendto(pk.pack_msg(pk.STATE, pid, seq, time.time(), 1, 1), ("127.0.0.1", self.port))
            time.sleep(0.02)
        time.sleep(0.3)
        self.server.terminate()
        self.server.wait(timeout=5)
        with open(os.path.join(self.tmp, "server_log.csv")) as f:
            seqs = [int(r["seq"]) for r in csv.DictReader(f)]
        self.assertEqual(seqs, [1, 2, 5, 6])

    def test_ping_pong_echoes_timestamp(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        pid = self._register(s)[1]
        s.sendto(pk.pack_msg(pk.PING, pid, 0, 123.456), ("127.0.0.1", self.port))
        while True:
            data, _ = s.recvfrom(2048)
            if pk.peek_type(data) == pk.PONG:
                break
        self.assertAlmostEqual(pk.unpack_msg(data)[3], 123.456, places=3)

    def test_client_survives_20_percent_loss_and_counts_it(self):
        proxy_port = free_port()
        proxy = LossyProxy(proxy_port, self.port, 0.20)
        proxy.start()
        res = subprocess.run(
            [sys.executable, os.path.join(ROOT, "client", "client.py"), "--server-ip", "127.0.0.1",
             "--server-port", str(proxy_port), "--name", "t1", "--duration", "6", "--logdir", self.tmp],
            capture_output=True, text=True, timeout=30)
        proxy.running = False
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        last = [l for l in res.stdout.splitlines() if "FINISHED" in l][-1]
        lost = int(last.split("lost=")[1].split()[0])
        recv = int(last.split("recv=")[1].split()[0])
        self.assertGreater(lost, 0)                                 # it noticed the gaps
        self.assertGreater(recv, 30)                                # and kept playing


if __name__ == "__main__":
    unittest.main()
