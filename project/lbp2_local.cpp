/* Local LBP2 bring-up shims. Lives only in this bring-up project copy, not in ps3recomp.
 *
 * 1. cellNetCtlGetState: the runtime's offline path deliberately returns NOT_INITIALIZED
 *    (an LBP1 rule). LBP2's net helper treats that as fatal, but accepts what a real
 *    console reports with no link: CELL_OK and state=Disconnected. The runtime has already
 *    written Disconnected by then, so only the return value changes.
 * 2. A progress logger for the game's init-step table (read-only).
 * 3. A UDP loopback for sys_net (see below).
 * 4. FMOD DSP plugins registered as relocatable lifted code (register_fmod_plugins). */
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <pthread.h>
#include <unistd.h>

extern "C" uint8_t* vm_base;
extern "C" int32_t __real_cellNetCtlGetState(int32_t* state);
extern "C" uint32_t cellGcm_flip_request_count(void);

static uint32_t be32(uint32_t a) {
    uint8_t* p = vm_base + a;
    return (uint32_t)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3];
}

extern "C" int32_t __wrap_cellNetCtlGetState(int32_t* state) {
    uint32_t ea = (uint32_t)(uintptr_t)state;
    if (ea) memset(vm_base + ea, 0xFF, 4);
    int32_t rc = __real_cellNetCtlGetState(state);
    if ((uint32_t)rc == 0x80130101u && ea && be32(ea) == 0) return 0; /* offline path wrote Disconnected */
    return rc;
}

/* 2b. Stall dump: when the init table sits on one step for 20 s (and again at 60 s), print every
 *     guest PPU thread's last lv2/HLE callsite, its in-flight syscall, a few registers and its
 *     guest stack back chain (saved LRs). Normal boots finish all 73 steps in 5-15 s. Added for
 *     the step 13 'ScratchPad' hang (2026-11-17), which never shows under gdb.
 *     The ctx pointers come from ppu_prof_stamp (linked with -Wl,--wrap=ppu_prof_stamp), which
 *     both dispatchers call with the guest ctx on every lv2 syscall and HLE call. */
struct ppu_context;
extern "C" void __real_ppu_prof_stamp(void* ctx, unsigned lr);
extern "C" int ppu_prof_snapshot(int idx, unsigned* tid, unsigned* cia, const char** name);
extern "C" uint32_t g_sc_inflight[64];
static ppu_context* volatile g_stall_ctx[65];
static volatile uint32_t g_stall_lr[65];
static void stall_dump(unsigned t, const char* cur);

/* 2d. Event ring for the stall dump (opt-in, LBP2_EVRING=1): a thread polls the per-frame job
 *     gates g1/g2 (u16 at *(TOC2+0x2F98) + g*0x404 + 4) and the post-effect labels every 100 us and
 *     records each change in memory; the GCM retire hook (#13) records every user command with the
 *     gate state it found. Nothing is printed until a stall, but the poll thread alone made the freeze vanish (0 in 19 runs vs ~1 in 5). */
struct EvRec { uint64_t us; uint32_t kind, a, b; };   /* kind 1 mem change, 2 user command */
static EvRec g_ev[1024];
static volatile uint32_t g_ev_n;
static bool g_ev_on;
static uint64_t ev_now_us() {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000u + (uint64_t)ts.tv_nsec / 1000u;
}
static void ev_add(uint32_t kind, uint32_t a, uint32_t b) {
    const uint32_t i = __atomic_fetch_add(&g_ev_n, 1u, __ATOMIC_RELAXED) & 1023u;
    g_ev[i] = EvRec{ ev_now_us(), kind, a, b };
}
static void* ev_poll(void*) {
    static const uint32_t labels[8] = { 0x41, 0x42, 0x43, 0x44, 0x45, 0x4E, 0x4F, 0x50 };
    uint32_t last[10] = {}; bool init = false;
    while (!__atomic_load_n(&vm_base, __ATOMIC_ACQUIRE)) usleep(100000);   /* started before guest memory exists */
    sleep(5);
    for (;;) {
        usleep(100);
        const uint32_t gb = be32(0xC75A98u + 0x2F98u);
        if (gb < 0x10000u || gb >= 0x40000000u) continue;
        uint32_t cur[10];
        cur[0] = (uint32_t)vm_base[gb + 0x404 + 4] << 8 | vm_base[gb + 0x404 + 5];
        cur[1] = (uint32_t)vm_base[gb + 0x808 + 4] << 8 | vm_base[gb + 0x808 + 5];
        for (int k = 0; k < 8; k++) cur[2 + k] = be32(0x20000000u + labels[k] * 16u);
        for (int k = 0; k < 10 && init; k++)
            if (cur[k] != last[k]) ev_add(1, k < 2 ? (uint32_t)(k + 1) : 0x100u | labels[k - 2], last[k] << 16 | (cur[k] & 0xFFFF));
        for (int k = 0; k < 10; k++) last[k] = cur[k];
        init = true;
    }
    return nullptr;
}
static void ev_dump() {
    const uint32_t n = g_ev_n, cnt = n < 160u ? n : 160u;
    if (!cnt) return;
    const uint64_t t_end = g_ev[(n - 1) & 1023u].us;
    fprintf(stderr, "[lbp2-stall] last %u events (ms before the newest; g1/g2 = gate count, L = label):\n", cnt);
    for (uint32_t j = n - cnt; j != n; j++) {
        const EvRec& e = g_ev[j & 1023u];
        const double ms = (double)(t_end - e.us) / 1000.0;
        if (e.kind == 1 && e.a < 0x100u)
            fprintf(stderr, "[lbp2-stall]   -%8.3f g%u %u -> %u\n", ms, e.a, e.b >> 16, e.b & 0xFFFF);
        else if (e.kind == 1)
            fprintf(stderr, "[lbp2-stall]   -%8.3f L%02X %u -> %u\n", ms, e.a & 0xFF, e.b >> 16, e.b & 0xFFFF);
        else if (e.kind == 2)
            fprintf(stderr, "[lbp2-stall]   -%8.3f ucmd %08X gate %s%s\n", ms, e.a,
                    (e.b & 1) ? "armed" : "NOT armed", (e.b & 2) ? " (waited)" : "");
        else if (e.kind == 3 || e.kind == 4)
            fprintf(stderr, "[lbp2-stall]   -%8.3f arm %s g%u (gate %u) lr %08X\n", ms, e.kind == 3 ? "enter" : "done ",
                    e.a & 0xFF, (e.a >> 8) & 0xFFFF, e.b);
        else
            fprintf(stderr, "[lbp2-stall]   -%8.3f release g%u flag %u list %u (gate %u) lr %08X\n", ms, e.a & 0xFF,
                    (e.a >> 8) & 0xF, (e.a >> 12) & 0xFF, e.a >> 20, e.b);
    }
}

static void* progress(void*) {
    static const uint32_t HEAD_SLOT = 0xC65AF0u - 0x74ECu;
    char last[128] = "";
    unsigned since = 0, dumps = 0;
    for (unsigned t = 0;; t += 5) {
        sleep(5);
        if (!vm_base) continue;
        uint32_t node = be32(HEAD_SLOT);
        if (node < 0x10000 || node > 0x10000000) continue;
        int i = 0; char cur[128] = "";
        for (; node && i < 200; i++) {
            uint32_t nm = be32(node), skip = be32(node + 4), init = be32(node + 8),
                     cl = be32(node + 12), x10 = be32(node + 16), nx = be32(node + 24);
            if (!init && !cl && !x10) { snprintf(cur, sizeof cur, "ALL-DONE (%d steps)", i); break; }
            if (!vm_base[node + 0x14] && !skip && init) {
                snprintf(cur, sizeof cur, "step %d '%s'", i, nm ? (const char*)vm_base + nm : "?");
                break;
            }
            node = nx ? nx : node + 0x24;
        }
        if (strcmp(cur, last)) { since = t; dumps = 0; }
        if (strcmp(cur, last) || t % 60 == 0) {
            fprintf(stderr, "[lbp2-local] t=%us init at: %s\n", t, cur);
            strcpy(last, cur);
        }
        if (cur[0] && strncmp(cur, "ALL-DONE", 8) && dumps < 2 && t - since >= (dumps ? 60u : 20u)) {
            dumps++;
            stall_dump(t, cur);
        }
        /* Frame progress. The RSX draw log stops after 32 lines (PS3_LOG_FIRST),
         * so a count of logged draws says nothing about whether frames run. */
        if (t % 10 == 0)
            fprintf(stderr, "[lbp2-local] t=%us flips=%u\n", t, cellGcm_flip_request_count());
    }
    return nullptr;
}

