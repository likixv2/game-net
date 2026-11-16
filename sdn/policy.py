"""
policy.py - the decision logic of the dynamic SDN controller, kept free of Ryu so it can be unit tested.

  * CongestionDetector : turns a stream of link-utilisation samples into "congestion started" /
                         "congestion ended" events, with hysteresis so it does not flap.
  * PlayerRegistry     : the set of player IPs announced by the game server (application events).
  * parse_control      : parses the text messages the game server sends to the controller.
  * rate_bps           : bits per second from two byte counters.

Control message format (one UDP/Unix datagram, plain text):
    REGISTER <ip> <player_id>      a player joined (sent again every 2 s as a heartbeat; harmless)
    LEAVE    <ip> <player_id>      a player timed out
"""
import ipaddress


def rate_bps(prev_bytes, cur_bytes, dt):
    """Average rate in bits per second between two byte-counter readings dt seconds apart."""
    if dt <= 0 or cur_bytes < prev_bytes:
        return 0.0
    return (cur_bytes - prev_bytes) * 8.0 / dt


class CongestionDetector:
    """Hysteresis detector.

    update(rate) returns "on"  after `up_samples`   consecutive samples >= high * capacity,
                   "off" after `down_samples` consecutive samples <  low  * capacity,
                   None  otherwise.  Only transitions are reported.
    """

    def __init__(self, capacity_bps=10e6, high=0.8, low=0.5, up_samples=2, down_samples=3):
        self.capacity = capacity_bps
        self.high = high
        self.low = low
        self.up_samples = up_samples
        self.down_samples = down_samples
        self.congested = False
        self._up = 0
        self._down = 0

    def update(self, rate):
        if not self.congested:
            self._up = self._up + 1 if rate >= self.high * self.capacity else 0
            if self._up >= self.up_samples:
                self.congested, self._up, self._down = True, 0, 0
                return "on"
        else:
            self._down = self._down + 1 if rate < self.low * self.capacity else 0
            if self._down >= self.down_samples:
                self.congested, self._up, self._down = False, 0, 0
                return "off"
        return None


class PlayerRegistry:
    """Player IPs the game server has announced."""

    def __init__(self):
        self.players = {}                      # ip -> player id

    def add(self, ip, pid):
        """Returns True if this IP is new."""
        new = ip not in self.players
        self.players[ip] = pid
        return new

    def remove(self, ip):
        """Returns True if the IP was known."""
        return self.players.pop(ip, None) is not None

    def ips(self):
        return sorted(self.players)


def parse_control(text):
    """Parse one control message. Returns (command, ip, player_id) or None if it is not valid."""
    if isinstance(text, bytes):
        try:
            text = text.decode("ascii")
        except UnicodeDecodeError:
            return None
    parts = text.strip().split()
    if len(parts) != 3 or parts[0] not in ("REGISTER", "LEAVE"):
        return None
    try:
        ip = str(ipaddress.IPv4Address(parts[1]))
        pid = int(parts[2])
    except ValueError:
        return None
    if not 0 < pid < 256:
        return None
    return parts[0], ip, pid
