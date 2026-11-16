# Lead 5 - Integration, QA & Report

**Your files:** `README.md`, `tests/`, `docs/REPORT_TEMPLATE.md`, the final report, the demo.
**Your mission:** make sure the four other parts work *together*, keep the team on schedule, and write the report and demo.
You are the glue. Nobody else sees the whole project - you do.

---

## Step 0 - Kickoff (first 30 minutes, everyone on a call)
1. Everyone reads `README.md` (architecture, packet format, ports).
2. Everyone confirms they have **Ubuntu with Mininet** working or know who does (Lead 3 and 4 need it; 1 and 2 do not).
3. Create the repository and branches:
```bash
cd game-net
git init && git add . && git commit -m "initial project"
git branch -M main
# push to GitHub, then everybody:
git checkout -b lead1-server        # lead2-client, lead3-sdn, lead4-metrics
```
4. Set the **checkpoints** (write the times in the group chat): C1 after ~2.5 h, C2 after ~5 h, final after ~8 h.
5. Remind everyone: **packet format is frozen**, and everybody opens their own guide in `docs/`.

## Step 1 - Verify the baseline yourself (15 min)
```bash
python3 -m unittest discover -s tests -v          # must say OK
```
Read `tests/test_protocol.py`. It tests: packet round-trips, registration of 3 players with distinct ids, a repeated REGISTER getting the same id,
duplicate/stale packet rejection, PING/PONG, a client under 20% packet loss, and the jitter/loss maths. Be able to explain each test.

## Step 2 - Checkpoints (your main job)
At each checkpoint, 15 minutes, everybody on a call:

**C1 (~2.5 h): "each part works alone"**
- Lead 1 + 2: server and client run on one laptop (`README` Quick start A), tests OK.
- Lead 3: `pingall` works in Mininet and `ovs-vsctl list queue` shows queues.
- Lead 4: analyzer runs on local logs.
- Merge all branches into `main`: `git checkout main && git merge lead1-server` etc. Fix conflicts together.

**C2 (~5 h): "everything works together in Mininet"**
Run ONE scenario together, with one person sharing their screen:
```bash
sudo python3 experiments/run_experiment.py --scenario baseline
```
Then `congested_prio`. Anything broken goes to the owner:

| Symptom | Owner |
|---|---|
| clients cannot register in Mininet | Lead 3 (network/controller), then Lead 1 |
| `lost` high even in baseline | Lead 3 (queues) |
| wrong latency numbers / empty summary | Lead 4 |
| client crash | Lead 2 |

**Final (~8 h): "freeze"** - run `sudo bash experiments/run_all.sh`, keep the results, tag the repo: `git tag final`.

## Step 3 - Keep a bug log (ongoing)
A simple table in your notes: time, who found it, what, who fixed it, fixed? It goes into the report ("Testing and issues") and impresses examiners.

## Step 4 - Write the report (start at C1, finish after the experiments)
Use `docs/REPORT_TEMPLATE.md` - it has draft text for each section; replace the `<...>` parts with your real numbers and screenshots.
Collect from the others:
- Lead 1: packet format table, how registration works
- Lead 2: loss handling explanation, the lost-vs-loss-rate observation
- Lead 3: topology diagram, `dump-flows` and `queue` screenshots
- Lead 4: `results_table.md` and the 4 PNGs

## Step 5 - Demo script (rehearse twice, 10 minutes)
1. (1 min) Show the topology diagram and say what the project does.
2. (2 min) Terminal 1: `PRIORITY=on ryu-manager sdn/controller.py`. Terminal 2: `sudo python3 sdn/topology.py`. `mininet> pingall`.
3. (2 min) Start server + 3 clients in Mininet (commands in `docs/LEAD3_SDN.md` Step 3). Show registration and the counters.
4. (2 min) Start 15 Mbps noise. Show `dump-flows s1` (the game rule) and that the game still works.
5. (2 min) Show the 4 graphs and `results_table.md`: baseline vs congestion vs congestion + priority.
6. (1 min) Conclusion + one limitation.
**Record a backup screen video the day before.** Live demos fail; a video saves you.

## Step 6 - Fresh-clone test (the last thing before submission)
```bash
cd /tmp && git clone <repo> fresh && cd fresh
python3 -m unittest discover -s tests -v
```
Follow the README on that clean copy. Whatever fails, fix in the README.

## You are DONE when
- [ ] all branches merged, `main` runs from a fresh clone
- [ ] tests pass
- [ ] the report has: architecture, packet format, UDP design, SDN design, setup, results with all graphs, limitations
- [ ] demo rehearsed twice + backup video recorded
- [ ] every team member answered their viva questions to you without notes (you are the examiner)

---

## LLM prompt pack (paste PROJECT CONTEXT from README.md first)

**P1 - Whole-project explanation**
> Explain my whole project to me in simple terms: what each of the five components does, what data flows between them, and why UDP + SDN priority
> is a good fit for game traffic. Then draw a text architecture diagram. I must present this to my class.

**P2 - Write a report section**
> Write the "<section name, e.g. Packet design>" section of my project report. Use this information: ```<paste facts from the others / README>```.
> Style: clear academic English for a university networking course, 250-350 words, no marketing language, and do not invent numbers.

**P3 - Review the report**
> Here is my report draft: ```<paste>```. Review it like a strict examiner: list missing items against this project requirement list (UDP updates, registration of multiple
> players, sequence numbers, packet loss handling, traffic prioritization, latency, jitter, congestion test), unclear explanations, and any claim not backed by data.

**P4 - Examiner mode for the team**
> Act as an examiner for this project. Ask the team 15 questions, one at a time, covering UDP vs TCP, sequence numbers, packet loss handling, SDN and OpenFlow,
> the controller logic, queues, latency/jitter/loss measurement, and project limitations. After each answer, rate it 1-5 and give the ideal answer.

**P5 - Merge conflict / git help**
> I have this git problem: ```<paste error / git status output>```. We are 5 students with branches lead1-server, lead2-client, lead3-sdn, lead4-metrics, and main.
> Tell me exact commands to resolve it without losing anyone's work.

**P6 - Demo script**
> Turn this demo outline into a speaking script for a 10-minute presentation with exact words for each step and what to point at on screen: ```<paste Step 5>```.

---

## Common problems
| Problem | Fix |
|---|---|
| someone's part is late | reassign: whoever finishes first pairs with them; Lead 3 is the usual bottleneck |
| Mininet on someone's laptop fails | one machine runs the experiments, others send their branch to that machine |
| merge conflicts | rarely happen if everyone only edits their own files; if they do, sit together and resolve |
| results look too perfect / identical | the priority switch is not working; ask Lead 3 for `dump-flows` and queue stats |

## Viva questions (you ask the team; be strict)
1. Why UDP? 2. What do sequence numbers give you? 3. What happens when a packet is lost? 4. What is SDN, and where is the SDN in your project?
5. How does the controller recognise game traffic? 6. Why do you need a congested link to show priority? 7. How are latency, jitter and loss computed?
8. What did the graphs show? 9. What would you improve with more time (retransmission of important events, per-flow bandwidth meters, more players, a real network)?
