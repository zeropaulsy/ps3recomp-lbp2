import gdb, struct
# 2026-11-20: who writes /dev_hdd1/cache/BCUS98245/output/temp and how. Logs every cellFsWrite /
# cellFsAioWrite / cellFsAllocateFileAreaWithoutZeroFill (ppu_fs.cpp handlers): fd, size, guest buffer,
# guest LR, bytes written, and whether the source buffer holds a >=256-byte zero run at write time.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGUSR1','SIGUSR2','SIGPIPE','SIGILL','SIGFPE','SIGINT','SIGSEGV','SIGBUS'):
    gdb.execute('handle %s nostop noprint pass' % s)
inf = [None]; B = [None]; cnt = {}
def mem(a, n): return bytes(inf[0].read_memory(B[0] + a, n))
def g(rdi, i): return struct.unpack('<Q', bytes(inf[0].read_memory(rdi + 8 * i, 8)))[0]
def lr(rdi): return struct.unpack('<Q', bytes(inf[0].read_memory(rdi + 1032, 8)))[0] & 0xffffffff
def zrun(buf, n):
    try: d = mem(buf, n)
    except gdb.MemoryError: return 'unreadable'
    k = d.find(bytes(256))
    if k < 0: return 'nozero'
    e = k
    while e < len(d) and d[e] == 0: e += 1
    return 'ZERO@+%d len %d' % (k, e - k)
class Fin(gdb.FinishBreakpoint):
    def __init__(self, tag, nptr):
        super().__init__(gdb.newest_frame(), internal=True); self.tag = tag; self.nptr = nptr
    def stop(self):
        try: n = struct.unpack('>Q', mem(self.nptr, 8))[0] if self.nptr else -1
        except gdb.MemoryError: n = -2
        print('[fsw] %s -> wrote %d' % (self.tag, n), flush=True); return False
    def out_of_scope(self): pass
class W(gdb.Breakpoint):
    def __init__(self, loc, kind): super().__init__(loc); self.kind = kind
    def stop(self):
        if inf[0] is None:
            inf[0] = gdb.selected_inferior(); B[0] = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
        rdi = int(gdb.parse_and_eval('(unsigned long long)$rdi'))
        t = gdb.selected_thread().name
        if self.kind == 'w':
            fd, buf, n, nptr = g(rdi, 3) & 0xffffffff, g(rdi, 4) & 0xffffffff, g(rdi, 5), g(rdi, 6) & 0xffffffff
            tag = 'write fd=%d buf=0x%08x n=%d lr=0x%08x thr=%s %s' % (fd, buf, n, lr(rdi), t, zrun(buf, min(n, 1 << 20)))
            print('[fsw] ' + tag, flush=True)
            if nptr: Fin(tag[:40], nptr)
        elif self.kind == 'a':
            aio = g(rdi, 3) & 0xffffffff
            fd, off, buf, n = struct.unpack('>IxxxxQIxxxxQ', mem(aio, 0x20))
            print('[fsw] aiowrite fd=%d off=0x%x buf=0x%08x n=%d lr=0x%08x thr=%s %s' % (fd, off, buf, n, lr(rdi), t,
                  zrun(buf, min(n, 1 << 20))), flush=True)
        else:
            print('[fsw] allocate r3=0x%x r4=0x%x lr=0x%08x' % (g(rdi, 3), g(rdi, 4), lr(rdi)), flush=True)
        return False
W('cellFsWrite(ppu_context*)', 'w'); W('cellFsAioWrite(ppu_context*)', 'a')
W('cellFsAllocateFileAreaWithoutZeroFill(ppu_context*)', 'z')
gdb.execute('run')
