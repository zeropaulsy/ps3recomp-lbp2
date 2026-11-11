import gdb
# cellFiber probe: who sends/waits for fiber signals (per host thread and fiber), and at the
# SNAP SIGINT the state of every fiber in the runtime's s_fibers list (libs/spurs/cellFiber.c).
# Offsets for this build (x86_64 glibc): Fiber.ea 16, opd 20, state 56, signal_pending 60,
# join_ea 64, ctx 1056; ppu_context gpr[i] 8*i, lr 1032, cia 1064.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')

STATES = ['READY', 'RUNNING', 'WAIT_SIGNAL', 'WAIT_JOIN', 'DONE']
inf = gdb.selected_inferior()
def u32(a): return int.from_bytes(inf.read_memory(a, 4).tobytes(), 'little')
def u64(a): return int.from_bytes(inf.read_memory(a, 8).tobytes(), 'little')
def lwp(): return gdb.selected_thread().ptid[1]
def guest_frames(n=8):
    out = []; f = gdb.newest_frame()
    while f is not None and len(out) < n:
        nm = f.name() or ''
        if nm.startswith('func_') or nm.startswith('_Z13func_'):
            out.append(nm.replace('_Z13func_', '').replace('func_', '').split('(')[0].replace('P11ppu_context', ''))
        f = f.older()
    return ' < '.join(out)

seen = {}
class CallBP(gdb.Breakpoint):
    def __init__(self, sym, tag):
        super().__init__(sym); self.tag = tag
    def stop(self):
        ea = int(gdb.parse_and_eval('(unsigned int)$rdi')) if self.tag == 'send' else 0
        k = (self.tag, lwp(), ea); seen[k] = seen.get(k, 0) + 1
        if seen[k] <= 3 or seen[k] in (10, 100, 1000, 10000):
            main = ' MAIN' if lwp() == inf.pid else ''
            print('[fib] %s lwp=%d%s fiber=0x%08X #%d  %s' % (self.tag, lwp(), main, ea, seen[k], guest_frames()), flush=True)
        return False

CallBP('cellFiberPpuSendSignal', 'send')
CallBP('cellFiberPpuWaitSignal', 'wait')
CallBP('cellFiberPpuYield', 'yield')
CallBP('cellFiberPpuJoinFiber', 'join')
CallBP('cellFiberPpuCreateFiber', 'create')
CallBP('cellFiberPpuExit', 'exit')
gdb.execute('run')

print('[fib] ==== fiber dump at SNAP ====')
p = u64(int(gdb.parse_and_eval('(unsigned long long)&s_fibers')))
n = 0
while p and n < 64:
    st = u32(p + 56); c = p + 1056
    print('[fib] fiber ea=0x%08X opd=0x%08X state=%s sigpend=%d join=0x%08X  guest lr=0x%08X cia=0x%08X r1=0x%08X r3=0x%X' % (
        u32(p + 16), u32(p + 20), STATES[st] if st < 5 else st, u32(p + 60), u32(p + 64),
        u64(c + 1032) & 0xffffffff, u64(c + 1064) & 0xffffffff, u64(c + 8) & 0xffffffff, u64(c + 24)), flush=True)
    p = u64(p); n += 1
print('[fib] totals:', sorted(((k[0], k[1] == inf.pid, hex(k[2])), v) for k, v in seen.items()))
gdb.execute('thread apply 1 bt 12')
gdb.execute('kill')
