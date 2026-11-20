import gdb, os, struct
# 2026-11-20: the LUT-build "43 s crash" starts with the game's libpng failing (incorrect data check)
# and calling the game's abort routine func_00781F14 (prints a back-chain trace via tty, exit(1)).
# Break there with every thread stopped: print the guest registers and the guest back chain, and
# copy guest main memory + the stack region into PNGDUMP (sparse files, one per range) for offline
# work. Then kill. env: PNGDUMP (fresh directory).
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
gdb.execute('set breakpoint pending on')
for s in ('SIGUSR1','SIGUSR2','SIGPIPE','SIGILL','SIGFPE','SIGINT','SIGSEGV','SIGBUS'):
    gdb.execute('handle %s nostop noprint pass' % s)
D = os.environ['PNGDUMP']
RANGES = [(0x00000000, 0x10000000), (0x10000000, 0x20000000), (0xD0000000, 0xD1000000), (0xDF000000, 0xE0000000)]
hit = [0]

def rd(pid_mem, B, a, n):
    pid_mem.seek(B + a); return pid_mem.read(n)

class Abort(gdb.Breakpoint):
    def stop(self):
        hit[0] += 1
        if hit[0] > 1: return False
        rdi = int(gdb.parse_and_eval('(unsigned long long)$rdi'))
        B = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
        pid = gdb.selected_inferior().pid
        t = gdb.selected_thread()
        print('[pngabort] hit thread "%s" lwp %d ctx=0x%x vm_base=0x%x' % (t.name, t.ptid[1], rdi, B), flush=True)
        inf = gdb.selected_inferior()
        g = struct.unpack('<32Q', bytes(inf.read_memory(rdi, 256)))
        lr = struct.unpack('<Q', bytes(inf.read_memory(rdi + 1032, 8)))[0]
        print('[pngabort] lr=0x%08x' % lr)
        for i in range(0, 32, 4):
            print('[pngabort] r%-2d %08x %08x %08x %08x' % ((i,) + tuple(x & 0xffffffff for x in g[i:i+4])))
        with open('/proc/%d/mem' % pid, 'rb', buffering=0) as m:
            sp = g[1] & 0xffffffff
            for k in range(40):
                try:
                    nxt = struct.unpack('>I', rd(m, B, sp + 4, 4))[0]
                    if not nxt: break
                    slr = struct.unpack('>Q', rd(m, B, nxt + 0x10, 8))[0]
                except OSError: break
                print('[pngabort] frame %2d sp=%08x lr=%08x' % (k, nxt, slr & 0xffffffff))
                sp = nxt
            open(os.path.join(D, 'ctx.txt'), 'w').write('ctx=0x%x\nlr=0x%x\n' % (rdi, lr) +
                ''.join('r%d=0x%x\n' % (i, g[i]) for i in range(32)))
            for a0, a1 in RANGES:
                fn = os.path.join(D, 'mem_%08x.bin' % a0); wrote = 0
                with open(fn, 'wb') as f:
                    f.truncate(a1 - a0)
                    for a in range(a0, a1, 0x10000):
                        try: c = rd(m, B, a, 0x10000)
                        except OSError: continue
                        if c.count(0) == len(c): continue
                        f.seek(a - a0); f.write(c); wrote += 1
                print('[pngabort] dumped %s: %d nonzero 64K chunks' % (fn, wrote), flush=True)
        print('[pngabort] guest thread backtrace (host):', flush=True)
        try: gdb.execute('bt 25')
        except gdb.error as e: print(e)
        print('[pngabort] DONE', flush=True)
        return True

Abort('_Z13func_00781F14P11ppu_context')
gdb.execute('run')
if hit[0]:
    gdb.execute('kill')
