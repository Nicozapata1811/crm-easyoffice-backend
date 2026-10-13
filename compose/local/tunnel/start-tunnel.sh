#!/bin/sh
# Runs a cloudflared quick tunnel and exits when it loses its connection, so
# "restart: unless-stopped" brings up a new tunnel. Quick tunnels expire after
# a day or two and cloudflared keeps retrying the dead one forever.
set -u

ORIGIN="${1:?usage: start-tunnel <origin url>}"
CHECK_EVERY=10
MAX_FAILURES=6
STARTUP_GRACE=60

# A plain sleep would delay the stop signal until it ends.
nap() { sleep "$1" & wait $!; }

cloudflared tunnel --no-autoupdate --metrics 0.0.0.0:2000 --url "$ORIGIN" &
PID=$!
trap 'kill "$PID" 2>/dev/null' TERM INT

nap "$STARTUP_GRACE"
failures=0
while kill -0 "$PID" 2>/dev/null; do
  if wget -q -T 3 -O /dev/null http://localhost:2000/ready; then
    failures=0
  else
    failures=$((failures + 1))
    echo "tunnel not ready ($failures/$MAX_FAILURES)"
    if [ "$failures" -ge "$MAX_FAILURES" ]; then
      echo "tunnel lost its connection; exiting so it is restarted with a new one"
      kill "$PID" 2>/dev/null
      exit 1
    fi
  fi
  nap "$CHECK_EVERY"
done
wait "$PID"