/* 3. UDP loopback. The runtime's sys_net is a black hole: sendto drops every packet,
 *    recv/recvfrom always say EWOULDBLOCK and select never reports a readable fd.
 *    A real console with no link still has lo0, and LBP2 depends on it: its party code
 *    (E_PARTY_OPERATION_CREATE, run unconditionally at init step 70 'Network') sends
 *    REQUEST_JOIN to itself over UDP to 127.0.0.1:3658 and waits in
 *    E_PARTY_STAGE_WAIT_FOR_JOIN_RESPONSE_FROM_NEW_PLAYER_TO_FOLLOW for the reply.
 *    This delivers datagrams sent to 127.x.x.x or 0.0.0.0 to the socket bound to the
 *    destination port. Everything else keeps the runtime's offline behaviour: packets
 *    to other addresses vanish, and write/except sets are still reported empty.
 *    Registered ahead of the runtime's handlers (first registration wins) by wrapping
 *    ppu_sysprx_register. errno stays with the runtime's _sys_net_errno_loc, which
 *    always reports EWOULDBLOCK. */
#include <chrono>
#include <condition_variable>
#include <deque>
#include <map>
#include <mutex>
#include <vector>
#include "ppu_context.h"

extern "C" void ps3_hle_register_ctx(uint32_t nid, const char* name, void (*fn)(ppu_context*));
extern "C" void __real_ppu_sysprx_register(void);

namespace {
struct Dgram { std::vector<uint8_t> data; uint8_t from[16]; };
struct Sock { int type = 0; bool bound = false; uint16_t port = 0, vport = 0; std::deque<Dgram> q; };
std::mutex g_mu;
std::condition_variable g_cv;
std::map<uint32_t, Sock> g_socks;
uint32_t g_next_fd = 3;
unsigned g_logged = 0;

uint16_t rd16(uint32_t a) { return (uint16_t)(vm_base[a] << 8 | vm_base[a + 1]); }
void wr32(uint32_t a, uint32_t v) { vm_base[a] = v >> 24; vm_base[a + 1] = v >> 16; vm_base[a + 2] = v >> 8; vm_base[a + 3] = v; }
uint64_t rd64(uint32_t a) { return (uint64_t)be32(a) << 32 | be32(a + 4); }
void ret(ppu_context* c, int32_t v) { c->gpr[3] = (uint64_t)(int64_t)v; }

void lo_socket(ppu_context* c) {
    std::lock_guard<std::mutex> l(g_mu);
    uint32_t fd = g_next_fd++;
    g_socks[fd].type = (int)(uint32_t)c->gpr[4];
    ret(c, (int32_t)fd);
}
void lo_bind(ppu_context* c) {   /* bind(fd, sockaddr_in{len,family,port,addr,vport,...}, len) */
    uint32_t fd = (uint32_t)c->gpr[3], sa = (uint32_t)c->gpr[4];
    std::lock_guard<std::mutex> l(g_mu);
    Sock& s = g_socks[fd];
    if (sa) { s.bound = true; s.port = rd16(sa + 2); s.vport = rd16(sa + 8); }
    fprintf(stderr, "[lbp2-local] lo: bind fd=%u type=%d port=%u vport=%u\n", fd, s.type, s.port, s.vport);
    ret(c, 0);
}
void lo_close(ppu_context* c) {
    std::lock_guard<std::mutex> l(g_mu);
    g_socks.erase((uint32_t)c->gpr[3]);
    ret(c, 0);
}
void lo_sendto(ppu_context* c) { /* sendto(fd, buf, len, flags, to, tolen) */
    uint32_t fd = (uint32_t)c->gpr[3], buf = (uint32_t)c->gpr[4], len = (uint32_t)c->gpr[5];
    uint32_t to = (uint32_t)c->gpr[7];
    ret(c, (int32_t)len);        /* reported sent either way, as before */
    if (!to || vm_base[to + 1] != 2 /* AF_INET */) return;
    uint32_t addr = be32(to + 4);
    if ((addr >> 24) != 127 && addr != 0) return;
    uint16_t port = rd16(to + 2), vport = rd16(to + 8);
    std::lock_guard<std::mutex> l(g_mu);
    Sock* dst = nullptr;
    for (auto& kv : g_socks)
        if (kv.second.bound && kv.second.port == port && (!vport || !kv.second.vport || kv.second.vport == vport)) { dst = &kv.second; break; }
    if (!dst) return;
    const Sock& src = g_socks[fd];
    Dgram d; d.data.assign(vm_base + buf, vm_base + buf + len);
    memcpy(d.from, vm_base + to, 16);
    d.from[2] = src.port >> 8; d.from[3] = src.port & 0xFF;
    d.from[4] = 127; d.from[5] = 0; d.from[6] = 0; d.from[7] = 1;
    d.from[8] = src.vport >> 8; d.from[9] = src.vport & 0xFF;
    if (dst->q.size() < 1024) dst->q.push_back(std::move(d));
    if (g_logged < 8) { g_logged++; fprintf(stderr, "[lbp2-local] lo: fd=%u -> port %u: %u bytes\n", fd, port, len); }
    g_cv.notify_all();
}
int32_t lo_pop(uint32_t fd, uint32_t buf, uint32_t len, uint32_t from, uint32_t fromlen) {
    std::lock_guard<std::mutex> l(g_mu);
    auto it = g_socks.find(fd);
    if (it == g_socks.end() || it->second.q.empty()) return -1;   /* errno_loc says EWOULDBLOCK */
    Dgram d = std::move(it->second.q.front()); it->second.q.pop_front();
    uint32_t n = (uint32_t)d.data.size() < len ? (uint32_t)d.data.size() : len;
    memcpy(vm_base + buf, d.data.data(), n);
    if (from && fromlen) {
        uint32_t cap = be32(fromlen); if (cap > 16) cap = 16;
        memcpy(vm_base + from, d.from, cap);
        wr32(fromlen, 16);
    }
    return (int32_t)n;
}
void lo_recvfrom(ppu_context* c) {   /* recvfrom(fd, buf, len, flags, from, fromlen*) */
    ret(c, lo_pop((uint32_t)c->gpr[3], (uint32_t)c->gpr[4], (uint32_t)c->gpr[5], (uint32_t)c->gpr[7], (uint32_t)c->gpr[8]));
}
void lo_recv(ppu_context* c) {
    ret(c, lo_pop((uint32_t)c->gpr[3], (uint32_t)c->gpr[4], (uint32_t)c->gpr[5], 0, 0));
}
/* select(nfds, rd, wr, ex, timeout{s64 sec, s64 usec}). Same timing as the runtime's
 * (NULL = tick at 10 ms, capped at 100 ms) but wakes early and reports readable fds. */
void lo_select(ppu_context* c) {
    uint32_t nfds = (uint32_t)c->gpr[3], rd = (uint32_t)c->gpr[4], wr = (uint32_t)c->gpr[5];
    uint32_t ex = (uint32_t)c->gpr[6], tv = (uint32_t)c->gpr[7];
    uint64_t us = 10000;
    if (tv) us = rd64(tv) * 1000000ull + rd64(tv + 8);
    if (us > 100000) us = 100000;
    if (nfds > 1024) nfds = 1024;
    std::vector<uint32_t> want;
    if (rd) for (uint32_t fd = 0; fd < nfds; fd++)
        if (be32(rd + (fd >> 5) * 4) & (1u << (fd & 31))) want.push_back(fd);
    std::vector<uint32_t> ready;
    {
        std::unique_lock<std::mutex> l(g_mu);
        auto scan = [&] {
            ready.clear();
            for (uint32_t fd : want) { auto it = g_socks.find(fd); if (it != g_socks.end() && !it->second.q.empty()) ready.push_back(fd); }
            return !ready.empty();
        };
        if (!scan() && us) g_cv.wait_for(l, std::chrono::microseconds(us), scan);
    }
    const uint32_t sets[3] = { rd, wr, ex };
    for (int s = 0; s < 3; s++)
        if (sets[s]) for (uint32_t i = 0; i < 128; i += 4) wr32(sets[s] + i, 0);
    for (uint32_t fd : ready) wr32(rd + (fd >> 5) * 4, be32(rd + (fd >> 5) * 4) | (1u << (fd & 31)));
    ret(c, (int32_t)ready.size());
}
}  // namespace

