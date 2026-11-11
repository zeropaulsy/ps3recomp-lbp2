#!/bin/bash
# Run a build through run.sh (silent) while saving a frame every few seconds.
# usage: run_frames.sh <seconds> <label> <frames-dir>   (env passes through to run.sh)
# Needs the Vulkan build (BIN=.../build-vk/lbp2_recomp). The dir must not exist yet; nothing is deleted.
W=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SECS=$1; LABEL=$2; D=$3
[ -n "$SECS" ] && [ -n "$LABEL" ] && [ -n "$D" ] || { echo "usage: $0 <seconds> <label> <frames-dir>"; exit 1; }
[ -e "$D" ] && { echo "$D exists; pick a new directory"; exit 1; }
mkdir -p "$D" || exit 1
export PS3RECOMP_VK_DUMP="$D/cur.ppm"
export PS3RECOMP_VK_DUMP_EVERY=${PS3RECOMP_VK_DUMP_EVERY:-30}
(
  for i in $(seq 5 5 "$SECS"); do
    sleep 5
    [ -f "$D/cur.ppm" ] && cp "$D/cur.ppm" "$D/t$(printf %03d "$i").ppm"
  done
) &
COPIER=$!
"$W/run.sh" "$SECS" "$LABEL"
kill "$COPIER" 2>/dev/null
wait 2>/dev/null
echo "frames in $D"
