#!/bin/bash
# Final check before submission: clone the repo into a clean folder and make sure it works from scratch.
# Usage:  bash scripts/fresh_clone_check.sh [repo-url]
REPO=${1:-https://github.com/likixv2/game-net.git}
TMP=$(mktemp -d)
FAIL=0
bad() { echo "  FAIL: $1"; FAIL=1; }
ok()  { echo "  ok:   $1"; }

echo "Cloning $REPO into $TMP ..."
git clone -q "$REPO" "$TMP/game-net" || { echo "clone failed"; exit 1; }
cd "$TMP/game-net" || exit 1

echo "1. required files"
for f in README.md common/packet.py server/server.py client/client.py sdn/controller.py sdn/policy.py sdn/topology.py \
         tools/noise.py metrics/analyze.py metrics/plot.py experiments/run_experiment.py experiments/run_all.sh \
         tests/test_protocol.py tests/test_dynamic_sdn.py docs/DOCUMENTATION.md docs/LEAD1_SERVER.md docs/LEAD2_CLIENT.md docs/LEAD3_SDN.md \
         docs/LEAD4_MEASUREMENT.md docs/LEAD5_INTEGRATION.md; do
    [ -f "$f" ] && ok "$f" || bad "missing $f"
done

echo "2. nothing junk committed"
if git ls-files | grep -qE '__pycache__|\.pyc$|\.DS_Store'; then bad "cache or system files are committed"; else ok "no __pycache__ / .pyc / .DS_Store"; fi

echo "3. Python files compile"
if python3 -I -m py_compile common/packet.py server/server.py client/client.py tools/noise.py \
        metrics/analyze.py metrics/plot.py experiments/run_experiment.py sdn/controller.py sdn/policy.py sdn/topology.py 2>/dev/null; then
    ok "all compile"
else
    bad "a Python file has a syntax error"
fi

echo "4. automated tests (about 10 seconds)"
OUT=$(python3 -W ignore -m unittest discover -s tests 2>&1)
if echo "$OUT" | tail -3 | grep -q "^OK"; then ok "all tests pass"; else bad "tests failed"; echo "$OUT" | tail -15; fi

echo "5. short local game run + analyzer"
mkdir -p results/check
python3 server/server.py --port 5099 --log results/check/server_log.csv --duration 9 >/dev/null 2>&1 &
sleep 0.7
python3 client/client.py --server-port 5099 --name c1 --duration 5 --logdir results/check >/dev/null 2>&1 &
python3 client/client.py --server-port 5099 --name c2 --duration 5 --logdir results/check >/dev/null 2>&1 &
wait
if python3 metrics/analyze.py results/check 2>&1 | grep -q "loss (%)"; then ok "analyzer printed latency, jitter and loss"; else bad "analyzer produced no table"; fi

echo
[ $FAIL -eq 0 ] && echo "ALL CHECKS PASSED: safe to submit." || echo "SOME CHECKS FAILED: fix them before submitting."
rm -rf "$TMP"
exit $FAIL
