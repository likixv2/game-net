# Lead 2 - Client & Reliability

**Your file:** `client/client.py`
**Your mission:** the game client. It registers (with retry), sends its position 20 times a second with increasing
sequence numbers, detects lost / old / duplicate packets from the server, keeps playing when packets go missing,
and measures round-trip time with PING/PONG.

The code is already written and tested; your job is to **run it, break it on purpose, understand it, and explain it**.

---

## Step 0 - Setup
```bash
cd game-net
python3 -m unittest discover -s tests -v       # must end with OK
```

## Step 1 - Normal run (10 min)
```bash
mkdir -p results/local
python3 server/server.py --port 5005 --log results/local/server_log.csv --duration 60 &
python3 client/client.py --name p1 --duration 20 --logdir results/local
```
Expected last line: `FINISHED sent=400 recv=~400 lost=0 stale=0`.
Files created: `results/local/client_p1_log.csv` (every WORLD packet received) and `client_p1_rtt.csv` (ping times).

## Step 2 - Understand the code (30 min)
The client is one loop that does three jobs depending on the clock:
1. **Send** (every 1/20 s): random-walk the position, `seq += 1`, send STATE.
2. **Ping** (every 1 s): send PING with the current time. When PONG returns, `rtt = now - ts`.
3. **Receive**: for each WORLD packet look at `wseq`:
   - `wseq <= last_world_seq` -> **stale or duplicate**, ignore (`stale += 1`).
   - `wseq > last_world_seq + 1` -> packets in between were **lost**: `lost += wseq - last_world_seq - 1`.
   - otherwise normal. Either way the newest snapshot replaces `world`.

**How the client "handles" loss:** every WORLD packet is a complete snapshot, so a lost one is simply replaced by the next
one; until then the client keeps using the last known positions (`world` is not cleared). Registration also handles loss
by retrying 3 times.

## Step 3 - Break it on purpose (20 min) - this is your demo of "handle packet loss"
**Option A (Linux, needs sudo)** - add 10% loss to the loopback interface:
```bash
sudo tc qdisc add dev lo root netem loss 10%
python3 server/server.py --port 5005 --log results/local/server_log.csv --duration 40 &
python3 client/client.py --name p1 --duration 20 --logdir results/local
sudo tc qdisc del dev lo root              # IMPORTANT: remove it afterwards
```
You should see roughly `lost=` about 10% of `recv+lost`.

**Option B (any OS, no sudo)** - the test `test_client_survives_20_percent_loss_and_counts_it` in `tests/test_protocol.py`
uses a Python "lossy proxy" that drops 20% of packets. Run: `python3 -m unittest tests.test_protocol.TestEndToEnd.test_client_survives_20_percent_loss_and_counts_it -v`.

Questions to answer in your notes: Does the client crash? Does `lost` roughly match the loss rate? What happens at 50%? At 100% (server killed)?

## Step 4 - Improvement ideas (optional, pick one)
- **Dead reckoning**: if no WORLD arrives for 100 ms, estimate other players' positions from their last two known positions.
- Re-register automatically if the server restarts (no WORLD for 3 s -> send REGISTER again).
- Print the RTT average every 5 s.

## You are DONE when
- [ ] normal run: `lost=0`
- [ ] with 10% loss: client finishes, `lost` is about 10%, no crash
- [ ] you can explain the 3 branches of the receive logic
- [ ] you can start 3 clients at once and all register with different ids

---

## LLM prompt pack (paste PROJECT CONTEXT from README.md first)

**P1 - Explain the code**
> Here is my `client/client.py`: ```<paste>```. Explain the main loop step by step as if I am a beginner. Specifically explain how sequence
> numbers let the client detect (a) lost packets, (b) duplicates, (c) out-of-order packets. Use a small example with seq 1,2,5,4,5,6.

**P2 - Add dead reckoning**
> Modify this client so that if no WORLD packet arrives for 100 ms, it estimates every other player's position by extrapolating from the
> last two received positions. Keep the code simple and beginner-friendly. Show the full changed file and mark new lines with `# NEW`: ```<paste>```

**P3 - Auto re-register**
> In this client, if no WORLD packet is received for 3 seconds, make the client send REGISTER again and continue with the new player id.
> Do not break the existing sequence-number logic. ```<paste>```

**P4 - Debug**
> My client does this wrong: <describe>. I ran: <command>. Output: ```<paste>```. My code: ```<paste>```. Find the root cause and give the smallest fix.

**P5 - Viva practice**
> Be my examiner for the UDP client of my Computer Networks game project. Ask me one question at a time about: sequence numbers, packet loss
> handling, why UDP, timeouts and retries, RTT measurement with ping/pong. After each answer give me feedback and the ideal answer.

---

## Common errors
| Problem | Fix |
|---|---|
| `could not register, giving up` | server is not running / wrong `--server-ip` / wrong port |
| `lost` is always 0 even with loss | the loss rule is on the wrong interface; on one laptop use `dev lo` |
| after tests the network is weird | you forgot `sudo tc qdisc del dev lo root` |

## Viva questions (practice answers)
1. **How do you detect packet loss?** A jump in sequence numbers: after seq 7, receiving seq 10 means 8 and 9 were lost.
2. **What do you do with a packet whose seq is lower than one you already saw?** It is stale or a duplicate, so it is discarded; applying it would move players backwards in time.
3. **Does UDP retransmit?** No. We chose not to retransmit game state, because the next update is more useful than a late old one. We only retry registration, since it is one-time and must succeed.
4. **How is RTT measured?** The client sends PING with its clock time; the server echoes it in PONG; RTT = time of arrival - echoed time.
5. **What happens to the game under heavy loss?** The client keeps displaying the last known positions until a newer snapshot arrives; it never blocks.
