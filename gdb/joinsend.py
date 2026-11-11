import gdb, struct
# At step 4 of party op CREATE (action 2, REQUEST_JOIN_TO_NEW_PLAYER_TO_FOLLOW): log the
# connection lookup func_00247608 and the send func_00248354 called from 0x21F10C / 0x21F184.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
inf = gdb.selected_inferior()
def gpr(ctx, i): return struct.unpack('<Q', bytes(inf.read_memory(ctx + 8*i, 8)))[0]
def lr(ctx): return struct.unpack('<Q', bytes(inf.read_memory(ctx + 1032, 8)))[0]
class Fin(gdb.FinishBreakpoint):
    def __init__(self, name, ctx):
        super().__init__(gdb.newest_frame(), internal=True); self.name = name; self.ctx = ctx
    def stop(self):
        print('RET %s r3=%#x' % (self.name, gpr(self.ctx, 3) & 0xffffffff), flush=True); return False
    def out_of_scope(self): pass
class Bp(gdb.Breakpoint):
    def __init__(self, spec, name, want):
        super().__init__(spec, internal=True); self.name = name; self.want = want
    def stop(self):
        ctx = int(gdb.parse_and_eval('$rdi'))
        if lr(ctx) not in self.want: return False
        print('CALL %s r3=%#x r4=%#x r5=%#x lr=%#x' % (self.name, gpr(ctx,3), gpr(ctx,4), gpr(ctx,5), lr(ctx)), flush=True)
        Fin(self.name, ctx); return False
Bp('_Z13func_00247608P11ppu_context', 'findconn', (0x21f110,))
Bp('_Z13func_00248354P11ppu_context', 'send', (0x21f188,))
gdb.execute('run')
gdb.execute('kill')
