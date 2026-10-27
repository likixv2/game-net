#!/usr/bin/env python3
"""
server.py - the game server (Lead 1).

What it does
  * listens on a UDP port
  * REGISTER  -> gives the sender a player id, replies REGISTER_ACK
  * STATE     -> updates that player's position (ignores old/duplicate packets)
  * PING      -> replies PONG immediately (so clients can measure RTT)
  * every 50 ms (20 Hz) sends a WORLD snapshot to every player
  * logs every STATE packet it receives to a CSV (used for latency/jitter/loss)

Run:  python3 server/server.py --port 5005 --log results/server_log.csv --duration 60
"""
import argparse
import csv
import os
import signal
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import packet as pk  # noqa: E402

TICK = 0.05           # 20 broadcasts per second
PLAYER_TIMEOUT = 5.0  # forget a player we have not heard from for this long


class Player:
    def __init__(self, pid, addr):
        self.pid = pid
        self.addr = addr
        self.last_seq = 0       # newest STATE seq accepted from this player
        self.last_seen = time.time()
        self.x = 0.0
        self.y = 0.0
        self.world_seq = 0      # seq counter for WORLD packets sent TO this player
        self.stale = 0          # duplicates / out-of-order packets dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=pk.GAME_PORT)
    ap.add_argument("--log", default="results/server_log.csv")
    ap.add_argument("--duration", type=float, default=0, help="stop after N seconds (0 = run until Ctrl+C)")
    ap.add_argument("--max-players", type=int, default=32)
    args = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
    logf = open(args.log, "w", newline="")
    log = csv.writer(logf)
    log.writerow(["player_id", "seq", "send_ts", "recv_ts"])

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.ip, args.port))
    sock.settimeout(0.005)
    print("[server] listening on %s:%d" % (args.ip, args.port), flush=True)

    players = {}        # pid -> Player
    addr_to_pid = {}    # (ip, port) -> pid
    next_pid = 1
    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    start = time.time()
    next_tick = start + TICK
    rows = 0
    total_rx = 0

    while running:
        now = time.time()
        if args.duration and now - start >= args.duration:
            break

        # ---------- receive one packet (waits at most 5 ms) ----------
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            data = None
        except ConnectionResetError:
         data = None
        except OSError:
            break

        if data:
            recv_ts = time.time()
            try:
                mtype, pid, seq, ts, x, y = pk.unpack_msg(data)
            except Exception:
                mtype = None   # garbage packet, ignore
            if mtype == pk.REGISTER:
                if addr in addr_to_pid:                 # ACK was lost, client asked again
                    p = players[addr_to_pid[addr]]
                elif len(players) < args.max_players:
                    p = Player(next_pid, addr)
                    players[next_pid] = p
                    addr_to_pid[addr] = next_pid
                    print("[server] player %d registered from %s:%d" % (next_pid, addr[0], addr[1]), flush=True)
                    next_pid += 1
                else:
                    p = None
                if p is not None:
                    p.last_seen = recv_ts
                    sock.sendto(pk.pack_msg(pk.REGISTER_ACK, p.pid, 0, time.time()), addr)
            elif mtype == pk.STATE:
                p = players.get(addr_to_pid.get(addr))
                if p is not None:
                    p.last_seen = recv_ts
                    if seq > p.last_seq:                # NEW packet -> accept
                        p.last_seq = seq
                        p.x, p.y = x, y
                        log.writerow([p.pid, seq, "%.6f" % ts, "%.6f" % recv_ts])
                        logf.flush()
                        rows += 1
                        total_rx += 1
                    else:                               # old or duplicate -> drop
                        p.stale += 1
            elif mtype == pk.PING:
                sock.sendto(pk.pack_msg(pk.PONG, pid, seq, ts, x, y), addr)

        # ---------- broadcast the world every TICK ----------
        now = time.time()
        if now >= next_tick:
            next_tick += TICK
            if next_tick < now:        # we fell behind, resync
                next_tick = now + TICK
            # drop players who went silent
            for pid_ in [i for i, p in players.items() if now - p.last_seen > PLAYER_TIMEOUT]:
                print("[server] player %d timed out" % pid_, flush=True)
                addr_to_pid.pop(players[pid_].addr, None)
                del players[pid_]
            if players:
                snapshot = {i: (p.x, p.y) for i, p in players.items()}
                for p in players.values():
                    p.world_seq += 1
                    sock.sendto(pk.pack_world(p.world_seq, time.time(), snapshot), p.addr)

      
    logf.flush()
    logf.close()
    print("[server] done. STATE packets accepted: %d" % total_rx, flush=True)
    for p in players.values():
        print("[server]   player %d: last_seq=%d stale_dropped=%d world_sent=%d"
              % (p.pid, p.last_seq, p.stale, p.world_seq), flush=True)


if __name__ == "__main__":
    main()