/* 4. cellKbRead (sys_io NID 0xFF0A21B7). The runtime implements it under the non-SDK name
 *    cellKbGetData, so the game's import was unresolved and faked as CELL_OK without writing
 *    the CellKbData. cellKbInit marks port 0 connected, so the game's keyboard poll (0x3223A0)
 *    then looped over the stale stack word at data.len, push_back'ing "keycodes" until its
 *    vector asked the 60 MB main pool for 16 MB (the OOM after ~65 s). Same signature/layout. */
/*    Fixed in the ps3recomp fork (lbp2-fixes: the runtime exports cellKbRead), so this binds
 *    only when built against a runtime that still has the old name (weak reference). */
extern "C" int32_t cellKbGetData(uint32_t port_no, void* data) __attribute__((weak));
static void kb_read(ppu_context* c) {
    c->gpr[3] = (uint64_t)(int64_t)cellKbGetData((uint32_t)c->gpr[3], (void*)(uintptr_t)(uint32_t)c->gpr[4]);
}


/* 6. Experiment, env LBP2_NO_KB=1: cellKbGetInfo (0x2F1774D5) reports no keyboard, as a typical
 *    console does. The runtime's cellKbInit marks port 0 connected; LBP2 then calls
 *    cellKey2CharOpen on every keyboard poll and never closes (runtime limit: 4 handles). */
static void kb_getinfo_none(ppu_context* c) {
    uint32_t ea = (uint32_t)c->gpr[3];
    if (!ea) { ret(c, (int32_t)0x80121202u); return; }   /* CELL_KB_ERROR_INVALID_PARAMETER */
    wr32(ea + 0, 2); wr32(ea + 4, 0); wr32(ea + 8, 0);
    for (uint32_t i = 0; i < 127; i++) vm_base[ea + 12 + i] = 0;
    ret(c, 0);
}

/* 9. Experiment, env LBP2_NO_MLAA=1: skip Edge MLAA (jaggies, no ~17 ms SPU round trip).
 *    The game has no switch (game-internals.md, "Post-processing, MLAA"). Each frame the
 *    PPU fills 5 task params (0xACFD3C) and clears done flag obj+0x28; the RSX copies the
 *    scene to the MLAA buffer, then the GCM user handler (cmd 0xF5AAC0DE) calls
 *    _cellSpursSendSignal for each of the 5 MLAA tasks (0xACFF14); the last task writes
 *    label 0x58 = frame counter and sets obj+0x28; the RSX acquires 0x58 and copies the
 *    buffer back. Here, signals to the MLAA taskset don't wake its tasks: the last one does
 *    the last task's two writes instead, so the copy-back returns the unsmoothed scene.
 *    obj = *(TOC 0xC65AF0 + 0x2548) = {+4 taskset, +8 task id array, +0x10 params (64 B
 *    each), +0x2C count}; 0xACFD3C puts the completion words in task 0's params: +0 label
 *    value (the frame counter), +4 label EA (obj+0x24, seen 0x20000580), +8 = &obj+0x28.
 *    Run nomlaa-2 (2026-11-13): 18.5 fps vs 16.4, but the glow halo around glowing
 *    objects disappears too, not only the anti-aliasing. On by default in env.sh since
 *    2026-11-16 (user: losing the glow is fine for now); LBP2_NO_MLAA=0 turns MLAA back on.
 *    It also turns on the runtime's RSX_ENGINE_XFER_SHADOW unless that is set. */
extern "C" int32_t _cellSpursSendSignal(void* taskset, uint32_t taskId);
static bool g_no_mlaa;
static void store_be32(uint32_t ea, uint32_t v) {
    __atomic_store_n((uint32_t*)(vm_base + ea), __builtin_bswap32(v), __ATOMIC_RELEASE);
}
static void send_signal(ppu_context* c) {
    const uint32_t ts = (uint32_t)c->gpr[3], id = (uint32_t)c->gpr[4];
    const uint32_t obj = be32(0xC65AF0u + 0x2548u);
    if (g_no_mlaa && ts && obj && be32(obj + 4) == ts) {
        const uint32_t n = vm_base[obj + 0x2C];
        if (n && id == be32(be32(obj + 8) + (n - 1) * 4)) {
            const uint32_t last = be32(obj + 0x10);   /* task 0's params (see above) */
            const uint32_t counter = be32(be32(0xC65AF0u + 0x2564u));
            uint32_t value = be32(last), flag = be32(last + 8);
            if (!value) value = counter;
            static unsigned logged;
            if (logged < 3) {
                logged++;
                fprintf(stderr, "[lbp2-local] LBP2_NO_MLAA: taskset 0x%08X id %u: label 0x58 = 0x%08X "
                        "(counter 0x%08X, param+4 0x%08X), flag 0x%08X (obj+0x28 0x%08X)\n",
                        ts, id, value, be32(be32(0xC65AF0u + 0x2564u)), be32(last + 4), flag, obj + 0x28);
            }
            store_be32(0x20000580u, value);          /* GCM label 0x58 */
            store_be32(flag ? flag : obj + 0x28, 1); /* the PPU waits for nonzero (0xACFE98) */
        }
        ret(c, 0);
        return;
    }
    ret(c, _cellSpursSendSignal((void*)(uintptr_t)ts, id));
}

/* 10. LBP2_SKIP_INTRO=1 (env.sh default): skip the intro movie. START skips it once the game
 *     is ready for that, which happens anywhere from ~44 to ~48 s, and START in the level
 *     opens the pause menu (and the next one closes it), so timed PAD_SCRIPT presses either
 *     miss the skip or leave the level paused depending on the run (nomlaa-3 stayed paused,
 *     at the 30 Hz cap). This pulses START (20 polls on, 40 off) from 38 s after the first
 *     pad poll until the level's first Edge MLAA kick: counter *(*(TOC+0x2564)) becomes
 *     nonzero at the level start and never before (no MLAA in the movie or menus). Gives up
 *     at 150 s. Cross doesn't skip the movie (run skip-3). */
