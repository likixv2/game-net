"""
ack.py - loss acknowledgment for the unreliable STATE stream.

Idea (same as Quake 3 / Gaffer on Games): no extra packets, no retransmission of old state.
The server records which client STATE seqs it received and piggybacks that on every WORLD packet:
    ack_seq  = highest client seq received so far
    ack_bits = 32-bit mask; bit i set  <=>  seq (ack_seq - 1 - i) was also received
The client collects these acks and so knows EXACTLY which of its packets were lost.
"""

MASK = 0xFFFFFFFF


class RecvWindow:
    """Server side: one per player. Records every STATE seq that arrives."""

    def __init__(self):
        self.highest = 0
        self.bits = 0
        self.count = 0          # unique seqs received

    def on_packet(self, seq):
        """Record seq. Returns True if it was new, False if duplicate / too old to track."""
        if seq > self.highest:
            if self.highest:
                shift = seq - self.highest
                self.bits = ((self.bits << shift) | (1 << (shift - 1))) & MASK
            self.highest = seq
            self.count += 1
            return True
        d = self.highest - seq
        if 1 <= d <= 32:
            m = 1 << (d - 1)
            if not self.bits & m:
                self.bits |= m
                self.count += 1
                return True
        return False


class AckTracker:
    """Client side: collects acks from WORLD packets."""

    def __init__(self):
        self.acked = set()
        self.last_ack = 0

    def on_ack(self, ack_seq, ack_bits):
        if ack_seq <= 0:
            return
        self.acked.add(ack_seq)
        for i in range(32):
            if (ack_bits >> i) & 1:
                s = ack_seq - 1 - i
                if s >= 1:
                    self.acked.add(s)
        if ack_seq > self.last_ack:
            self.last_ack = ack_seq

    def summary(self):
        """(expected, received, lost) for seqs 1..last_ack. Packets newer than last_ack
        are still unconfirmed (in flight / tail of the run) and are NOT counted as lost."""
        expected = self.last_ack
        got = sum(1 for s in self.acked if s <= expected)
        return expected, got, expected - got

    def lost_seqs(self):
        return [s for s in range(1, self.last_ack + 1) if s not in self.acked]