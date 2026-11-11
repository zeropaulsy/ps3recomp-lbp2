import gdb, struct
# Step 70 probe: after the SNAP SIGINT, trace action 3 of the network state machine:
# sceNpUtilCmpNpId args + 36-byte NpIds, and results of func_001F0D58 / func_001F4D10.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('run')
inf = gdb.selected_inferior()
B = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
def rd(a, n): return bytes(inf.read_memory(B + a, n))
def u32(a): return struct.unpack('>I', rd(a, 4))[0]
def gpr(ctx, i): return struct.unpack('<Q', bytes(inf.read_memory(ctx + 8*i, 8)))[0]
hits = {}
LIMIT = 6
class Fin(gdb.FinishBreakpoint):
    def __init__(self, name, ctx):
        super().__init__(gdb.newest_frame(), internal=True); self.name = name; self.ctx = ctx
    def stop(self):
        try:
            v = int(gdb.parse_and_eval('$rax')) if self.ctx is None else gpr(self.ctx, 3)
            print('RET %s r3=%#x' % (self.name, v & 0xffffffff))
        except Exception as e: print('RET err', e)
        return False
    def out_of_scope(self): pass
class Bp(gdb.Breakpoint):
    def __init__(self, spec, name):
        super().__init__(spec, internal=True); self.name = name
    def stop(self):
        n = hits.get(self.name, 0) + 1; hits[self.name] = n
        if self.name == 'cmp':
            if n > 400: return False
            a = int(gdb.parse_and_eval('$rdi'))
            if a not in (0xcbd7f0,): return False
            a = int(gdb.parse_and_eval('$rdi')); b = int(gdb.parse_and_eval('$rsi'))
            print('CMP rdi=%#x rsi=%#x' % (a, b))
            for x in (a, b):
                g = x - B if x > B else x
                try: print('   npid@%08x %s' % (g, rd(g, 36).hex()))
                except Exception as e: print('   err', e)
            Fin('cmp', None)
        else:
            ctx = int(gdb.parse_and_eval('$rdi'))
            lr = struct.unpack('<Q', bytes(inf.read_memory(ctx + 1032, 8)))[0]
            if self.name == 'f25bfc' and lr == 0x25ca4: return False
            k = (self.name, lr); hits[k] = hits.get(k, 0) + 1
            if hits[k] > LIMIT: return False
            if self.name == 'exec':
                o = gpr(ctx, 3) & 0xffffffff
                print('EXEC obj=%08x 16f0=%s npid@b0=%s' % (o, rd(o + 0x16f0, 0x20).hex(), rd(o + 0xb0, 36).hex()))
                return False
            print('CALL %s r3=%#x r4=%#x lr=%#x' % (self.name, gpr(ctx, 3), gpr(ctx, 4),
                  struct.unpack('<Q', bytes(inf.read_memory(ctx + 8*32 + 8*32 + 16*32 + 8, 8)))[0]))
            Fin(self.name, ctx)
        return False
Bp('sceNpUtilCmpNpId', 'cmp')
Bp('_Z13func_001F0D58P11ppu_context', 'f1f0d58')
Bp('_Z13func_001F4D10P11ppu_context', 'f1f4d10')
Bp('_Z13func_00025BFCP11ppu_context', 'f25bfc')
Bp('_Z13func_0021DD40P11ppu_context', 'exec')
TOC = 0xC65AF0
mgr = u32(TOC - 0x5a4)
print('MGR(toc-0x5a4)=%08x +0x3c=%08x' % (mgr, u32(mgr + 0x3c)))
print('MGR +0x118 npid', rd(mgr + 0x118, 36).hex())
gdb.execute('continue')
gdb.execute('kill')