extern "C" int32_t cellPadGetData(uint32_t port_no, void* data);
static bool g_skip_intro;
static void pad_get_data(ppu_context* c) {
    const uint32_t port = (uint32_t)c->gpr[3], ea = (uint32_t)c->gpr[4];
    const int32_t rc = cellPadGetData(port, (void*)(uintptr_t)ea);
    ret(c, rc);
    static std::chrono::steady_clock::time_point t0 = std::chrono::steady_clock::now();
    static bool done;
    static unsigned polls;
    if (done || rc != 0 || port != 0 || !ea) return;
    const double t = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    if (t < 38.0) return;
    const uint32_t ctr_slot = be32(0xC65AF0u + 0x2564u);
    if (t > 150.0 || (ctr_slot && be32(ctr_slot) != 0)) {
        done = true;
        fprintf(stderr, "[lbp2-local] LBP2_SKIP_INTRO: stopped at %.1f s (%s)\n", t,
                t > 150.0 ? "timeout" : "level started");
        return;
    }
    if (polls++ % 60 < 20) vm_base[ea + 9] |= 0x08;   /* button[2] DIGITAL1 low byte: START */
}

/* FMOD DSP plugins run lifted (relocatable). The FMOD mixer SPU task (image 9) DMAs each plugin's
 * file image straight out of the game ELF (EA = file offset + 0x10000 + 0x100, i.e. from the
 * first PT_LOAD, vaddr 0x80) into its swap area at LS ~0x21E00-0x2E000, at a different address
 * per plugin, and re-fetches it on almost every use (plugin 8: ~1200 loads/s). The plugins are
 * PIC (ila K + brsl-derived delta), so they are lifted once with spu_lifter.py --reloc at their
 * ELF base 0x80; a GET from the EA below makes that copy resident and dispatch runs it at
 * canon 0x80 + offset with ctx->reloc_delta. Before this they ran in the SPU interpreter, one
 * full host core, and the mixer fell behind (main waits on FMOD's lock -> long frames).
 * Image ids are spu/spu_workloads.c's. Span = the first PT_LOAD's filesz (all the code).
 * SPU_RELOC_OFF=1 (runtime) skips these registrations for an A/B. */
extern "C" void spu_overlay_register_region_reloc(uint32_t content_ea, uint32_t span,
                                                  uint32_t canon, int image_id);
static void register_fmod_plugins(void) {
    static const struct { uint32_t file_off, span; int image_id; } k[] = {
        /* Unnamed plugins (no SpuGUID/.note), loaded at LS 0x22010 while walking. */
        {0xB81000u, 0x0520u,  2},   /* spu_0000 */
        {0xB81680u, 0x1DB0u,  3},   /* spu_0001 */
        {0xB83580u, 0x7250u,  4},   /* spu_0002 */
        {0xB8AA80u, 0x4350u,  5},   /* spu_0003 */
        {0xB8EF80u, 0x3BB0u,  6},   /* spu_0004 */
        /* fmod_codec_* / fmod_dsp_* (their .note.spu_name). Not all are used in every level. */
        {0xBE7400u, 0x62C0u, 10},   /* spu_0008 codec_adpcm */
        {0xBEE080u, 0x2A90u, 11},   /* spu_0009 codec_raw */
        {0xBF1500u, 0x2AF0u, 12},   /* spu_0010 dsp_chorus */
        {0xBF4480u, 0x0850u, 13},   /* spu_0011 dsp_compressor */
        {0xBF5180u, 0x39A0u, 14},   /* spu_0012 dsp_delay */
        {0xBF9000u, 0x0770u, 15},   /* spu_0013 dsp_distortion */
        {0xBF9C00u, 0x13F0u, 16},   /* spu_0014 dsp_echo */
        {0xBFB480u, 0x07B0u, 17},   /* spu_0015 dsp_flange */
        {0xBFC100u, 0x1710u, 18},   /* spu_0016 dsp_highpass */
        {0xBFDD00u, 0x0E30u, 19},   /* spu_0017 dsp_itecho */
        {0xBFF100u, 0x13B0u, 20},   /* spu_0018 dsp_lowpass2 */
        {0xC00980u, 0x2580u, 21},   /* spu_0019 dsp_lowpass */
        {0xC03380u, 0x10B0u, 22},   /* spu_0020 dsp_lowpass_simple */
        {0xC04980u, 0x0540u, 23},   /* spu_0021 dsp_normalize */
        {0xC05380u, 0x0720u, 24},   /* spu_0022 dsp_oscillator */
        {0xC05F80u, 0x1360u, 25},   /* spu_0023 dsp_parameq */
        {0xC07780u, 0x3450u, 26},   /* spu_0024 dsp_pitchshift */
        {0xC0B080u, 0x3190u, 27},   /* spu_0025 dsp_sfxreverb */
        {0xC0E700u, 0x1BA0u, 28},   /* spu_0026 dsp_tremolo */
        {0xC10900u, 0x3BA0u, 29},   /* spu_0027 codec_mpeg_functions */
        {0xC14B00u, 0x1DD0u, 30},   /* spu_0028 codec_mpeg_init */
    };
    for (const auto& p : k)
        spu_overlay_register_region_reloc(p.file_off + 0x10000u + 0x100u, p.span, 0x80u, p.image_id);
}

/* 13. LBP2_SCREEN_SIZE=<0..1> (default 0.5; "game" keeps the game's own value): the
 *     display option "screen size" (the in-game Screen Size slider, script
 *     Get/SetDisplayOptionScreenSize). The final composite draws the scene as a centred quad
 *     scaled by powf(1.3, size - 0.5) (0x2BDDFC; 0.5 = exactly full screen, 0 = x0.877 with
 *     black bars, 1 = x1.14 cropped). The game's display init (0x5DF918) zeroes the option
 *     (current 0xD10D48, target 0xD10D4C) right before its cellVideoOutConfigure call
 *     (LR 0x5DFC10), and a new profile copies the current value (ctor 0x171470, field
 *     +0x458), so with no saved profile the game ran at 0: the picture filled only
 *     x 79..1201, y 44..676 of the 1280x720 frame. Where a console gets a nonzero default is
 *     unknown. The saved profile (hdd0/game/BCUS98245_USER1/USRDIR/bigfart1, made at the
 *     first boot) holds 0 too and is applied at every boot (0x32D364 calls the setter
 *     0x5DCCC8 with its value, LR 0x32D69C). So this sets both values after the display
 *     init's call, which new profiles copy, and replaces the saved profile's value when it
 *     is applied (linked with -Wl,--wrap=_Z13func_005DCCC8P11ppu_context; the lifted
 *     stub 0x7A3210 that reaches the setter is in another object, so it goes through the
 *     wrap). The in-game slider still works for the session (other LR), but its saved
 *     value is replaced at the next boot unless LBP2_SCREEN_SIZE=game. */
extern "C" int32_t cellVideoOutConfigure(uint32_t videoOut, void* config, void* option, uint32_t wait);
static float g_screen_size = 0.5f;
static bool g_screen_size_on;
extern "C" void __real__Z13func_005DCCC8P11ppu_context(ppu_context* c);
extern "C" void __wrap__Z13func_005DCCC8P11ppu_context(ppu_context* c) {
    if (g_screen_size_on && (uint32_t)c->lr == 0x0032D69Cu) {
        fprintf(stderr, "[lbp2-local] LBP2_SCREEN_SIZE: saved profile's screen size %.3f -> %.3f\n",
                c->fpr[1], (double)g_screen_size);
        c->fpr[1] = (double)g_screen_size;
    }
    __real__Z13func_005DCCC8P11ppu_context(c);
}
static void video_out_configure(ppu_context* c) {
    ret(c, cellVideoOutConfigure((uint32_t)c->gpr[3], (void*)(uintptr_t)(uint32_t)c->gpr[4],
                                 (void*)(uintptr_t)(uint32_t)c->gpr[5], (uint32_t)c->gpr[6]));
    if ((uint32_t)c->lr != 0x005DFC10u) return;
    uint32_t bits;
    memcpy(&bits, &g_screen_size, 4);
    wr32(0xD10D48u, bits);
    wr32(0xD10D4Cu, bits);
    fprintf(stderr, "[lbp2-local] LBP2_SCREEN_SIZE: display option screen size set to %.3f\n",
            (double)g_screen_size);
}

