# ps3recomp-lbp2

Work in progress: a static recompilation of **LittleBigPlanet 2** (BCUS98245, USA) with
[ps3recomp](https://github.com/sp00nznet/ps3recomp), built against the
[`lbp2-fixes` branch of the zeropaulsy fork](https://github.com/zeropaulsy/ps3recomp/tree/lbp2-fixes).

**This repository contains no game code or data.** The lifted C/C++ (generated from the
game's executable), the SPU images and job modules, the disc contents, keys and saves are all
excluded (`.gitignore` is a whitelist). You need your own copy of the game, and you have to
decrypt and lift it yourself.

## Status

- Boots through all 73 init steps, plays the intro movie and runs the opening credits level
  indefinitely (6-minute runs).
- The Vulkan build renders that level correctly with the game's own shaders. Known problems:
  white patches during the level intro (~110 s), the final image is shrunk to 0.875 of the
  frame, and it runs at ~7 frames/s (~11.5 headless with `LBP2_NO_RASTER=1`).
- No audio by design in these scripts (see "Running").

## What is here

| Path | What |
|------|------|
| `project/` | The game project: `CMakeLists.txt`, `main.cpp`, `stubs.cpp`, and `lbp2_local.cpp` (game-specific shims: offline `cellNetCtlGetState`, a UDP loopback for the game's party code, init-step logging, `LBP2_NO_RASTER`, `LBP2_CRASH_BT`) |
| `env.sh` | Workspace paths and the runtime settings LBP2 needs; sourced by the scripts |
| `run.sh` | Silent launcher: `./run.sh <seconds> [label]`, log in `runs/` |
| `run_frames.sh` | Same, saving a Vulkan frame every 5 s: `./run_frames.sh <seconds> <label> <new-dir>` |
| `patch_stubs.py` | Post-lift fix for import stubs (see below) |
| `gdb/` | `run_gdb.sh <seconds> <absolute script> <label>` and the probe scripts used during bring-up |
| `tools/` | Small ELF helpers: `ppc_view.py ADDR:N`, `callers.py ADDR`, `tocref.py`, `opd.py`, `str.py` (need `capstone`) |

## Building

1. **Get the runtime.** Clone the fork's branch next to this repository:
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
6. **Configure and build** (the lifted files are large: keep the job count low, about 1.5 GB
   of RAM per job):
   ```
   cmake -S project -B build -G Ninja -DPS3RECOMP_DIR=$PWD/ps3recomp \
         -DRECOMP_DIR=$PWD/recompiled -DSPU_DIR=$PWD/spu
   ninja -C build -j3
   ```
   Add `-DPS3RECOMP_RSX_VULKAN=ON` (in a second build directory, e.g. `build-vk`) for real
   pixels; it needs glslang. The default build uses the headless null renderer.

## Running

Always through `run.sh` or `gdb/run_gdb.sh`. Both force SDL's dummy audio driver, make the
PulseAudio/PipeWire/JACK servers unreachable, and kill the game if it opens an audio device.
Any new launcher should do the same.

```
./run.sh 200 test                                            # headless, 200 s
BIN=$PWD/build-vk/lbp2_recomp ./run_frames.sh 200 vk frames-1 # Vulkan, a frame every 5 s
```

Progress shows in the log as `[lbp2-local] t=Ns flips=N` and `init at: step N`.

### Runtime settings

`env.sh` sets these by default (set one before calling to change it, or
`LBP2_NO_DEFAULT_ENV=1` to skip them all):

| Variable | Why |
|----------|-----|
| `PAD_SCRIPT=25:0x4000,30:0x4000,35:0x4000` | Presses Cross for the game's two boot prompts |
| `SPU_INTERP_UNLIFTED=1` | Interprets SPU code loaded at run time (the FMOD mixer's DSP plugins) |
| `SPU_DMA_REPEAT_EXEMPT=8` | SPU image 8 waits on a control block between frames; the repeat watchdog must not halt it |
| `SPU_WWS_PM_IMAGE=1` | The `Wws_Job` policy module is image 1 here, so job modules dispatch to lifted code |
| `GCM_USER_QUEUE=1` | Delivers every GCM user command; the game releases a job-list gate per command |
| `GCM_FIFO_SEGMENT=0x8000` | 32 KB command-ring segments, as the SDK's default context; avoids a deadlock with the next setting |
| `GCM_SEMA_ACQUIRE=1`, `GCM_SEMA_ACQUIRE_MS=2000` | The RSX waits for labels the SPU jobs write; without it frames show 128x128 blocks of older frames |
| `CELL_FIBER_RUN_RETURNS=1` | `cellFiberPpuRunFibers` returns when nothing is runnable; the game signals its fibers after it returns |
| `PS3RECOMP_VK_GUEST_PROGRAMS=1` | Vulkan build: use the game's shaders |

Useful extras: `LBP2_NO_RASTER=1` (headless build without the software rasterizer, much
faster), `GCM_SEMA_STATS=1`, `VK_BLACK_STATS=1`, `RSX_PRESENT_LOG=1`, `LBP2_CRASH_BT=1`.

## Credits

ps3recomp by sp00nznet and contributors. LittleBigPlanet is a trademark of Sony Interactive
Entertainment; this project is not affiliated with or endorsed by Sony or Media Molecule.
