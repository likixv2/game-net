"""
packet.py - the shared packet format. EVERY other file imports this one.

Two packet shapes are used:

1) Client -> Server (and the server's replies to REGISTER / PING)
   Fixed 22 bytes:  type(1) | player_id(1) | seq(4) | timestamp(8) | x(4) | y(4)

2) Server -> Client "WORLD" snapshot (variable length)
   Header 14 bytes: type(1) | seq(4) | timestamp(8) | count(1)
   then `count` entries of 9 bytes each: player_id(1) | x(4) | y(4)

All numbers are big-endian ("network byte order"), hence the "!" in struct formats.
"""
import struct

# ---- message types -------------------------------------------------------
REGISTER = 1      # client -> server: "let me join"
REGISTER_ACK = 2  # server -> client: "you are player N"
STATE = 3         # client -> server: my position
PING = 4          # client -> server: latency probe
PONG = 5          # server -> client: echo of PING
WORLD = 6         # server -> client: positions of all players

TYPE_NAMES = {1: "REGISTER", 2: "REGISTER_ACK", 3: "STATE",
              4: "PING", 5: "PONG", 6: "WORLD"}

# ---- ports ---------------------------------------------------------------
GAME_PORT = 5005   # the SDN controller prioritises UDP traffic on THIS port
NOISE_PORT = 6000  # background congestion traffic uses this port

# ---- struct formats ------------------------------------------------------
_MSG = struct.Struct("!BBIdff")      # 1+1+4+8+4+4 = 22 bytes
_WORLD_HDR = struct.Struct("!BIdB")  # 1+4+8+1     = 14 bytes
_WORLD_ENT = struct.Struct("!Bff")   # 1+4+4       = 9 bytes

MSG_SIZE = _MSG.size


def pack_msg(msg_type, player_id, seq, timestamp, x=0.0, y=0.0):
    """Build a 22-byte client<->server packet."""
    return _MSG.pack(msg_type, player_id, seq, timestamp, x, y)


def unpack_msg(data):
    """Return (type, player_id, seq, timestamp, x, y). Raises ValueError if the packet is bad."""
    if len(data) != _MSG.size:
        raise ValueError("bad length %d (expected %d)" % (len(data), _MSG.size))
    return _MSG.unpack(data)


def pack_world(seq, timestamp, players):
    """players = {player_id: (x, y)}. Returns bytes."""
    items = list(players.items())[:255]
    out = _WORLD_HDR.pack(WORLD, seq, timestamp, len(items))
    for pid, (x, y) in items:
        out += _WORLD_ENT.pack(pid, x, y)
    return out


def unpack_world(data):
    """Return (seq, timestamp, {player_id: (x, y)}). Raises ValueError if bad."""
    if len(data) < _WORLD_HDR.size:
        raise ValueError("world packet too short")
    msg_type, seq, ts, count = _WORLD_HDR.unpack_from(data, 0)
    if msg_type != WORLD:
        raise ValueError("not a WORLD packet")
    expected = _WORLD_HDR.size + count * _WORLD_ENT.size
    if len(data) != expected:
        raise ValueError("world packet bad length")
    players = {}
    offset = _WORLD_HDR.size
    for _ in range(count):
        pid, x, y = _WORLD_ENT.unpack_from(data, offset)
        players[pid] = (x, y)
        offset += _WORLD_ENT.size
    return seq, ts, players


def peek_type(data):
    """First byte is always the message type."""
    return data[0] if data else None