extern "C" void __wrap_ppu_sysprx_register(void) {
    register_fmod_plugins();
    {
        const char* e = getenv("LBP2_SCREEN_SIZE");
        if (!e || strcmp(e, "game")) {
            if (e && *e) g_screen_size = strtof(e, nullptr);
            if (!(g_screen_size >= 0.0f)) g_screen_size = 0.0f;   /* also NaN */
            if (g_screen_size > 1.0f) g_screen_size = 1.0f;
            g_screen_size_on = true;
            ps3_hle_register_ctx(0x0BAE8772u, "cellVideoOutConfigure (lbp2: LBP2_SCREEN_SIZE)",
                                 video_out_configure);
        }
    }
    { const char* e = getenv("LBP2_SKIP_INTRO"); g_skip_intro = e && *e == '1'; }
    if (g_skip_intro)
        ps3_hle_register_ctx(0x8B72CDA1u, "cellPadGetData (lbp2: LBP2_SKIP_INTRO)", pad_get_data);
    { const char* e = getenv("LBP2_NO_MLAA"); g_no_mlaa = e && *e == '1'; }
    if (g_no_mlaa) {
        fprintf(stderr, "[lbp2-local] LBP2_NO_MLAA=1: Edge MLAA skipped\n");
        ps3_hle_register_ctx(0xE0A6DBE4u, "_cellSpursSendSignal (lbp2: LBP2_NO_MLAA)", send_signal);
        /* With no MLAA job the scene comes back from the MLAA buffer unchanged, so its copy
         * out and back can stay on the GPU (runtime RSX_ENGINE_XFER_SHADOW: no flush and
         * readback each frame, +4.2% fps, runs xs-on/off 2026-11-15). Set it to 0 to compare. */
        if (!getenv("RSX_ENGINE_XFER_SHADOW")) setenv("RSX_ENGINE_XFER_SHADOW", "1", 1);
    }
    if (getenv("LBP2_NO_KB"))
        ps3_hle_register_ctx(0x2F1774D5u, "cellKbGetInfo (lbp2: no keyboard)", kb_getinfo_none);
    if (cellKbGetData)
        ps3_hle_register_ctx(0xFF0A21B7u, "cellKbRead (lbp2: -> cellKbGetData)", kb_read);
    ps3_hle_register_ctx(0x9C056962u, "netSocket (lbp2 loopback)",  lo_socket);
    ps3_hle_register_ctx(0xB0A59804u, "netBind (lbp2 loopback)",    lo_bind);
    ps3_hle_register_ctx(0x6DB6E8CDu, "netClose (lbp2 loopback)",   lo_close);
    ps3_hle_register_ctx(0x9647570Bu, "netSendTo (lbp2 loopback)",  lo_sendto);
    ps3_hle_register_ctx(0x1F953B9Fu, "recvfrom (lbp2 loopback)",   lo_recvfrom);
    ps3_hle_register_ctx(0xFBA04F37u, "recv (lbp2 loopback)",       lo_recv);
    ps3_hle_register_ctx(0x3F09E20Au, "select (lbp2 loopback)",     lo_select);
    __real_ppu_sysprx_register();
}

extern "C" void __wrap_ppu_prof_stamp(void* vctx, unsigned lr) {
    unsigned t = (unsigned)((ppu_context*)vctx)->thread_id;
    if (t < 65) { g_stall_ctx[t] = (ppu_context*)vctx; g_stall_lr[t] = lr; }
    __real_ppu_prof_stamp(vctx, lr);
}

static bool guest_ok(uint32_t a) { return a >= 0x10000u && a < 0xFFFF0000u; }

extern "C" void cellSpurs_debug_dump(const char* tag) __attribute__((weak));

static void stall_dump(unsigned t, const char* cur) {
    fprintf(stderr, "[lbp2-stall] t=%us stuck at %s: guest PPU threads\n", t, cur);
    /* RSX side: control words at 0x20002000 (+0x40 = put/get/ref in the SDK layout) and the labels
     * the SPU jobs release (0x44, the 0x4E-0x50 post-effect gates, 0x58 = MLAA frame counter). */
    fprintf(stderr, "[lbp2-stall] ctrl +00 %08X %08X %08X  +40 %08X %08X %08X\n", be32(0x20002000u),
            be32(0x20002004u), be32(0x20002008u), be32(0x20002040u), be32(0x20002044u), be32(0x20002048u));
    fprintf(stderr, "[lbp2-stall] labels 41..44 %08X %08X %08X %08X  4E..50 %08X %08X %08X  58 %08X\n",
            be32(0x20000410u), be32(0x20000420u), be32(0x20000430u), be32(0x20000440u),
            be32(0x200004E0u), be32(0x200004F0u), be32(0x20000500u), be32(0x20000580u));
    if (cellSpurs_debug_dump) cellSpurs_debug_dump("lbp2-stall");
    ev_dump();
    /* The Wws job list main drains at 0x5EBE84 (*(TOC2+0x2F9C) -> list object -> line, TOC2 = 0xC75A98): per row
     * {hw0 publish, hw1 claim, hw2..hw7 per-SPU in flight}, headers {u16, u16 cmd, u32 arg} at
     * *(line+0x30+4*row); cmd 2 = wait until the u16 at arg is 0 (dependency {u16 count, u8 wid,
     * u8 ready}). Plus the dependency lines the PMs were found spinning on in two frozen runs. */
    auto dump_list = [](const char* name, uint32_t obj, unsigned before, unsigned after) {
        const uint32_t line = guest_ok(obj) && obj < 0x40000000u ? be32(obj) : 0;
        if (!guest_ok(line) || line >= 0x40000000u) return;
        fprintf(stderr, "[lbp2-stall] %s obj %08X (spurs %08X wid %u) line %08X: %08X %08X %08X %08X\n", name, obj,
                be32(obj + 4), be32(obj + 8), line, be32(line), be32(line + 4), be32(line + 8), be32(line + 12));
        for (uint32_t row = 0; row < 4; row++) {
            const uint32_t r = line + 0x40 + 16 * row, hdr = be32(line + 0x30 + 4 * row);
            uint16_t h[8];
            for (int k = 0; k < 8; k++) h[k] = (uint16_t)(be32(r + 2 * (k & ~1)) >> ((k & 1) ? 0 : 16));
            if (!guest_ok(hdr) || hdr >= 0x40000000u) continue;
            fprintf(stderr, "[lbp2-stall]   row %u hdr %08X hw %04X %04X | %04X %04X %04X %04X %04X %04X\n",
                    row, hdr, h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);
            unsigned lo = h[1] > before ? h[1] - before : 0u;
            for (unsigned i = lo; i < h[1] + after && i < 0x400u; i++) {
                const uint32_t w0 = be32(hdr + 8 * i), arg = be32(hdr + 8 * i + 4);
                fprintf(stderr, "[lbp2-stall]     [%03X] %08X %08X", i, w0, arg);
                if ((w0 & 0xFFFF) == 2 && guest_ok(arg) && arg < 0x40000000u) fprintf(stderr, " dep %08X", be32(arg & ~3u));
                fputc('\n', stderr);
            }
        }
    };
    /* main's list (0x5EBE84: *(TOC2+0x2F9C) -> list object -> line, TOC2 = 0xC75A98), then every list in
     * the wid table the gate release kicks (*(TOC2+0x2F58) -> u32 objects, 0x5EBC24) */
    const uint32_t toc = 0xC75A98u;
    dump_list("joblist main", be32(be32(toc + 0x2F9Cu) + 4), 3, 5);
    { const uint32_t wt = be32(toc + 0x2F58u);
      for (uint32_t i = 0; i < 16 && guest_ok(wt); i++) {
          char nm[24]; snprintf(nm, sizeof nm, "joblist w%u", i);
          dump_list(nm, be32(wt + 4 * i), 1, 3);
      } }
    /* the dependency structs at *(TOC2+0x2F98): {u32 n; entries {u16 count, u8 wid, u8 ready}}, stride 0x404 */
    { const uint32_t db = be32(toc + 0x2F98u);
      for (uint32_t g = 0; g < 8 && guest_ok(db); g++) {
          const uint32_t sb = db + g * 0x404u, n = be32(sb);
          fprintf(stderr, "[lbp2-stall] depstruct %u n %u:", g, n);
          for (uint32_t k = 0; k < 8; k++) fprintf(stderr, " %08X", be32(sb + 4 + 4 * k));
          fputc('\n', stderr);
      } }
    fprintf(stderr, "[lbp2-stall] pmdeps 160E5100: %08X %08X  160FD480: %08X %08X  160F5300: %08X %08X\n",
            be32(0x160E5100u), be32(0x160E5104u), be32(0x160FD480u), be32(0x160FD484u),
            be32(0x160F5300u), be32(0x160F5304u));
    /* The two per-frame gates the GCM user handler releases (0x4000xxxx / 0xC000xxxx): structs at
     * *(TOC2+0x2F98), stride 0x404, dependency word {u16 count, u8 wid, u8 ready} at +4. */
    { const uint32_t gb = be32(0xC75A98u + 0x2F98u);
      fprintf(stderr, "[lbp2-stall] gates base %08X: g0 %08X g1 %08X g2 %08X\n", gb,
              guest_ok(gb) ? be32(gb + 4) : 0u, guest_ok(gb) ? be32(gb + 0x404 + 4) : 0u,
              guest_ok(gb) ? be32(gb + 0x808 + 4) : 0u); }
    for (unsigned tid = 1; tid < 65; tid++) {
        ppu_context* c = g_stall_ctx[tid];
        if (!c) continue;
        unsigned stid = 0, scia = 0; const char* nm = "?";
        if (!ppu_prof_snapshot((int)tid - 1, &stid, &scia, &nm)) nm = tid == 1 ? "main" : "(gone)";
        uint32_t sp = (uint32_t)c->gpr[1];
        fprintf(stderr, "[lbp2-stall] tid %u '%s' sc %u callsite 0x%08X lr 0x%08X ctr 0x%08X sp 0x%08X "
                "r3 %08X r4 %08X r5 %08X r6 %08X r31 %08X\n",
                tid, nm, tid < 64 ? g_sc_inflight[tid] : 0u, g_stall_lr[tid], (uint32_t)c->lr,
                (uint32_t)c->ctr, sp, (uint32_t)c->gpr[3], (uint32_t)c->gpr[4], (uint32_t)c->gpr[5],
                (uint32_t)c->gpr[6], (uint32_t)c->gpr[31]);
        char line[512]; int n = 0;
        for (int f = 0; f < 24 && guest_ok(sp); f++) {
            uint32_t back = be32(sp + 4);              /* 64-bit back chain, low word */
            if (back <= sp || back - sp > 0x100000u || !guest_ok(back)) break;
            uint32_t saved = be32(back + 16 + 4);      /* caller frame's LR save doubleword */
            n += snprintf(line + n, sizeof line - n, " %08X", saved);
            if (n >= (int)sizeof line - 12) break;
            sp = back;
        }
        fprintf(stderr, "[lbp2-stall]   chain:%s\n", n ? line : " (none)");
        /* What r3 points at: for a thread blocked in sys_lwmutex_lock that is the lwmutex
         * (owner tid, then waiter, attribute, recursive count). */
        uint32_t r3 = (uint32_t)c->gpr[3];
        if (guest_ok(r3) && r3 < 0x40000000u)
            fprintf(stderr, "[lbp2-stall]   *r3: %08X %08X %08X %08X\n", be32(r3), be32(r3 + 4),
                    be32(r3 + 8), be32(r3 + 12));
    }
}

