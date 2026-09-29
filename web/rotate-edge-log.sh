#!/bin/sh
# Keeps the monitor's access log (/var/log/grs/edge.json) under 20 MB: every 5 minutes, if it
# is larger, move it aside (one old copy) and have Nginx reopen its logs. The monitor notices
# the new file and follows it. Run in the background by the image's entrypoint.
LOG=/var/log/grs/edge.json
(
  while sleep 300; do
    if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 20000000 ]; then
      mv -f "$LOG" "$LOG.1" && nginx -s reopen
    fi
  done
) &
