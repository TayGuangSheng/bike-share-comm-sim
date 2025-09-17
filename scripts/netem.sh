#!/usr/bin/env bash
set -e
DEV=lo
case "$1" in
  add) sudo tc qdisc add dev "$DEV" root netem delay "${2:-150ms}" loss "${3:-3%}" ;;
  change) sudo tc qdisc change dev "$DEV" root netem delay "${2:-150ms}" loss "${3:-3%}" ;;
  delete|del|clear) sudo tc qdisc del dev "$DEV" root || true ;;
  show) tc qdisc show dev "$DEV" ;;
  *) echo "Usage: $0 {add|change|delete|show} [delay] [loss]" ;;
esac