/* 2c. LBP2_FRAME_STALL_MS=<n>: the same dump when no flip has come for n ms after the first 300
 *     flips (once per stalled frame, at most 10 per run). For the in-level near-freeze
 *     (2026-11-17: 1-7 fps for ~50 s, frames ~2 s apart, background threads running normally). */
static void* frame_stall_watch(void*) {
    const unsigned lim = (unsigned)atoi(getenv("LBP2_FRAME_STALL_MS"));
    unsigned last = 0, still = 0, dumps = 0; bool fired = false;
    for (unsigned ms = 0; dumps < 10; ms += 50) {
        usleep(50000);
        unsigned f = cellGcm_flip_request_count();
        if (f != last) { last = f; still = 0; fired = false; continue; }
        still += 50;
        if (f < 300 || fired || still < lim) continue;
        fired = true; dumps++;
        char what[64]; snprintf(what, sizeof what, "flip %u for %u ms", f, still);
        stall_dump(ms / 1000, what);
    }
    return nullptr;
}

__attribute__((constructor)) static void start_progress() {
#ifdef LBP2_SPU_LS_NO_DIAG
    /* The lifted SPU code is built with SPU_LS_NO_DIAG (CMake LBP2_SPU_LS_DIAG=OFF). */
    static const char* const vars[] = {"SPU_LS_WATCH", "SPU_LS_LOWREAD", "SPU_SMC_WATCH", "SPU_WWS_PROBE"};
    for (const char* v : vars)
        if (getenv(v))
            fprintf(stderr, "[lbp2-local] %s is set, but the lifted SPU code has no LS diagnostics "
                    "gate: rebuild with -DLBP2_SPU_LS_DIAG=ON to see its lqd/stqd\n", v);
#endif
    pthread_t th;
    if (pthread_create(&th, nullptr, progress, nullptr) == 0) pthread_detach(th);
    if (getenv("LBP2_FRAME_STALL_MS") && pthread_create(&th, nullptr, frame_stall_watch, nullptr) == 0)
        pthread_detach(th);
}

/* 7. LBP2_NO_RASTER=1: skip the headless null backend's CPU rasterizer. On Linux the
 *    runtime's "null" backend fills every triangle and decodes every texture on the
 *    CPU (a correctness probe, rsx_null_backend.c). With nothing to display that only
 *    slows the RSX thread, and the main loop waits for it in cellGcmGetFlipStatus
 *    (0x5DE684 polls it with usleep(300)). present() stays, so flips still complete.
 *    Linked with -Wl,--wrap=rsx_null_backend_init. The struct mirrors rsx_backend in
 *    libs/video/rsx_commands.h (field order matters). */
struct lbp2_rsx_backend {
    void* userdata;
    void* init; void* shutdown; void* begin_frame; void* end_frame; void* present;
    void* set_render_target; void* set_viewport; void* set_blend; void* set_depth_stencil;
    void* set_color_mask; void* set_alpha_test; void* set_shader; void* set_vertex_attribs;
    void (*clear)(void*, uint32_t, uint32_t, float, uint8_t);
    void (*draw_arrays)(void*, uint32_t, uint32_t, uint32_t);
    void (*draw_indexed)(void*, uint32_t, uint32_t, uint32_t);
    void* bind_texture;
};
extern "C" int __real_rsx_null_backend_init(uint32_t w, uint32_t h, const char* title);
extern "C" lbp2_rsx_backend* rsx_get_backend(void);
static void norast_clear(void*, uint32_t, uint32_t, float, uint8_t) {}
static void norast_draw(void*, uint32_t, uint32_t, uint32_t) {}
extern "C" int __wrap_rsx_null_backend_init(uint32_t w, uint32_t h, const char* title) {
    int rc = __real_rsx_null_backend_init(w, h, title);
    const char* e = getenv("LBP2_NO_RASTER");
    lbp2_rsx_backend* b = rc == 0 && e && *e == '1' ? rsx_get_backend() : nullptr;
    if (b) {
        b->clear = norast_clear;
        b->draw_arrays = norast_draw;
        b->draw_indexed = norast_draw;
        b->bind_texture = nullptr;
        b->set_vertex_attribs = nullptr;
        printf("[lbp2-local] LBP2_NO_RASTER: null backend draws/clears/textures disabled\n");
    }
    return rc;
}

