# ps3recomp-lbp2

Work in progress: a static recompilation of **LittleBigPlanet 2** (BCUS98245, USA) with
[ps3recomp](https://github.com/sp00nznet/ps3recomp), built against the
[`lbp2-fixes` branch of the zeropaulsy fork](https://github.com/zeropaulsy/ps3recomp/tree/lbp2-fixes).

**This repository contains no game code or data.** The lifted C/C++ (generated from the
game's executable), the SPU images and job modules, the disc contents, keys and saves are all
excluded (`.gitignore` is a whitelist). You need your own copy of the game, and you have to
decrypt and lift it yourself.

## Status

As of 2026-11-21:

- **Boots reliably** through all 73 init steps (about 5 s), skips the intro movie, and reaches the
  opening credits level at about 40 s. The level can be walked through with scripted controller
  input; the cutscene after it plays, and the next level (Avalon) loads.
- **Renders correctly with the game's own shaders** (Vulkan build), in a window or headless.
- **Speed:** the level runs at the game's own 30 fps cap. Without the cap it does about 39-41 fps
  standing and 36-38 fps walking. The in-engine cutscene after the credits course is the slow part
  (20-23 fps). The limit is the game's SPU job code (translated to native code, but the job lane
  the main thread waits on needs about 16 ms per frame while walking and 35 ms in that cutscene).
- **Audio works internally:** the FMOD mixer and all its codec/effect plugins run as translated code
  and keep up in real time. These scripts never play it (see "Running").
- **Known problems:**
  - An occasional long frame remains (one or two a minute, 100-150 ms), and about 3 frames a
    second take 40-100 ms instead of 33.
  - MLAA anti-aliasing is off by default for speed (`LBP2_NO_MLAA=1`), which also removes the
    glow halo.
  - A 7-pixel black band at the top and bottom of the frame (in the game's scene image; source
    unchecked). The larger black bars on all four sides (the image drawn at 0.877 of the frame)
    are fixed by `LBP2_SCREEN_SIZE`, see "Runtime settings".
  - The transition into the second level (Avalon) froze once in five runs (the RSX gave up
    waiting on a label the SPU jobs write, then the SPU job lanes were halted by the runtime's
    repeat watchdog). Not reproduced since.
  - Online features are stubbed (offline only).
  - A hard reset of the PC while the game runs can damage its HDD cache
    (`hdd1/cache/BCUS98245/output/temp`); the game then exits with a libpng `incorrect data check` at
    about 43 s. `python3 tools/cachecheck.py` finds the damaged entry; move the file away and the game
    rebuilds it.

<img width="1298" height="788" alt="Screenshot From 2026-11-20 23-39-54" src="https://github.com/user-attachments/assets/a285ddb2-d859-4ea4-8455-0fac7229eb04" />

## What is here

| Path | What |
|------|------|
| `project/` | The game project: `CMakeLists.txt`, `main.cpp`, `stubs.cpp`, and `lbp2_local.cpp` (game-specific shims: offline `cellNetCtlGetState`, a UDP loopback for the game's party code, intro skip, MLAA skip, the Screen Size option (`LBP2_SCREEN_SIZE`), registration of the FMOD plugins as relocatable SPU code, init-step logging and stall dumps, `LBP2_NO_RASTER`, `LBP2_CRASH_BT`) |
| `env.sh` | Workspace paths and the runtime settings LBP2 needs; sourced by the scripts |
| `run.sh` | Silent launcher: `./run.sh <seconds> [label]`, log in `runs/` (or in `$LBP2_RUNS_DIR`) |
| `run_frames.sh` | Same, saving a Vulkan frame every 5 s: `./run_frames.sh <seconds> <label> <new-dir>` |
| `patch_stubs.py` | Post-lift fix for import stubs (see below) |
| `gdb/` | `run_gdb.sh <seconds> <absolute script> <label>` and the probe scripts used during bring-up |
| `tools/` | Small ELF helpers: `ppc_view.py ADDR:N`, `callers.py ADDR`, `tocref.py`, `opd.py`, `str.py` (need `capstone`); `cachecheck.py` checks the PNGs in the game's HDD cache |

## Building

1. **Get the runtime.** Clone the fork's branch into this checkout (it is ignored by git):
   ```
   git clone -b lbp2-fixes https://github.com/zeropaulsy/ps3recomp.git ps3recomp
   ```
2. **Decrypt the game's `EBOOT.BIN`** to an ELF with your own tools and keys, and put its path
   in `local.env`: `LBP2_ELF=/path/to/lbp2.elf`.
3. **Extract the disc** into `game/` by its Joliet names (the ISO9660 tree is upper-case and
   truncates long names), so that `game/PS3_GAME/USRDIR/...` exists. `data.sdat` must also be
   decrypted to `game/PS3_GAME/USRDIR/data.sdat.dec` for the SPU job modules.
4. **Lift the PPU code** into `recompiled/`:
   ```
   python3 ps3recomp/tools/ppu_loader.py "$LBP2_ELF" -o out/
   python3 ps3recomp/tools/ppu_lifter.py "$LBP2_ELF" --functions out/lbp2.functions.json \
       --hle-stubs out/lbp2.imports.json --output recompiled/
   python3 patch_stubs.py
   ```
   `patch_stubs.py` makes every import stub save r2 the way the real stub does (the runtime's
   fast HLE path returns before restoring it, and LBP2 uses three TOCs). Run it after every lift.
5. **Lift the SPU code** into `spu/`: the embedded SPU images (`extract_spu_images.py`,
   `spu_lifter.py`, `build_spu_workloads.py`), the raw `Wws_Job` policy module (ELF offset
   0xC26F80, 12160 bytes; not an ELF, so it is wrapped at LS 0xA00 and lifted with
   `--extra-funcs pm_wwsjob=0xA2C`), and the 100 job modules from `data.sdat.dec`
   (`extract_jobmods.py --usrdir game/PS3_GAME/USRDIR --sdat data.sdat.dec`, then
   `lift_jobmods.py --jobmods spu/jobmods --out spu --register spu/jobmods_register.c
   --symbol-prefix lbp2`). This step is not scripted yet; the commands are what the bring-up
   used and may need adjusting.
   The FMOD mixer copies its 26 plugin images (`spu_0000`-`spu_0004` and `spu_0008`-`spu_0028`)
   to its own choice of LS address, so those must be lifted position-independent, one by one:
   ```
   python3 ps3recomp/tools/spu_lifter.py spu/images/<img>.elf --auto-functions spu/images/<img>.elf \
       --symbol-prefix <img>_ -o spu/<img> --reloc
   ```
   `build_spu_workloads.py --relift` lifts them without `--reloc`; redo these afterwards. Without
   it they run in the SPU interpreter, the mixer falls behind, frames stall and the audio drops out.
6. **Configure and build** (the lifted files are large: keep the job count low, about 1.5 GB
   of RAM per job):
   ```
   cmake -S project -B build -G Ninja
   ninja -C build -j3
   ```
   Add `-DPS3RECOMP_RSX_VULKAN=ON` (in a second build directory, e.g. `build-vk`) for real
   pixels; it needs glslang. The default build uses the headless null renderer.
   `-DPS3RECOMP_DIR=`, `-DRECOMP_DIR=` and `-DSPU_DIR=` point elsewhere if your layout differs.
   The lifted SPU code is built with `-mavx2` (and `-mfma` if present) when the configuring
   machine has AVX2 (faster SPU float ops); the binary then needs the same CPU features.
   `-DLBP2_SPU_AVX2=OFF` builds one without them, `-DLBP2_SPU_FMA=OFF` drops only `-mfma`.
   The lifted SPU code is also built with `-fcf-protection=none` (no `endbr64` at the start of
   every function, about 0.6% faster job code); the binary then loses its IBT/shadow-stack marking.
   `-DLBP2_SPU_CF_PROTECTION=ON` keeps the compiler's default.

## Running

Always through `run.sh` or `gdb/run_gdb.sh`. Both force SDL's dummy audio driver, make the
PulseAudio/PipeWire/JACK servers unreachable, and kill the game if it opens an audio device.
Any new launcher should do the same.

```
./run.sh 200 test                                            # headless, 200 s
BIN=$PWD/build-vk/lbp2_recomp ./run_frames.sh 200 vk frames-1 # Vulkan, a frame every 5 s
```

Add `PS3RECOMP_VK_WINDOW=1` to the Vulkan build to watch it in a window (F11 for fullscreen,
Esc quits). Controller input is scripted: `PAD_SCRIPT=<sec>:<buttons>,...` presses buttons and
`PAD_STICK` moves the left stick (format in the runtime's `libs/input/cellPad.c`).

Progress shows in the log as `[lbp2-local] t=Ns flips=N` and `init at: step N`.

`LBP2_RUNS_DIR=<dir>` puts the log somewhere else (the game's working directory stays `runs/`).
The game logs a lot (over 100 MB in a few minutes with some debug settings); on a slow or nearly
full disk the writes stall the game for seconds at a time, so for timing runs use a RAM disk such
as `LBP2_RUNS_DIR=/dev/shm/lbp2-runs`.

### Runtime settings

`env.sh` sets these by default (set one before calling to change it, or
`LBP2_NO_DEFAULT_ENV=1` to skip them all):

| Variable | Why |
|----------|-----|
| `PAD_SCRIPT=25:0x4000,30:0x4000,35:0x4000` | Presses Cross for the game's two boot prompts |
| `LBP2_SKIP_INTRO=1` | Pulses START from 38 s until the level starts, which skips the intro movie (never pauses the level) |
| `LBP2_NO_MLAA=1` | Skips the Edge MLAA SPU pass: ~+20% fps, but no anti-aliasing and no glow halo. `LBP2_NO_MLAA=0` turns MLAA back on |
| `LBP2_NO_RASTER=1` | Headless build only: skips the null backend's CPU rasterizer, whose output nobody sees (much faster). `LBP2_NO_RASTER=0` keeps it |
| `LBP2_FIFO_SPIN_MAX=4` | Caps the game's RSX-backlog spin, which otherwise freezes ~0.5 s when the RSX has caught up (most often with `LBP2_NO_MLAA=1`) |
| `LBP2_RSX_POLL_US=250` | The RSX thread sleeps 250 us between FIFO passes instead of 4 ms (range 50..4000); ~+11% fps walking the level |
| `SPU_FLOAT_RZ=1` | Runs SPU code with the host in round-toward-zero, flush-to-zero mode, so single-precision SPU float ops are one native op each (same bits as the exact forms; ~+16% fps in levels) |
| `SPU_INTERP_UNLIFTED=1` | Interprets SPU code loaded at run time that has no translation (the FMOD plugins have one, see "Building" step 5) |
| `SPU_DMA_REPEAT_EXEMPT=8` | SPU image 8 waits on a control block between frames; the repeat watchdog must not halt it |
| `SPU_WWS_PM_IMAGE=1` | The `Wws_Job` policy module is image 1 here, so job modules dispatch to lifted code |
| `GCM_USER_QUEUE=1` | Delivers every GCM user command; the game releases a job-list gate per command |
| `GCM_FIFO_SEGMENT=0x8000` | 32 KB command-ring segments, as the SDK's default context; avoids a deadlock with the next setting |
| `GCM_SEMA_ACQUIRE=1`, `GCM_SEMA_ACQUIRE_MS=2000` | The RSX waits for labels the SPU jobs write; without it frames show 128x128 blocks of older frames |
| `CELL_FIBER_RUN_RETURNS=1` | `cellFiberPpuRunFibers` returns when nothing is runnable; the game signals its fibers after it returns |
| `PS3RECOMP_VK_GUEST_PROGRAMS=1` | Vulkan build: use the game's shaders |
| `SPU_MFC_LOOKUP_CACHE=1` | Per-thread cache of the SPU MFC engine lookup; about 19% faster in levels |
| `VK_DRAW_BATCH=1` | Vulkan build: records draws, uploads and clears into one GPU submission instead of waiting for the GPU after each draw; about 7.9 -> 12.3 fps in levels |

Not set by `env.sh` (the defaults below are built in):

| Variable | Why |
|----------|-----|
| `LBP2_SCREEN_SIZE=0.5` (default) | The game's Screen Size display option. The final image is scaled by 1.3^(size - 0.5), so 0.5 fills the frame exactly. The game starts new profiles at 0 (black bars on all four sides) and saves that, so this value replaces it at boot and when the saved profile is applied. The in-game slider still works until the next boot. `LBP2_SCREEN_SIZE=game` keeps the game's own value |
| `LBP2_VBLANK_MS=16` (default) | Period of the emulated vblank in ms (project/main.cpp). The game flips every second vblank, so the frame cap is 1000 / (2 * period): 16 gives 31.25 fps, `16.667` gives 30.0 fps as on hardware (fractions are accepted). Smaller values are only for measuring headroom: game timing that counts vblanks runs fast |
| `PS3RECOMP_VK_PRESENT=immediate` | Vulkan window only (`fifo`, `mailbox`, `immediate`, `relaxed`; default mailbox, else fifo). This NVIDIA/XWayland setup offers no mailbox, and under fifo a hidden window, locked screen or switched-off display holds each present ~1 s, so the game runs at ~1 fps. `immediate` never waits |

Useful extras: `GCM_SEMA_STATS=1`, `VK_BLACK_STATS=1`, `RSX_PRESENT_LOG=1`, `LBP2_CRASH_BT=1`,
`SPU_XR_FIX_STATS=10` (every 10 s, the SPU float ops that needed the exact slow path, by call site).
For hunting stalls: `GCM_HITCH_MS=<n>` (frames slower than n ms), `SPU_TASK_SLOW_MS=<n>` (slow
SPURS task rounds), `LBP2_FRAME_STALL_MS=<n>` (all guest threads when a frame stalls),
`SPU_INTERP_STATS=10` (what SPU code runs interpreted).

## Credits

ps3recomp by sp00nznet and contributors. LittleBigPlanet is a trademark of Sony Interactive
Entertainment; this project is not affiliated with or endorsed by Sony or Media Molecule.
