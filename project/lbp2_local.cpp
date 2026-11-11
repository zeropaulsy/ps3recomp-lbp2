/* Local LBP2 bring-up shims. Lives only in this bring-up project copy, not in ps3recomp.
 *
 * 1. cellNetCtlGetState: the runtime's offline path deliberately returns NOT_INITIALIZED
 *    (an LBP1 rule). LBP2's net helper treats that as fatal, but accepts what a real
 *    console reports with no link: CELL_OK and state=Disconnected. The runtime has already
 *    written Disconnected by then, so only the return value changes.
 * 2. A progress logger for the game's init-step table (read-only).
 * 3. A UDP loopback for sys_net (see below). */
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

static void* progress(void*) {
    static const uint32_t HEAD_SLOT = 0xC65AF0u - 0x74ECu;
    char last[128] = "";
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
        if (strcmp(cur, last) || t % 60 == 0) {
            fprintf(stderr, "[lbp2-local] t=%us init at: %s\n", t, cur);
            strcpy(last, cur);
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

extern "C" void __wrap_ppu_sysprx_register(void) {
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

__attribute__((constructor)) static void start_progress() {
    pthread_t th;
    if (pthread_create(&th, nullptr, progress, nullptr) == 0) pthread_detach(th);
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