/* 8. LBP2_CRASH_BT=1: on a fatal SIGSEGV/SIGBUS, print the fault address, rip, the thread
 *    name and a raw backtrace to stderr, then let the crash proceed. The Vulkan build
 *    crashes intermittently at the level transition and not under gdb (timing). Installed
 *    from a constructor, i.e. before the runtime's guest-pointer trap, which chains to
 *    the previous handler, so this runs after it. Addresses are printed raw together with
 *    this handler's own address: subtract to get offsets for `nm -n` / addr2line. */
#include <csignal>
#include <execinfo.h>
#include <ucontext.h>
static void lbp2_crash_bt(int sig, siginfo_t* si, void* uc) {
    char name[32] = "?";
    pthread_getname_np(pthread_self(), name, sizeof name);
    const ucontext_t* u = (const ucontext_t*)uc;
    dprintf(2, "[lbp2-crash] signal %d addr=%p rip=%llx rsp=%llx thread='%s' handler=%p\n",
            sig, si ? si->si_addr : nullptr,
            u ? (unsigned long long)u->uc_mcontext.gregs[REG_RIP] : 0ull,
            u ? (unsigned long long)u->uc_mcontext.gregs[REG_RSP] : 0ull,
            name, (void*)&lbp2_crash_bt);
    void* fr[64];
    int n = backtrace(fr, 64);
    for (int i = 0; i < n; i++) dprintf(2, "[lbp2-crash]   #%d %p\n", i, fr[i]);
    struct sigaction dfl;
    memset(&dfl, 0, sizeof dfl);
    dfl.sa_handler = SIG_DFL;
    sigemptyset(&dfl.sa_mask);
    sigaction(sig, &dfl, nullptr);   /* the faulting instruction re-runs and the process dies */
}
__attribute__((constructor)) static void lbp2_install_crash_bt() {
    const char* e = getenv("LBP2_CRASH_BT");
    if (!e || *e != '1') return;
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = lbp2_crash_bt;
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGSEGV, &sa, nullptr);
    sigaction(SIGBUS, &sa, nullptr);
    { void* warm[2]; backtrace(warm, 2); }   /* load libgcc now, not inside the handler */
}

/* 11. LBP2_FIFO_SPIN_MAX=<n>: cap the edge spin in the game's RSX-backlog query to n usleeps.
 *     0x5DE6FC reads the GCM control register and, before returning put - get, loops up to
 *     1001 x usleep(30) (r30 = 0x3E9, LR 0x5DE71C) while get or put is within 4 KB of either
 *     end of the 4 MB ring. Its caller is the game's command-buffer callback (0x5DEAA8, at
 *     every 32 KB segment end). When the RSX has caught up and parks on the 0x43-0x45
 *     acquire just after a ring wrap (get < 0x1000), the main thread hits the next segment
 *     end before it kicks the job that writes that label, so it spins the whole 1001
 *     iterations (~500 ms with host usleep granularity) and the RSX waits with it. On
 *     hardware the RSX runs far enough behind that this never lines up; with LBP2_NO_MLAA
 *     it does (runs skip-4, stall-1: 506 ms stalls every ~15 s, ~4% of the frames' time).
 *     The hook lowers the loop counter at the loop's usleep, so the spin ends after n more
 *     iterations; the query then returns the (exact: the RSX is parked) put - get as usual.
 *     Linked with -Wl,--wrap=lv2_syscall. */
extern "C" void __real_lv2_syscall(ppu_context* ctx);
static int g_fifo_spin_max = -1;
extern "C" void __wrap_lv2_syscall(ppu_context* ctx) {
    if (ctx->gpr[11] == 0x8D && (uint32_t)ctx->lr == 0x005DE71Cu) {
        if (g_fifo_spin_max < 0) {
            const char* e = getenv("LBP2_FIFO_SPIN_MAX");
            g_fifo_spin_max = e && *e ? atoi(e) : 0;
            if (g_fifo_spin_max > 0)
                fprintf(stderr, "[lbp2-local] LBP2_FIFO_SPIN_MAX=%d: RSX backlog query spin capped\n", g_fifo_spin_max);
        }
        if (g_fifo_spin_max > 0 && ctx->gpr[30] > (uint64_t)g_fifo_spin_max) {
            static unsigned n;
            if (n++ < 8)
                fprintf(stderr, "[lbp2-local] FIFO backlog spin capped (get 0x%08X put 0x%08X)\n",
                        be32(0x20002000u + 4), be32(0x20002000u));
            ctx->gpr[30] = (uint64_t)g_fifo_spin_max;
        }
    }
    __real_lv2_syscall(ctx);
}

/* 12. LBP2_GCOV_DUMP_AT=<s>: PGO training helper. When the binary is built with
 *     -fprofile-generate (LBP2_SPU_EXTRA_FLAGS), write the profile at <s> seconds:
 *     run.sh ends the game with SIGKILL, so the at-exit write never happens. */
extern "C" void __gcov_dump(void) __attribute__((weak));
static void* gcov_dump_thread(void* arg) {
    const unsigned s = (unsigned)(uintptr_t)arg;
    sleep(s);
    fprintf(stderr, "[lbp2-local] LBP2_GCOV_DUMP_AT: writing the profile at %u s\n", s);
    __gcov_dump();
    fprintf(stderr, "[lbp2-local] LBP2_GCOV_DUMP_AT: profile written\n");
    return nullptr;
}
__attribute__((constructor)) static void lbp2_gcov_dump_start() {
    const char* e = getenv("LBP2_GCOV_DUMP_AT");
    if (!e || !*e || !__gcov_dump) return;
    pthread_t th;
    if (pthread_create(&th, nullptr, gcov_dump_thread, (void*)(uintptr_t)atoi(e)) == 0) pthread_detach(th);
}

/* 13. LBP2_GATE_WAIT_MS=<n> (default 0 = off; opt-in): hold the RSX walker on a gate user command until
 *     the main thread has armed that gate. Each frame main pushes the post-effect SPU jobs behind a
 *     gate (0x5E8E88: push, then sth 1 at gate+4) and the GCM user handler releases it when the RSX
 *     retires 0x4000xxxx (gate 1) / 0xC000xxxx (gate 2) (0x2B1CA8 -> 0x5EBBC8: sth 0, then the
 *     workload's readyCount). Main arms only ~5-10 ms before the walker gets there (sometimes 1 ms):
 *     when the walker wins, the release finds the gate still 0, main's arm closes it for good, the
 *     jobs never run, and the RSX sits on their "done" label (0x43/0x44/0x4E-0x50) -- the 2 s
 *     GCM_SEMA_ACQUIRE_MS give-up at best, a frozen game at worst (2026-11-22, notes/boot-progress.md).
 *     Gates at *(TOC2+0x2F98), stride 0x404, u16 count at +4. After 3 timeouts in a row the wait
 *     stays off until a gate is found armed again (a scene that does not arm them pays nothing).
 *     It never fired in 8 runs and did not stop the freeze: the real cause is #15 (the arm itself
 *     publishes its barrier before closing it). Kept opt-in for diagnosis. */
