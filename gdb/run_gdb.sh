#!/bin/bash
# silent gdb launcher: same audio lockout and private dirs as run.sh, plus its audio watchdog.
# usage: run_gdb.sh <seconds> <gdb-script> <label>
. "$(dirname "${BASH_SOURCE[0]}")/../env.sh"   # sets W, LBP2_ELF and the game's runtime settings
export SDL_AUDIODRIVER=dummy
export PULSE_SERVER=unix:/nonexistent/pulse PIPEWIRE_REMOTE=/nonexistent/pipewire ALSA_CONFIG_PATH=/dev/null JACK_NO_START_SERVER=1
export XDG_RUNTIME_DIR=$W/empty-xdg
export PS3_VFS_ROOT=$W/game PS3_HDD0_ROOT=$W/hdd0 PS3_HDD1_ROOT=$W/hdd1 PS3_DEV_FLASH=$W/dev_flash
export PS3_TITLE=lbp2-recomp
mkdir -p "$W/runs" "$W/empty-xdg"; cd "$W/runs" || exit 1
LOG=$W/runs/$(date +%H%M%S)-$3.log
timeout -s KILL $1 gdb -q -batch -x "$2" --args "${BIN:-$W/build/lbp2_recomp}" "$LBP2_ELF" > "$LOG" 2>&1 &
TP=$!
[ -n "$SNAP" ] && ( for i in $(seq 1 ${SNAPS:-1}); do sleep "$SNAP"; P=$(pgrep -x lbp2_recomp); echo "=== IO t=$((i*SNAP)) $(grep -E 'rchar|read_bytes' /proc/$P/io 2>/dev/null | tr '\n' ' ')" >> "$LOG"; pkill -INT -x lbp2_recomp; done ) &
WHY=done
while kill -0 $TP 2>/dev/null; do
  for P in $(pgrep -x lbp2_recomp); do
    if ls -l /proc/$P/fd 2>/dev/null | grep -q '/dev/snd'; then WHY=AUDIO_DEVICE_OPENED; kill -9 $P; pkill -9 -x gdb; fi
    if ss -xpn 2>/dev/null | grep "pid=$P," | grep -qE 'pulse/native|pipewire-0'; then WHY=AUDIO_SERVER_CONNECTED; kill -9 $P; pkill -9 -x gdb; fi
    RSS=$(awk '/VmRSS/{print $2}' /proc/$P/status 2>/dev/null); if [ "${RSS:-0}" -gt 9000000 ]; then WHY=RSS_LIMIT; kill -9 $P; fi
  done
  sleep 0.5
done
wait $TP; echo "rc=$? why=$WHY log=$LOG"
