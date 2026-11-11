# Sourced by run.sh, run_frames.sh and gdb/run_gdb.sh. Not meant to be run on its own.
#
# W is this checkout. Machine-specific settings go in local.env next to this file
# (not tracked), for example:
#   LBP2_ELF=/path/to/your/decrypted/EBOOT.elf
#   BIN=/path/to/build-vk/lbp2_recomp
W=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
[ -f "$W/local.env" ] && . "$W/local.env"
: "${LBP2_ELF:=$W/lbp2.elf}"
export LBP2_WORKSPACE="$W" LBP2_ELF

# The runtime settings LBP2 needs (ps3recomp fork, branch lbp2-fixes). Each one is
# only a default: set a variable before calling to change it, or to empty to unset
# its effect where the runtime treats empty as off. LBP2_NO_DEFAULT_ENV=1 skips all.
# What each does: README.md, "Runtime settings".
if [ -z "$LBP2_NO_DEFAULT_ENV" ]; then
  : "${PAD_SCRIPT=25:0x4000,30:0x4000,35:0x4000}"  # Cross at 25/30/35 s: the boot prompts
  : "${SPU_INTERP_UNLIFTED=1}"         # interpret runtime-loaded SPU code (FMOD DSP plugins)
  : "${SPU_DMA_REPEAT_EXEMPT=8}"       # never let the repeat watchdog halt SPU image 8
  : "${SPU_WWS_PM_IMAGE=1}"            # the Wws_Job policy module is SPU image 1 in LBP2
  : "${GCM_USER_QUEUE=1}"              # deliver every GCM user command (job-list gates)
  : "${GCM_FIFO_SEGMENT=0x8000}"       # 32 KB command-ring segments, as the SDK's default context
  : "${GCM_SEMA_ACQUIRE=1}"            # the RSX waits on semaphore acquires (SPU-written labels)
  : "${GCM_SEMA_ACQUIRE_MS=2000}"      # ... but gives up after 2 s
  : "${CELL_FIBER_RUN_RETURNS=1}"      # cellFiberPpuRunFibers returns when nothing is runnable
  : "${PS3RECOMP_VK_GUEST_PROGRAMS=1}" # Vulkan build: run the game's own shaders
  export PAD_SCRIPT SPU_INTERP_UNLIFTED SPU_DMA_REPEAT_EXEMPT SPU_WWS_PM_IMAGE GCM_USER_QUEUE \
         GCM_FIFO_SEGMENT GCM_SEMA_ACQUIRE GCM_SEMA_ACQUIRE_MS CELL_FIBER_RUN_RETURNS \
         PS3RECOMP_VK_GUEST_PROGRAMS
fi