extern "C" void (*g_gcm_user_cmd_retire_hook)(uint32_t cmd);
static unsigned g_gate_wait_ms;
static void gate_retire_hook(uint32_t cmd) {
    if (cmd == 0xF5AAC0DEu || !(cmd & 0x40000000u)) { if (g_ev_on) ev_add(2, cmd, 1); return; }
    static unsigned misses, waits, timeouts;
    const uint32_t gb = be32(0xC75A98u + 0x2F98u);
    if (!guest_ok(gb)) return;
    const uint32_t ga = gb + (1u + (cmd >> 31)) * 0x404u + 4u;
    auto armed = [ga] { return (vm_base[ga] | vm_base[ga + 1]) != 0; };
    if (armed()) { misses = 0; if (g_ev_on) ev_add(2, cmd, 1); return; }
    if (g_ev_on) ev_add(2, cmd, 0);
    if (misses >= 3 || !g_gate_wait_ms) return;
    const auto t0 = std::chrono::steady_clock::now();
    const auto lim = std::chrono::milliseconds(g_gate_wait_ms);
    while (!armed() && std::chrono::steady_clock::now() - t0 < lim) usleep(50);
    const long us = (long)std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now() - t0).count();
    if (armed()) {
        if (g_ev_on) ev_add(2, cmd, 3);
        misses = 0; waits++;
        if (waits <= 20 || (waits & 255) == 0)
            fprintf(stderr, "[lbp2-gate] 0x%08X: walker ahead of main, waited %ld us for the arm (#%u)\n",
                    cmd, us, waits);
    } else {
        misses++; timeouts++;
        if (timeouts <= 20 || (timeouts & 255) == 0)
            fprintf(stderr, "[lbp2-gate] 0x%08X: gate not armed after %u ms (timeout #%u%s)\n",
                    cmd, g_gate_wait_ms, timeouts, misses >= 3 ? ", waits off until a gate is armed" : "");
    }
}
__attribute__((constructor)) static void lbp2_gate_wait_start() {
    const char* e = getenv("LBP2_GATE_WAIT_MS");
    g_gate_wait_ms = e && *e ? (unsigned)atoi(e) : 0u;
    const char* s = getenv("LBP2_FRAME_STALL_MS");   /* call-site records: a few atomics per event */
    g_ev_on = s && atoi(s) > 0;
    const char* r = getenv("LBP2_EVRING");           /* opt-in: its 100 us poll thread hides the freeze */
    if (g_ev_on && r && *r == '1') { pthread_t th; if (pthread_create(&th, nullptr, ev_poll, nullptr) == 0) pthread_detach(th); }
    if (g_gate_wait_ms || g_ev_on) g_gcm_user_cmd_retire_hook = gate_retire_hook;
}

/* 14. With the stall dump on: record each gate arm (0x5E8E88, g = high word of r4) and each gate
 *     release that clears a gate (0x5EBBC8: r4 high word = g, its byte 5 = "clear the gate", r3 low
 *     word = list index; the ~20 kick-only calls per frame, byte 5 = 0, are not recorded)
 *     in the event ring, with the gate's u16 and the caller. Linked with --wrap for both (the calls
 *     come through the 0x7Axxxx stubs in another translation unit). */
static uint32_t gate_u16(uint32_t g) {
    const uint32_t gb = be32(0xC75A98u + 0x2F98u);
    if (!guest_ok(gb) || gb >= 0x40000000u || g > 8) return 0xFFFF;
    const uint32_t ga = gb + g * 0x404u + 4u;
    return (uint32_t)vm_base[ga] << 8 | vm_base[ga + 1];
}
/* 15. LBP2_ARM_ORDER (default 1; 0 = the game's own order): the gate arm, 0x5E8E88(r3, r4; g = high
 *     word of r4), does   n = 0;  0x5E8E0C: entry[0] = {count 0, wid, ready 8};  0x5E7CCC: push a
 *     "wait until entry[0] count == 0" header into the job list (publishing it) and n++;  then
 *     sth 1 at entry[0].   Between the push and the sth the barrier is visible with its count at 0:
 *     a policy module polling the list then passes it, and every job main pushes after it runs at
 *     once, before main has written the counts of the dependencies those jobs decrement (0x5E7D6C:
 *     count 1..5, then the matching wait header). Those decrements are lost, the counts never reach
 *     0, the lists stop, and the RSX waits for the label their last job writes: the Avalon-transition
 *     freeze (2026-11-22: entries left at 1 and 5 right after an arm, the jobs before the stuck
 *     header all done). On the console the window is a few instructions; here the host can deschedule
 *     the guest thread between the two stores while the PM threads poll at host speed. This runs the
 *     same three steps with the count stored before the push. */
void func_005E8E0C(ppu_context* ctx);
void func_005E7CCC(ppu_context* ctx);
extern "C" PPU_THREAD_LOCAL void (*g_trampoline_fn)(void*);
extern "C" int  spu_coh_is_reserved(uint32_t addr);
extern "C" void spu_lockline_lock(void);
extern "C" void spu_lockline_unlock(void);
extern "C" void spu_coh_notify_write(uint32_t addr);
static void drain_trampoline(ppu_context* c) {
    while (g_trampoline_fn) { void (*f)(void*) = g_trampoline_fn; g_trampoline_fn = nullptr; f(c); }
}
/* A PPU store an SPU reservation on the line must see (a PUTLLC compares the line under this lock). */
static void coh_store_be(uint32_t a, uint32_t v, unsigned n) {
    spu_lockline_lock();
    for (unsigned i = 0; i < n; i++) vm_base[a + i] = (uint8_t)(v >> (8 * (n - 1 - i)));
    if (spu_coh_is_reserved(a)) spu_coh_notify_write(a);
    spu_lockline_unlock();
}
static int g_arm_order = -1;
extern "C" void __real__Z13func_005E8E88P11ppu_context(ppu_context* c);
extern "C" void __wrap__Z13func_005E8E88P11ppu_context(ppu_context* c) {
    const uint32_t g = (uint32_t)(c->gpr[4] >> 32), lr = (uint32_t)c->lr;
    if (g_arm_order < 0) {
        const char* e = getenv("LBP2_ARM_ORDER");
        g_arm_order = !(e && *e == '0');
        fprintf(stderr, "[lbp2-local] LBP2_ARM_ORDER=%d: job-list gates %s\n", g_arm_order,
                g_arm_order ? "closed before their barrier is published" : "armed in the game's order");
    }
    if (g_ev_on) ev_add(3, (g & 0xFF) | gate_u16(g) << 8, lr);
    const uint32_t gb = be32(0xC75A98u + 0x2F98u);
    if (!g_arm_order || g > 8 || !guest_ok(gb) || gb >= 0x40000000u) {
        __real__Z13func_005E8E88P11ppu_context(c);
    } else {
        const uint64_t r3 = c->gpr[3], r4 = c->gpr[4];
        const uint32_t sb = gb + g * 0x404u;
        coh_store_be(sb, 0, 4);                                  /* n = 0 */
        c->gpr[3] = r3; c->gpr[4] = r4; c->lr = 0x005E8EF0u;     /* entry[0] = {0, wid, 8} */
        func_005E8E0C(c); drain_trampoline(c);
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        coh_store_be(sb + 4, 1, 2);                              /* closed ... */
        __atomic_thread_fence(__ATOMIC_SEQ_CST);
        c->gpr[3] = r3; c->gpr[4] = r4; c->lr = 0x005E8F10u;     /* ... before its wait header goes in */
        func_005E7CCC(c); drain_trampoline(c);
        c->lr = lr;
    }
    if (g_ev_on) ev_add(4, (g & 0xFF) | gate_u16(g) << 8, lr);
}
extern "C" void __real__Z13func_005EBBC8P11ppu_context(ppu_context* c);
extern "C" void __wrap__Z13func_005EBBC8P11ppu_context(ppu_context* c) {
    const uint32_t g = (uint32_t)(c->gpr[4] >> 32), flag = ((uint32_t)c->gpr[4] >> 16) & 0xFF;
    const uint32_t li = (uint32_t)c->gpr[3], lr = (uint32_t)c->lr;
    if (g_ev_on && flag) ev_add(5, (g & 0xFF) | 1u << 8 | (li & 0xFF) << 12 | (gate_u16(g) & 0xFFF) << 20, lr);
    __real__Z13func_005EBBC8P11ppu_context(c);
}
