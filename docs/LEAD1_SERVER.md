# Lead 1 - Server & Protocol

**Your files:** `common/packet.py`, `server/server.py`
**Your mission:** build the game server. It registers players, receives their positions, ignores old/duplicate packets,
answers pings, broadcasts the world 20 times a second, and logs every packet so Lead 4 can measure latency/jitter/loss.

Good news: both files are already written and tested. Your job is to **run them, understand them well enough to explain
them, and improve them**. Do the steps in order.

---

## Step 0 - Setup (5 min)
```bash
git clone <your repo url> && cd game-net        # or unzip the project folder
python3 --version                               # needs 3.8+
python3 -m unittest discover -s tests -v        # should end with OK
```

## Step 1 - Run the server and two clients (10 min)
Open 3 terminals in the project folder.
```bash
# terminal 1
mkdir -p results/local
python3 server/server.py --port 5005 --log results/local/server_log.csv --duration 60
# terminal 2
python3 client/client.py --name p1 --duration 30 --logdir results/local
# terminal 3
python3 client/client.py --name p2 --duration 30 --logdir results/local
```
**You should see:** the server printing `player 1 registered`, `player 2 registered`; clients printing
`sent=... recv=... lost=0`. When the clients end, `results/local/server_log.csv` has about 600 rows.

## Step 2 - Understand `packet.py` (20 min)
A UDP packet is just bytes. `struct` converts numbers to bytes and back.
- `"!BBIdff"`: `!` = network byte order, `B` = 1 byte, `I` = 4-byte integer, `d` = 8-byte float (the timestamp), `f` = 4-byte float.
  Total 1+1+4+8+4+4 = **22 bytes**.
- `pack_msg(...)` builds those bytes, `unpack_msg(...)` reads them back and raises an error if the length is wrong
  (so garbage packets cannot crash the server).
- WORLD packets are variable length because the number of players changes: a 14-byte header then 9 bytes per player.

Try it yourself in a Python shell:
```python
from common import packet as pk
b = pk.pack_msg(pk.STATE, 3, 42, 1.5, 10.0, 20.0)
print(len(b), b.hex())
print(pk.unpack_msg(b))
```

## Step 3 - Understand `server.py` (30 min)
Read the file from top to bottom. The main loop does three things, over and over:

1. **Receive** one packet (waits at most 5 ms), then decide by message type:
   - `REGISTER` -> new address gets the next player id; an address we already know gets the *same* id again
     (because its ACK may have been lost - this is "handle packet loss" for registration).
   - `STATE` -> **sequence number check**: `if seq > p.last_seq` accept and log it; otherwise it is old or a duplicate, drop it.
   - `PING` -> immediately send `PONG` with the same timestamp.
2. **Broadcast** every 50 ms: build one snapshot of all players and send it to every player. Each player has its own
   `world_seq` counter so the client can detect gaps (= lost packets).
3. **Clean up**: players silent for 5 s are removed.

Why a CSV log? Lead 4's analyzer reads `server_log.csv` and computes uplink latency, jitter and loss from the
`send_ts`, `recv_ts` and `seq` columns.

## Step 4 - Experiments to run (15 min) - write the results in your notes
1. **Kill a client with Ctrl+C**, wait 6 s, watch the server print `timed out`. Start it again: it registers with a new id.
2. **Duplicate test**: the automated test `test_stale_and_duplicate_packets_are_dropped` sends seq `1,2,5,3,5,4,6` and
   checks only `1,2,5,6` are accepted. Read that test and explain why.
3. **Many players**: start 5 clients. Do all see `players_seen=5`?

## Step 5 - Improvements you can add (pick one or two, optional)
- Print a one-line status every 5 s (players online, packets per second).
- Add a `--tick` argument (broadcast rate).
- Send REGISTER_ACK a second time if the same address registers again within 1 s (already done - read how).

## You are DONE when
- [ ] `python3 -m unittest discover -s tests -v` shows OK
- [ ] 3 clients register, play 30 s, `server_log.csv` has about 1800 rows
- [ ] You can answer every viva question below without looking

---

## LLM prompt pack
Paste the **PROJECT CONTEXT** block from `README.md` first in every new chat, then one of these. Replace `<...>`.

**P1 - Explain the code to me**
> Here is my `server/server.py`: ```<paste file>```. Explain it to me block by block like I am a beginner. For each block say what
> problem it solves. Then ask me 5 questions to check that I understood.

**P2 - Explain struct**
> Explain Python's `struct.pack` and `struct.unpack` with the format string "!BBIdff". Show me byte by byte what 22 bytes look like for
> type=3, player_id=2, seq=10, timestamp=1.5, x=3.0, y=4.0. Why do we use "!" (network byte order)?

**P3 - Add a feature**
> Using this `server.py`: ```<paste file>```, add <feature, e.g. "print how many packets per second the server receives every 5 seconds">.
> Give me the full modified file, mark the new lines with `# NEW`, and tell me how to test it.

**P4 - Debug**
> My server does this: <describe>. Command I ran: <command>. Output/error: ```<paste>```. Here is the code: ```<paste>```.
> Find the cause, explain why it happens, and give me the fix. Do not rewrite everything, only what is needed.

**P5 - Viva practice**
> Act as my Computer Networks examiner. I built the UDP game server in this project (code: ```<paste>```). Ask me one question at a time,
> wait for my answer, then tell me what was right, what was missing, and the ideal answer. Cover: why UDP, sequence numbers,
> registration, packet loss, why timestamps are in the packet.

---

## Common errors
| Problem | Fix |
|---|---|
| `OSError: Address already in use` | an old server is still running: `pkill -f server.py` or use `--port 5006` |
| clients say `no ACK, retry` | server not started, wrong `--server-ip`, or a firewall (Linux: `sudo ufw allow 5005/udp`) |
| `ModuleNotFoundError: common` | run from the project root folder, not from inside `server/` |

## Viva questions (practice answers)
1. **Why UDP and not TCP for a game?** TCP retransmits lost packets and delivers in order, so one lost packet stalls all later ones (head-of-line blocking). In a game, old positions are useless; we want the newest state, not a perfect history. UDP has no such delay.
2. **What do sequence numbers do?** They let the receiver spot loss (gaps), duplicates and reordering (an old seq arriving after a newer one).
3. **How does registration survive loss?** The client retries up to 3 times; the server answers a repeated REGISTER from the same address with the same id.
4. **Why is the timestamp in every packet?** The receiver computes one-way latency as `recv_ts - send_ts`, and jitter from how that changes. It works in Mininet because all hosts share one clock.
5. **Why does the server send full snapshots instead of changes?** A lost snapshot is harmless because the next one replaces it; no retransmission needed.
