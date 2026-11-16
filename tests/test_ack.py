import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import packet as pk  # noqa: E402
from common.ack import RecvWindow, AckTracker  # noqa: E402


class TestWorldAckFields(unittest.TestCase):
    def test_round_trip(self):
        data = pk.pack_world(7, 123.5, {1: (1.0, 2.0), 2: (3.0, 4.0)}, ack_seq=42, ack_bits=0b1011)
        self.assertEqual(len(data), 22 + 2 * 9)
        seq, ts, players, ack_seq, ack_bits = pk.unpack_world_full(data)
        self.assertEqual((seq, ack_seq, ack_bits), (7, 42, 0b1011))
        self.assertEqual(players[2], (3.0, 4.0))

    def test_old_api_still_works(self):
        data = pk.pack_world(3, 1.0, {1: (5.0, 6.0)})
        seq, ts, players = pk.unpack_world(data)
        self.assertEqual(seq, 3)
        self.assertEqual(pk.unpack_world_full(data)[3:], (0, 0))


class TestRecvWindow(unittest.TestCase):
    def test_gap_sets_bits(self):
        w = RecvWindow()
        for s in (1, 2, 4, 5):
            w.on_packet(s)
        self.assertEqual(w.highest, 5)
        self.assertEqual(w.bits, 0b1101)     # 4, 2, 1 received; 3 missing
        self.assertEqual(w.count, 4)

    def test_late_packet_fills_hole(self):
        w = RecvWindow()
        for s in (1, 2, 4, 5):
            w.on_packet(s)
        self.assertTrue(w.on_packet(3))
        self.assertEqual(w.bits, 0b1111)
        self.assertEqual(w.count, 5)

    def test_duplicate_not_counted(self):
        w = RecvWindow()
        w.on_packet(1)
        w.on_packet(2)
        self.assertFalse(w.on_packet(2))
        self.assertFalse(w.on_packet(1))
        self.assertEqual(w.count, 2)

    def test_big_jump_clears_window(self):
        w = RecvWindow()
        w.on_packet(1)
        w.on_packet(100)
        self.assertEqual(w.bits, 0)
        self.assertEqual(w.count, 2)


class TestAckTracker(unittest.TestCase):
    def _run(self, sent, drop):
        server = RecvWindow()
        client = AckTracker()
        for s in range(1, sent + 1):
            if s not in drop:
                server.on_packet(s)
            if server.highest:                      # a WORLD packet comes back every time
                client.on_ack(server.highest, server.bits)
        return client

    def test_finds_exact_lost_packets(self):
        c = self._run(10, drop={3, 7})
        self.assertEqual(c.summary(), (10, 8, 2))
        self.assertEqual(c.lost_seqs(), [3, 7])

    def test_tail_is_not_counted_as_lost(self):
        c = self._run(10, drop={10})
        self.assertEqual(c.summary(), (9, 9, 0))

    def test_no_loss(self):
        c = self._run(50, drop=set())
        self.assertEqual(c.summary(), (50, 50, 0))

    def test_lost_ack_is_recovered_by_later_ack(self):
        server = RecvWindow()
        client = AckTracker()
        for s in (1, 2, 3):
            server.on_packet(s)
        # WORLD packets carrying acks for 1 and 2 are lost; only the last one arrives
        client.on_ack(server.highest, server.bits)
        self.assertEqual(client.summary(), (3, 3, 0))


if __name__ == "__main__":
    unittest.main()