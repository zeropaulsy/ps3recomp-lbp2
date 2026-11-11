#!/bin/bash
# Run the LBP2 recomp silently, in private directories. usage: run.sh <seconds> [label]
# BIN=<path> runs another build of the same game (e.g. build-vk/lbp2_recomp, the Vulkan backend).
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"   # sets W, LBP2_ELF and the game's runtime settings
SECS=${1:-120}; LABEL=${2:-run}; LOG=$W/runs/$(date +%H%M%S)-$LABEL.log
# Audio: SDL's dummy driver, and every real sound server made unreachable.
export SDL_AUDIODRIVER=dummy
export PULSE_SERVER=unix:/nonexistent/pulse PIPEWIRE_REMOTE=/nonexistent/pipewire ALSA_CONFIG_PATH=/dev/null JACK_NO_START_SERVER=1
export XDG_RUNTIME_DIR=$W/empty-xdg
export PS3_VFS_ROOT=$W/game PS3_HDD0_ROOT=$W/hdd0 PS3_HDD1_ROOT=$W/hdd1 PS3_DEV_FLASH=$W/dev_flash
export PS3_TITLE=lbp2-recomp
mkdir -p "$W/runs" "$W/empty-xdg"; cd "$W/runs" || exit 1
"${BIN:-$W/build/lbp2_recomp}" "$LBP2_ELF" > "$LOG" 2>&1 &
PID=$!
START=$SECONDS; MAXRSS=0; WHY=timeout
while kill -0 $PID 2>/dev/null; do
  if ls -l /proc/$PID/fd 2>/dev/null | grep -q '/dev/snd'; then WHY=AUDIO_DEVICE_OPENED; kill -9 $PID; break; fi
  if ss -xpn 2>/dev/null | grep "pid=$PID," | grep -qE 'pulse/native|pipewire-0'; then WHY=AUDIO_SERVER_CONNECTED; kill -9 $PID; break; fi
  RSS=$(awk '/VmRSS/{print $2}' /proc/$PID/status 2>/dev/null); RSS=${RSS:-0}; [ "$RSS" -gt "$MAXRSS" ] && MAXRSS=$RSS
  if [ "$RSS" -gt 9000000 ]; then WHY=RSS_LIMIT; kill -9 $PID; break; fi
  if [ $((SECONDS-START)) -ge "$SECS" ]; then kill -9 $PID; break; fi
  sleep 0.5
done
wait $PID 2>/dev/null; RC=$?
[ $((SECONDS-START)) -lt "$SECS" ] && [ "$WHY" = timeout ] && WHY=exited
echo "=== end: why=$WHY rc=$RC elapsed=$((SECONDS-START))s maxrss_kb=$MAXRSS log=$LOG" | tee -a "$LOG"
