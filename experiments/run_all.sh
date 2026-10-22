#!/bin/bash
# Runs every scenario, then makes the graphs.   Usage: sudo bash experiments/run_all.sh [ryu|none]
CTRL=${1:-ryu}
cd "$(dirname "$0")/.."
for s in baseline congested_noprio congested_prio loss5; do
    echo "================ $s ================"
    python3 experiments/run_experiment.py --scenario $s --controller $CTRL
done
python3 metrics/plot.py
echo "All done. Graphs and results_table.md are in results/"
