import gdb
# Why do pm_wwsjob lanes spin at LS 0x2554 (AllocateJob's job-header GET loop)?
# Breaks on spu_halt when the repeat watchdog halts image 1 at pc 0x2554 and dumps the
# registers AllocateJob uses, its LS state and the guest memory it reads.
# spu_context offsets (runtime/spu/spu_context.h): gpr 0 (16 B each), ls ptr 264192,
# pc 264200, image_id 264220, policy_mode 265856.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
MAXHITS = 4
hits = [0]
inf = lambda: gdb.selected_inferior()
def u32(a): return int.from_bytes(bytes(inf().read_memory(a, 4)), 'little')
def u64(a): return int.from_bytes(bytes(inf().read_memory(a, 8)), 'little')
def hexdump(base, n):
    b = bytes(inf().read_memory(base, n))
    return '\n'.join('      +%03X: %s' % (o, ' '.join(b[o+i:o+i+4].hex() for i in range(0, 16, 4))) for o in range(0, n, 16))

class HaltBP(gdb.Breakpoint):
    def stop(self):
        ctx = int(gdb.parse_and_eval('(unsigned long long)$rdi'))
        img = u32(ctx + 264220); pc = u32(ctx + 264200) & 0x3FFFF
        if img != 1 or pc != 0x2554: return False
        hits[0] += 1
        if hits[0] > MAXHITS: return False
        ls = u64(ctx + 264192); vb = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
        g = lambda r: u32(ctx + 16*r)        # preferred slot
        lsw = lambda a: int.from_bytes(bytes(inf().read_memory(ls + a, 4)), 'big')
        print('[wwsspin] hit %d spuNum=%d wid=%d' % (hits[0], lsw(0x1C8), lsw(0x1DC)), flush=True)
        print('[wwsspin] r3=%05X r50=%05X r52(lineEA)=%08X r54=%08X r56=%08X r58=%05X r60=%08X r62=%08X r70(hdrEA)=%08X r68=%08X r57=%08X'
              % tuple(g(r) for r in (3, 50, 52, 54, 56, 58, 60, 62, 70, 68, 57)), flush=True)
        print('[wwsspin] LS 0x14C0..0x1500 (hdrEA cache, line q0 cache, 0x14E0 dep, 0x14F0 dep EA):\n' + hexdump(ls + 0x14C0, 0x40), flush=True)
        print('[wwsspin] LS line copy @r50 (128):\n' + hexdump(ls + (g(50) & 0x3FFF0), 0x80), flush=True)
        print('[wwsspin] LS header buffer 0xD00 (128):\n' + hexdump(ls + 0xD00, 0x80), flush=True)
        le = g(52) & ~0x7F
        print('[wwsspin] RAM line @%08X (128):\n' % le + hexdump(vb + le, 0x80), flush=True)
        he = g(70) & ~0x7F
        print('[wwsspin] RAM header @%08X (128):\n' % he + hexdump(vb + he, 0x80), flush=True)
        return False

HaltBP('spu_halt')
gdb.execute('run')
gdb.execute('kill')
