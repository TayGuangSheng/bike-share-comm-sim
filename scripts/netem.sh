#!/usr/bin/env bash
# ./netem.sh add 100ms 10%   # impair loopback
# ./netem.sh clear
set -euo pipefail
cmd=${1:-help}; delay=${2:-100ms}; loss=${3:-5%}
if [ "$cmd" = "add" ]; then
  sudo tc qdisc add dev lo root netem delay $delay loss $loss
  echo "Added netem on lo: delay=$delay loss=$loss"
elif [ "$cmd" = "change" ]; then
  sudo tc qdisc change dev lo root netem delay $delay loss $loss
  echo "Changed netem on lo: delay=$delay loss=$loss"
elif [ "$cmd" = "clear" ]; then
  sudo tc qdisc del dev lo root || true
  echo "Cleared netem on lo"
else
  echo "Usage: $0 add|change|clear [delay] [loss]"
fi
