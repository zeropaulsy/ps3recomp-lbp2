import gdb
# Probe for the 60 MB fixed-pool OOM: guest args of 16 MB requests into the pool
# allocators, and the host backtrace (guest call chain) when the game reports it.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)

SZ = 0x1000000
hits = {}

def rd(ctx, i):
    return int(gdb.parse_and_eval('*(unsigned long long*)(%d+%d)' % (ctx, 8*i)))

class AllocBP(gdb.Breakpoint):
    def __init__(self, fn):
        sym = '_Z13func_%08XP11ppu_context' % fn
        super().__init__(sym)
        self.fn = fn
        self.condition = ' || '.join('*(unsigned long long*)($rdi+%d)==%d' % (8*i, SZ) for i in (4,5,6,7))
    def stop(self):
        ctx = int(gdb.parse_and_eval('(unsigned long long)$rdi'))
        lr = rd(ctx, 1032//8) & 0xffffffff
        k = (self.fn, lr); hits[k] = hits.get(k, 0) + 1
        if hits[k] <= 4:
            g = ' '.join('r%d=%08X' % (i, rd(ctx, i) & 0xffffffff) for i in range(3, 11))
            print('[pooloom] fn=%08X lr=%08X #%d %s' % (self.fn, lr, hits[k], g), flush=True)
            gdb.execute('bt 40')
        return False

class ChainBP(gdb.Breakpoint):
    def stop(self):
        print('[pooloom] ---- ppu_log_host_chain hit', flush=True)
        gdb.execute('bt 60')
        return False

AllocBP(0xAEAD88)
AllocBP(0xAE9060)
ChainBP('ppu_log_host_chain')
gdb.execute('run')
gdb.execute('kill')
