cmake_minimum_required(VERSION 3.20)
project(lbp2_recomp
    VERSION 0.1.0
    LANGUAGES C CXX
    DESCRIPTION "Recompiled PS3 game project (ps3recomp)"
)

# ---------------------------------------------------------------------------
# Standards
# ---------------------------------------------------------------------------
set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Prefer Ninja if available
if(NOT CMAKE_GENERATOR MATCHES "Ninja" AND NOT DEFINED ENV{CMAKE_GENERATOR})
    message(STATUS "Tip: use -G Ninja for faster builds")
endif()

# ---------------------------------------------------------------------------
# The two directories this project is built from
# ---------------------------------------------------------------------------
# PS3RECOMP_DIR is the toolkit checkout: include/, runtime/, libs/, tools/.
# RECOMP_DIR is where the lifter's output for THIS game lives. They are
# separate on purpose -- a port keeps its generated code in its own tree and
# points at whatever toolkit checkout it is building against:
#
#   cmake -B build -G Ninja \
#         -DPS3RECOMP_DIR=/path/to/ps3recomp \
#         -DRECOMP_DIR=/path/to/my_game/recompiled
#
# Defaults follow this repository's layout: ps3recomp/ (the lbp2-fixes branch of
# the fork), recompiled/ and spu/ all sit next to project/.
if(NOT DEFINED PS3RECOMP_DIR)
    get_filename_component(PS3RECOMP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../ps3recomp" ABSOLUTE)
endif()
get_filename_component(PS3RECOMP_DIR "${PS3RECOMP_DIR}" ABSOLUTE)

set(RECOMP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../recompiled" CACHE PATH
    "Directory holding the lifter's output: ppu_recomp.h and the lifted sources")
get_filename_component(RECOMP_DIR "${RECOMP_DIR}" ABSOLUTE)

message(STATUS "ps3recomp SDK:   ${PS3RECOMP_DIR}")
message(STATUS "Lifted output:   ${RECOMP_DIR}")

if(NOT EXISTS "${RECOMP_DIR}/ppu_recomp.h")
    message(FATAL_ERROR
        "No ppu_recomp.h in ${RECOMP_DIR}.\n"
        "That header and the lifted sources beside it are what "
        "tools/ppu_lifter.py writes. Run the lifter, drop its output there, "
        "or point -DRECOMP_DIR= at wherever it already is.")
endif()

# The lifted translation units. A game's lift is hundreds of generated files,
# so they are globbed rather than listed; re-run CMake after a fresh lift.
file(GLOB RECOMP_SOURCES CONFIGURE_DEPENDS
    "${RECOMP_DIR}/*.c"
    "${RECOMP_DIR}/*.cpp"
)
if(NOT RECOMP_SOURCES)
    message(FATAL_ERROR
        "${RECOMP_DIR} has a ppu_recomp.h but no .c or .cpp beside it. The "
        "lifted functions and the function table live in those; without them "
        "there is nothing to run.")
endif()
list(LENGTH RECOMP_SOURCES RECOMP_SOURCE_COUNT)
message(STATUS "Lifted sources:  ${RECOMP_SOURCE_COUNT} file(s)")

# ---------------------------------------------------------------------------
# ps3recomp runtime library
# ---------------------------------------------------------------------------
# Built from source as a subdirectory rather than imported as a prebuilt
# archive. A static library carries none of its own link requirements, so an
# imported one arrives without SDL2, pthreads, the Metal frameworks or the
# Winsock/XInput imports -- the link then fails on every platform for a
# different reason. add_subdirectory hands all of that over with the target.
add_subdirectory("${PS3RECOMP_DIR}" "${CMAKE_BINARY_DIR}/ps3recomp_sdk"
                 EXCLUDE_FROM_ALL)

# ---------------------------------------------------------------------------
# The HLE NID table
# ---------------------------------------------------------------------------
# Maps each firmware import NID onto the handler in the runtime that answers
# it. A port may keep a hand-curated one beside its lift; otherwise generate
# the canonical every-module table, which is what the toolkit's own boot
# harness uses.
if(EXISTS "${RECOMP_DIR}/ppu_hle_nids.cpp")
    set(HLE_NID_TABLE "${RECOMP_DIR}/ppu_hle_nids.cpp")
    message(STATUS "HLE NID table:   ${HLE_NID_TABLE}")
else()
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    set(HLE_NID_TABLE "${CMAKE_CURRENT_BINARY_DIR}/ppu_hle_nids.cpp")
    # The generator discovers handlers from library definitions. Rebuild when
    # an existing module changes, and reconfigure when a new module is added.
    file(GLOB_RECURSE HLE_NID_SOURCES CONFIGURE_DEPENDS
        "${PS3RECOMP_DIR}/libs/*.c")
    # A removed input cannot make the output older than a remaining dependency.
    # Track the list itself so deletions also remove stale handler references.
    set(HLE_NID_SOURCE_LIST "${CMAKE_CURRENT_BINARY_DIR}/hle_nid_sources.txt")
    file(GENERATE OUTPUT "${HLE_NID_SOURCE_LIST}" CONTENT "${HLE_NID_SOURCES}\n")
    add_custom_command(
        OUTPUT "${HLE_NID_TABLE}"
        COMMAND "${Python3_EXECUTABLE}"
                "${PS3RECOMP_DIR}/tools/gen_hle_nids.py"
                --out "${HLE_NID_TABLE}" --all
        DEPENDS "${PS3RECOMP_DIR}/tools/gen_hle_nids.py"
                "${PS3RECOMP_DIR}/tools/nid_database.py"
                ${HLE_NID_SOURCES} "${HLE_NID_SOURCE_LIST}"
        COMMENT "Generating the HLE NID -> handler table")
    message(STATUS "HLE NID table:   generated (every module)")
endif()

# ---------------------------------------------------------------------------
# The game executable
# ---------------------------------------------------------------------------
# The PPU boot scaffold is compiled here rather than taken from the runtime
# library: every one of these files #includes the lifter's per-game
# ppu_recomp.h, so they can only be built against a particular lift.
set(PS3RECOMP_SCAFFOLD
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_loader.cpp"
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_hle.cpp"
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_fs.cpp"
    "${PS3RECOMP_DIR}/runtime/ppu/ppu_sysprx.cpp"
)

# ---------------------------------------------------------------------------
# Lifted SPU images (optional)
# ---------------------------------------------------------------------------
# A title that runs SPU work gets its images lifted into <SPU_DIR>/<image>/ by
# tools/spu_lifter.py, with a registration TU generated by
# tools/build_spu_workloads.py. cellSpurs dispatches them by content
# fingerprint, so the generated table is keyed to the images THIS build ships:
# a table generated from another release registers signatures that can never
# match, which is worse than shipping none. Both the table and the job-module
# registry self-register from constructors and are therefore optional -- a tree
# that has not lifted its SPU images yet configures and links without them.
set(SPU_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../spu" CACHE PATH
    "Directory holding the lifted SPU images (<SPU_DIR>/<image>/spu_recomp.c)")
option(PORT_ENABLE_SPU "Compile and register the title's lifted SPU images" ON)

set(PORT_SPU_INPUTS "" CACHE STRING
    "Input files to scan for all embedded SPU ELF programs (semicolon-separated decrypted ELF/PRX/data paths)")
set(SPU_SOURCES "")
if(PORT_ENABLE_SPU AND PORT_SPU_INPUTS)
    include("${PS3RECOMP_DIR}/cmake/PS3RecompSPU.cmake")
    ps3recomp_generate_spu("${CMAKE_CURRENT_BINARY_DIR}/generated_spu" ${PORT_SPU_INPUTS})
    list(APPEND SPU_SOURCES ${SPU_GENERATED_SOURCES}
         "${PS3RECOMP_DIR}/runtime/spu/spu_dispatch_mt.c")
elseif(PORT_ENABLE_SPU)
    file(GLOB SPU_LIFTED CONFIGURE_DEPENDS "${SPU_DIR}/*/spu_recomp.c")
    if(SPU_LIFTED)
        list(LENGTH SPU_LIFTED SPU_IMAGE_COUNT)
        message(STATUS "Lifted SPU:      ${SPU_IMAGE_COUNT} image(s)")
        # The musttail indirect-branch fast path. Excluded from the runtime
        # library on purpose (see the SDK root CMakeLists): it must be built
        # here, by clang, or the tail call degrades to a plain call and a guest
        # loop that branches indirectly walks the thread stack off its guard
        # page a few thousand iterations in.
        list(APPEND SPU_SOURCES ${SPU_LIFTED}
             "${PS3RECOMP_DIR}/runtime/spu/spu_dispatch_mt.c")
        # Generated beside the lift; each is present only once its generator
        # has been run, so each is included only if it is actually here.
        foreach(gen IN ITEMS spu_workloads.c jobmods_register.c taskset_policy_bytes.c)
            if(EXISTS "${SPU_DIR}/${gen}")
                list(APPEND SPU_SOURCES "${SPU_DIR}/${gen}")
            else()
                message(STATUS "  (no ${gen} -- not registered)")
            endif()
        endforeach()
    else()
        message(STATUS "Lifted SPU:      none found in ${SPU_DIR}")
    endif()
endif()

add_executable(${PROJECT_NAME}
    main.cpp
    stubs.cpp
    lbp2_local.cpp
    ${PS3RECOMP_SCAFFOLD}
    ${HLE_NID_TABLE}
    ${RECOMP_SOURCES}
    ${SPU_SOURCES}
)

# lbp2_check_host_simd(): sets LBP2_HOST_HAS_AVX2 / LBP2_HOST_HAS_FMA (cached) when the compiler
# takes -mavx2 / -mfma and the machine configuring the build runs them. The defaults of
# LBP2_SPU_AVX2 / LBP2_PPU_AVX2 (and their FMA options) come from it.
macro(lbp2_check_host_simd)
    if(NOT MSVC OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
        include(CheckCSourceRuns)
        set(CMAKE_REQUIRED_FLAGS "-mavx2")
        check_c_source_runs("
            #include <immintrin.h>
            int main(void) {
                if (!__builtin_cpu_supports(\"avx2\")) return 1;
                __m256d d = _mm256_set1_pd(1.0);
                return _mm256_movemask_pd(_mm256_add_pd(d, d)) != 0;
            }" LBP2_HOST_HAS_AVX2)
        set(CMAKE_REQUIRED_FLAGS "-mavx2 -mfma")
        check_c_source_runs("
            #include <immintrin.h>
            int main(void) {
                if (!__builtin_cpu_supports(\"fma\")) return 1;
                __m128 f = _mm_set1_ps(1.0f);
                return _mm_movemask_ps(_mm_fmadd_ps(f, f, f)) != 0;
            }" LBP2_HOST_HAS_FMA)
        unset(CMAKE_REQUIRED_FLAGS)
    endif()
endmacro()

# The lifted SPU sources use bare #include "spu_context.h". Scope that include
# directory (and their flags) to those TUs alone: adding it to the whole target
# changes the compile command of every lifted PPU TU, and those are large enough
# that the needless rebuild is measured in tens of minutes.
#   SPU_USE_DISPATCH_MT -- route SPU_IB_DISPATCH through the musttail path.
#   -O2                 -- the target-wide level is -O2 too nowadays (see below); kept
#                          explicit because the SPU sources are small and decode-hot, so they get
#                          full optimization. The last -O on the line wins.
if(SPU_SOURCES)
    set_source_files_properties(${SPU_SOURCES} PROPERTIES
        INCLUDE_DIRECTORIES "${PS3RECOMP_DIR}/runtime/spu"
        COMPILE_DEFINITIONS SPU_USE_DISPATCH_MT)
    if(NOT MSVC OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
        set(_spu_opts "-O2")
        # LBP2_SPU_AVX2=ON: the lifted SPU sources also get -mavx2, and -mfma when
        # the host has FMA3 too. That selects the runtime's AVX2 form of the exact
        # SPU float ops (four lanes as one f64x4 instead of two SSE halves), VEX
        # three-operand code (~13% faster Wws jobs in LBP2's levels) and, under
        # SPU_FLOAT_RZ=1, a single fused op for fma/fms/fnms. -ffp-contract=off
        # still applies, so the compiler contracts nothing into fma by itself.
        # Default: ON when the compiler takes -mavx2 and the machine configuring
        # the build has AVX2. The binary then needs what it was built for: pass
        # -DLBP2_SPU_AVX2=OFF for one that runs anywhere.
        if(NOT DEFINED LBP2_SPU_AVX2)
            lbp2_check_host_simd()
        endif()
        option(LBP2_SPU_AVX2 "Compile the lifted SPU sources with -mavx2 (and -mfma)" ${LBP2_HOST_HAS_AVX2})
        option(LBP2_SPU_FMA "With LBP2_SPU_AVX2, also -mfma" ${LBP2_HOST_HAS_FMA})
        if(LBP2_SPU_AVX2)
            list(APPEND _spu_opts "-mavx2")
            if(LBP2_SPU_FMA)
                list(APPEND _spu_opts "-mfma")
            endif()
        endif()
        # The MFC parameter-channel writes (5-6 per DMA) become plain stores instead of calls
        # into spu_wrch (runtime/spu/spu_context.h, SPU_WRCH_INLINE).
        list(APPEND _spu_opts "-DSPU_WRCH_INLINE")
        # Every lqd/stqd tests a diagnostics gate (SPU_LS_WATCH, SPU_LS_LOWREAD, SPU_SMC_WATCH,
        # SPU_WWS_PROBE). Title builds compile it out (SPU_LS_NO_DIAG); -DLBP2_SPU_LS_DIAG=ON
        # puts it back for debugging. lbp2_local.cpp warns if those variables are set without it.
        option(LBP2_SPU_LS_DIAG "Keep the LS-access diagnostics gate in the lifted SPU code" OFF)
        if(NOT LBP2_SPU_LS_DIAG)
            list(APPEND _spu_opts "-DSPU_LS_NO_DIAG")
            set_source_files_properties(lbp2_local.cpp PROPERTIES COMPILE_DEFINITIONS LBP2_SPU_LS_NO_DIAG)
        endif()
        # LBP2_SPU_EXTRA_FLAGS="...": more flags for the lifted SPU sources only (experiments:
        # -march=native, -O3, PGO). Empty by default.
        set(LBP2_SPU_EXTRA_FLAGS "" CACHE STRING "Extra compile flags for the lifted SPU sources")
        if(LBP2_SPU_EXTRA_FLAGS)
            separate_arguments(_spu_extra UNIX_COMMAND "${LBP2_SPU_EXTRA_FLAGS}")
            list(APPEND _spu_opts ${_spu_extra})
        endif()
        set_source_files_properties(${SPU_SOURCES} PROPERTIES COMPILE_OPTIONS "${_spu_opts}")
    endif()
endif()

# app.rc carries the icon, the version block and the manifest, and needs a
# resource compiler. Listing it as a source on a host that has none is not a
# link error, it is a "no rule to make" for a file nothing can consume.
if(WIN32 AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/app.rc")
    target_sources(${PROJECT_NAME} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/app.rc")
endif()

target_include_directories(${PROJECT_NAME} PRIVATE
    "${RECOMP_DIR}"                            # the generated ppu_recomp.h
    "${PS3RECOMP_DIR}/include"
    "${PS3RECOMP_DIR}/runtime/ppu"
    "${PS3RECOMP_DIR}/runtime/spu"
    "${PS3RECOMP_DIR}/runtime/memory"
    "${PS3RECOMP_DIR}/runtime/syscalls"
    "${PS3RECOMP_DIR}/runtime/platform"        # win32_compat.h and friends
    "${PS3RECOMP_DIR}/libs/video"
    "${CMAKE_CURRENT_SOURCE_DIR}"
)

target_link_libraries(${PROJECT_NAME} PRIVATE
    ps3recomp_runtime
)

# The runtime is C++, and on Apple also Objective-C. Letting CMake infer the
# link language from the generated C would leave the C++ standard library out.
set_target_properties(${PROJECT_NAME} PROPERTIES LINKER_LANGUAGE CXX)

# Windows system import libraries. dbghelp symbolizes crash-handler addresses
# against the PDB, user32 and gdi32 are what the backend's window and its GDI
# present are made of, and winmm is timeBeginPeriod. None of the four names
# anything a POSIX linker can find; the D3D12 backend's own imports come in
# through the #pragma comment(lib) in libs/video/rsx_d3d12_backend.c.
if(WIN32)
    target_link_libraries(${PROJECT_NAME} PRIVATE
        dbghelp
        user32
        gdi32
        winmm
    )
endif()

# ---------------------------------------------------------------------------
# Compiler-specific flags
# ---------------------------------------------------------------------------
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(${PROJECT_NAME} PRIVATE
        -Wall -Wextra -Wno-unused-parameter
        -fno-strict-aliasing
        # The lift spells PPC arithmetic as signed C arithmetic, which must wrap;
        # without this, clang exploits overflow UB (e.g. folds "x*x < 0" to false).
        -fwrapv
        # The target-wide level for a build whose configuration sets none (no
        # CMAKE_BUILD_TYPE, or one CMake has no defaults for). Without it every
        # lifted PPU TU compiled at -O0: each static inline helper (ppc_rlw64,
        # vmx_w, vm_read32_inl) is a real call that spills to the stack. It was
        # -O1 to keep the huge TUs' build time down, but at -O1 GCC still leaves
        # vmx_vmaddfp / vm_read32_mm as calls inside the big lifted functions
        # (~25% of the main PPU thread's own work in LBP2). -O2: +2% fps in the
        # level, full PPU rebuild ~20 min at -j4 (~1.5 GB per compiler). Debug and
        # the optimised configurations keep their own levels.
        $<$<NOT:$<CONFIG:Debug,Release,RelWithDebInfo,MinSizeRel>>:-O2>
    )
elseif(MSVC)
    target_compile_options(${PROJECT_NAME} PRIVATE
        /W3 /wd4100 /wd4244 /wd4267
        /Zc:__cplusplus         # report correct __cplusplus value
        # ppu_recomp.h defines PPU_FENCE, the lowering of the guest's
        # sync/lwsync/eieio/isync, and in C that is <stdatomic.h>. The lifter
        # writes C++ by default, but --single-file writes ppu_recomp.c, and a
        # port that took it would not compile without this. The runtime's own
        # build already carries the same flag for the same reason.
        /experimental:c11atomics
    )
    target_compile_definitions(${PROJECT_NAME} PRIVATE
        _CRT_SECURE_NO_WARNINGS
    )
endif()

# The lifted translation units are machine-generated and can run to hundreds of
# thousands of lines each, so they get their own flags:
#
#   - warnings off. They are about generated code and nobody will act on them,
#     and at this volume they bury the diagnostics that matter.
#   - no floating-point contraction. arm64 fuses a multiply and an add by
#     default; a PPC fmadd is spelt as one where the lifter means one.
#   - /bigobj on MSVC. A single lifted file routinely passes the 65,536-section
#     limit of the default object format.
if(MSVC)
    set_source_files_properties(${RECOMP_SOURCES} PROPERTIES
        COMPILE_OPTIONS "/w;/bigobj")
else()
    set(_ppu_opts "-w;-ffp-contract=off")
    # LBP2_PPU_AVX2=ON: the lifted PPU sources also get -mavx2, and -mfma with LBP2_PPU_FMA.
    # vmx_fmaf (vmaddfp / vnmsubfp) becomes one instruction per lane instead of a double
    # emulation, and the scalar fmadd family's fma() an inline vfmadd instead of a libm
    # call. Results are the same: fmaf/fma are exact either way and -ffp-contract=off still
    # applies. +1.3% fps over -O2 alone in LBP2's level. Default: what the configuring host
    # has (as LBP2_SPU_AVX2); -DLBP2_PPU_AVX2=OFF for a binary that runs anywhere.
    if(NOT DEFINED LBP2_PPU_AVX2)
        lbp2_check_host_simd()
    endif()
    option(LBP2_PPU_AVX2 "Compile the lifted PPU sources with -mavx2 (and -mfma)" ${LBP2_HOST_HAS_AVX2})
    option(LBP2_PPU_FMA "With LBP2_PPU_AVX2, also -mfma" ${LBP2_HOST_HAS_FMA})
    if(LBP2_PPU_AVX2)
        list(APPEND _ppu_opts "-mavx2")
        if(LBP2_PPU_FMA)
            list(APPEND _ppu_opts "-mfma")
        endif()
    endif()
    # LBP2_PPU_EXTRA_FLAGS="...": more flags for the lifted PPU sources only (experiments).
    # Empty by default.
    set(LBP2_PPU_EXTRA_FLAGS "" CACHE STRING "Extra compile flags for the lifted PPU sources")
    if(LBP2_PPU_EXTRA_FLAGS)
        separate_arguments(_ppu_extra UNIX_COMMAND "${LBP2_PPU_EXTRA_FLAGS}")
        list(APPEND _ppu_opts ${_ppu_extra})
    endif()
    set_source_files_properties(${RECOMP_SOURCES} PROPERTIES
        COMPILE_OPTIONS "${_ppu_opts}")
endif()

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
install(TARGETS ${PROJECT_NAME} RUNTIME DESTINATION bin)

# ---------------------------------------------------------------------------
# The window launcher (macOS)
# ---------------------------------------------------------------------------
# A title that replaces its executable (sys_game_process_exitspawn, done by a
# port as an exec) loses its window with the old process image. The launcher
# holds the window for the whole session instead: it runs the port with
# PS3RECOMP_HOST_SURFACES set, the Metal backend renders into IOSurfaces it
# shares (libs/video/rsx_host_surface.h), and the image an exec brings up
# attaches to the same window again. One Objective-C file and no runtime
# library, so it builds in seconds:
#
#   ./MyGameRecomp_window [--title T] [--size WxH] -- ./MyGameRecomp <args>
if(APPLE)
    enable_language(OBJC)
    add_executable(${PROJECT_NAME}_window "${PS3RECOMP_DIR}/tools/host_window/host_window.m")
    target_include_directories(${PROJECT_NAME}_window PRIVATE "${PS3RECOMP_DIR}/libs/video")
    target_compile_definitions(${PROJECT_NAME}_window PRIVATE HOST_WINDOW_TITLE="${PROJECT_NAME}")
    target_compile_options(${PROJECT_NAME}_window PRIVATE -fobjc-arc -Wall -Wextra -Wno-unused-parameter)
    target_link_libraries(${PROJECT_NAME}_window PRIVATE
        "-framework AppKit" "-framework Metal" "-framework QuartzCore" "-framework IOSurface")
    install(TARGETS ${PROJECT_NAME}_window RUNTIME DESTINATION bin)
endif()

# LBP2 shims: see lbp2_local.cpp
target_link_options(${PROJECT_NAME} PRIVATE -Wl,--wrap=cellNetCtlGetState -Wl,--wrap=ppu_sysprx_register -Wl,--wrap=rsx_null_backend_init -Wl,--wrap=lv2_syscall)
