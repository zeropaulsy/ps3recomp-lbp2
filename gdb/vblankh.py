import gdb, time
# LBP2 vblank handler 0x5DCB0C: counter *[TOC+0x2B1C], flag byte *[TOC+0x2B20], interval *[TOC+0x2B28].
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
inf = gdb.selected_inferior(); T0 = time.time()
TOC = None
def B(): return int(gdb.parse_and_eval('(unsigned long long)vm_base'))
def r32(a): return int.from_bytes(inf.read_memory(B() + a, 4).tobytes(), 'big')
def r8(a): return int.from_bytes(inf.read_memory(B() + a, 1).tobytes(), 'big')
n = [0]; last = [0]
class H(gdb.Breakpoint):
    def stop(self):
        global TOC
        if TOC is None: TOC = int(gdb.parse_and_eval("*(unsigned long long*)($rdi+16)")) & 0xffffffff; print("[vbh] toc=0x%X" % TOC, flush=True)
        n[0] += 1
        now = time.time() - T0
        if n[0] <= 12 or now - last[0] >= 2.0:
            last[0] = now
            pc, pf, pi = r32(TOC + 0x2B1C), r32(TOC + 0x2B20), r32(TOC + 0x2B28)
            lab = r32(r32(TOC + 0x2B24) + 0x104)
            print('[vbh] t=%.1f call#%d counter=%d flag=%d interval=%d label41=0x%08X r3(vcount)=%d' % (
                now, n[0], r32(pc), r8(pf), r32(pi), r32(lab),
                int(gdb.parse_and_eval('*(unsigned long long*)($rdi+24)'))), flush=True)
        return False
H('_Z13func_005DCB0CP11ppu_context')
gdb.execute('run')
gdb.execute('kill')
