import gdb, threading, os, time, signal, re
# Main-thread sync-point wait (0x5E3D20 loops `while(!F72AD00(ent->ptr, 3, ent->val)) usleep`).
# 0x72AD00(p, k, v): slot = *(u32*)p + 0x40 + k*16; true when min(u16 at slot+2..+0xE) >= v.
# After SNAP's first SIGINT, every SW_GAP seconds arm a one-shot breakpoint on 0x72AD00 and
# print the awaited value, all 8 slots (8 x u16 each) and the guest call chain.
# Env: SW_COUNT (default 12), SW_GAP (default 3).
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
COUNT = int(os.environ.get('SW_COUNT', '12')); GAP = float(os.environ.get('SW_GAP', '3'))

def rd(ctx, i): return int(gdb.parse_and_eval('*(unsigned long long*)(%d+%d)' % (ctx, 8*i)))
def mem(ea, n):
    B = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
    return bytes(gdb.selected_inferior().read_memory(B + ea, n))
def be16(b, o): return (b[o] << 8) | b[o+1]
def be32(b, o): return int.from_bytes(b[o:o+4], 'big')

class BP(gdb.Breakpoint):
    def stop(self):
        ctx = int(gdb.parse_and_eval('(unsigned long long)$rdi'))
        p, k, v = rd(ctx, 3) & 0xffffffff, rd(ctx, 4) & 0xffffffff, rd(ctx, 5) & 0xffff
        base = be32(mem(p, 4), 0)
        print('[syncwait] t=%.0f p=%08X base=%08X k=%d want=%d ent(r31)=%08X usleep(r28)=%d'
              % (time.time() - T0, p, base, k, v, rd(ctx, 31) & 0xffffffff, rd(ctx, 28) & 0xffffffff), flush=True)
        s = mem(base, 0xC0)
        print('[syncwait] head: ' + s[:0x40].hex(), flush=True)
        for i in range(8):
            o = 0x40 + 16*i
            print('[syncwait] slot%d: %s' % (i, ' '.join('%5d' % be16(s, o + 2*j) for j in range(8))), flush=True)
        out = gdb.execute('bt 20', to_string=True)
        print('[syncwait] chain: ' + ' < '.join(re.findall(r'func_([0-9A-F]{8})', out)), flush=True)
        self.enabled = False
        return True

T0 = time.time()
bp = BP('_Z13func_0072AD00P11ppu_context'); bp.enabled = False
gdb.execute('run')
pid = gdb.selected_inferior().pid
for i in range(COUNT):
    bp.enabled = True
    gdb.execute('continue')          # stops in BP.stop
    threading.Thread(target=lambda: (time.sleep(GAP), os.kill(pid, signal.SIGINT)), daemon=True).start()
    gdb.execute('continue')          # stops on the SIGINT
gdb.execute('kill')
