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
