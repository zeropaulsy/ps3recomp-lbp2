import gdb, struct
# Log every network state-machine transition (func_001EA4AC = SetState(obj, state); func_001F0E38 = NextStep)
# from boot, with the guest LR and the state/step at the time. Stops printing after 300 hits.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
inf = gdb.selected_inferior()
def gpr(ctx, i): return struct.unpack('<Q', bytes(inf.read_memory(ctx + 8*i, 8)))[0]
n = [0]
class Bp(gdb.Breakpoint):
    def __init__(self, spec, name):
        super().__init__(spec, internal=True); self.name = name
    def stop(self):
        n[0] += 1
        if n[0] > 300: return False
        B = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
        ctx = int(gdb.parse_and_eval('$rdi'))
        o = gpr(ctx, 3) & 0xffffffff
        lr = struct.unpack('<Q', bytes(inf.read_memory(ctx + 1032, 8)))[0]
        st, step = struct.unpack('>II', bytes(inf.read_memory(B + o + 0x16f4, 8)))
        print('%s obj=%08x r4=%d lr=%#x cur state=%d step=%d' % (self.name, o, gpr(ctx, 4) & 0xffffffff, lr, st, step), flush=True)
        return False
Bp('_Z13func_001EA4ACP11ppu_context', 'SETSTATE')
Bp('_Z13func_001F0E38P11ppu_context', 'NEXTSTEP')
gdb.execute('run')
gdb.execute('kill')
