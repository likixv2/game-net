#!/usr/bin/env python3
"""
noise.py - background traffic to create congestion (no iperf needed).

  sink   (receives and throws away):   python3 tools/noise.py sink --port 6000
  sender (floods UDP at a given rate): python3 tools/noise.py send --ip 10.0.0.5 --port 6000 --mbps 15 --duration 60
"""
import argparse
import socket
import time


def sink(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    s.bind(("0.0.0.0", port))
    while True:
        s.recv(65535)


def send(ip, port, mbps, duration, size=1200):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    payload = b"x" * size
    pkts_per_sec = mbps * 1e6 / 8 / size
    start = time.time()
    sent = 0
    while True:
        now = time.time()
        elapsed = now - start
        if elapsed >= duration:
            break
        # how many packets we SHOULD have sent by now vs. how many we did
        due = int(elapsed * pkts_per_sec) - sent
        for _ in range(max(0, due)):
            try:
                s.sendto(payload, (ip, port))
            except OSError:
                pass            # buffer full, that's fine, we are flooding on purpose
            sent += 1
        time.sleep(0.002)
    print("[noise] sent %d packets (~%.1f Mbps target)" % (sent, mbps), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["sink", "send"])
    ap.add_argument("--ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=6000)
    ap.add_argument("--mbps", type=float, default=15)
    ap.add_argument("--duration", type=float, default=60)
    a = ap.parse_args()
    if a.mode == "sink":
        sink(a.port)
    else:
        send(a.ip, a.port, a.mbps, a.duration)
