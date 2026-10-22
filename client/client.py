#!/usr/bin/env python3
"""
client.py - one game client / bot (Lead 2).

What it does
  1. REGISTER with the server (retries 3 times, 1 s each)
  2. 20 times a second: move randomly and send a STATE packet with seq = 1,2,3,...
  3. receives WORLD snapshots from the server:
        - if seq is not newer than the last one  -> stale/duplicate, DROP it
        - if seq jumped (e.g. 7 -> 10)            -> packets 8 and 9 were LOST, count them
        - the newest snapshot replaces the old one (full snapshots, so a lost one is just
          skipped; meanwhile we keep showing the last known positions)
  4. once a second sends a PING and measures round-trip time (RTT)
  5. writes CSV logs for the analyzer

Run:  python3 client/client.py --server-ip 127.0.0.1 --name p1 --duration 30
"""
import argparse
import csv
import os
import random
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import packet as pk  # noqa: E402


def register(sock, server, tries=3, wait=1.0):
    """Send REGISTER until we get REGISTER_ACK. Returns our player id, or None."""
    for attempt in range(1, tries + 1):
        sock.sendto(pk.pack_msg(pk.REGISTER, 0, 0, time.time()), server)
        deadline = time.time() + wait
        while time.time() < deadline:
            sock.settimeout(max(0.01, deadline - time.time()))
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                break
            if pk.peek_type(data) == pk.REGISTER_ACK:
                try:
                    return pk.unpack_msg(data)[1]
                except ValueError:
                    pass
        print("[client] no ACK, retry %d/%d" % (attempt, tries), flush=True)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server-ip", default="127.0.0.1")
    ap.add_argument("--server-port", type=int, default=pk.GAME_PORT)
    ap.add_argument("--name", default="p1")
    ap.add_argument("--duration", type=float, default=30)
    ap.add_argument("--rate", type=float, default=20, help="STATE packets per second")
    ap.add_argument("--logdir", default="results")
    args = ap.parse_args()

    os.makedirs(args.logdir, exist_ok=True)
    server = (args.server_ip, args.server_port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    pid = register(sock, server)
    if pid is None:
        print("[client %s] could not register, giving up" % args.name, flush=True)
        sys.exit(1)
    print("[client %s] registered as player %d" % (args.name, pid), flush=True)

    world_f = open(os.path.join(args.logdir, "client_%s_log.csv" % args.name), "w", newline="")
    world_log = csv.writer(world_f)
    world_log.writerow(["seq", "send_ts", "recv_ts"])
    rtt_f = open(os.path.join(args.logdir, "client_%s_rtt.csv" % args.name), "w", newline="")
    rtt_log = csv.writer(rtt_f)
    rtt_log.writerow(["time", "rtt_ms"])

    x, y = random.uniform(0, 100), random.uniform(0, 100)
    seq = 0                 # our outgoing STATE counter
    last_world_seq = 0      # newest WORLD seq we accepted
    sent = recvd = lost = stale = 0
    world = {}              # last known positions of all players: pid -> (x, y)
    interval = 1.0 / args.rate
    start = time.time()
    next_send = start
    next_ping = start + 1.0
    next_report = start + 5.0
    sock.settimeout(0.005)

    while True:
        now = time.time()
        if now - start >= args.duration:
            break

        # ---- send our position ----
        if now >= next_send:
            next_send += interval
            if next_send < now:
                next_send = now + interval
            x = min(100, max(0, x + random.uniform(-2, 2)))   # random walk
            y = min(100, max(0, y + random.uniform(-2, 2)))
            seq += 1
            sock.sendto(pk.pack_msg(pk.STATE, pid, seq, time.time(), x, y), server)
            sent += 1

        # ---- latency probe ----
        if now >= next_ping:
            next_ping += 1.0
            sock.sendto(pk.pack_msg(pk.PING, pid, 0, time.time()), server)

        # ---- receive ----
        try:
            data, _ = sock.recvfrom(2048)
        except socket.timeout:
            data = None
        if data:
            recv_ts = time.time()
            t = pk.peek_type(data)
            if t == pk.WORLD:
                try:
                    wseq, wts, players = pk.unpack_world(data)
                except ValueError:
                    continue
                if wseq <= last_world_seq:
                    stale += 1                         # old / duplicate: ignore
                else:
                    if wseq > last_world_seq + 1 and last_world_seq != 0:
                        lost += wseq - last_world_seq - 1   # gap in seq numbers = lost packets
                    last_world_seq = wseq
                    world = players                    # newest snapshot wins
                    recvd += 1
                    world_log.writerow([wseq, "%.6f" % wts, "%.6f" % recv_ts])
            elif t == pk.PONG:
                try:
                    _, _, _, ts, _, _ = pk.unpack_msg(data)
                    rtt_log.writerow(["%.3f" % (recv_ts - start), "%.3f" % ((recv_ts - ts) * 1000)])
                except ValueError:
                    pass

        if now >= next_report:
            next_report += 5.0
            print("[client %s] t=%3ds sent=%d recv=%d lost=%d stale=%d players_seen=%d"
                  % (args.name, now - start, sent, recvd, lost, stale, len(world)), flush=True)

    world_f.close()
    rtt_f.close()
    print("[client %s] FINISHED sent=%d recv=%d lost=%d stale=%d" % (args.name, sent, recvd, lost, stale), flush=True)


if __name__ == "__main__":
    main()
