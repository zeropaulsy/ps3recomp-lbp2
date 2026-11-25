import gdb, os, time, struct
# Guest memcpy (func_00783384: r3 dst, r4 src, r5 len) into [MW_LO, MW_HI): log dst, src, len,
# guest chain and the first source bytes. (2026-11-25, planet index-buffer shards)
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
LO = int(os.environ.get('MW_LO', '11D00000'), 16); HI = int(os.environ.get('MW_HI', '11D30000'), 16)
MAX = int(os.environ.get('MW_MAX', '60'))
inf = gdb.selected_inferior(); T0 = time.time(); n = [0]
def guest_frames(k=12):
    out = []; f = gdb.newest_frame()
    while f is not None and len(out) < k:
        nm = f.name() or ''
        if '_Z13func_' in nm: out.append(nm.replace('_Z13func_', '').split('P11')[0])
        f = f.older()
    return ' < '.join(out)
class B(gdb.Breakpoint):
    def stop(self):
        ctx = int(gdb.parse_and_eval('$rdi'))
        r = lambda i: struct.unpack('<Q', inf.read_memory(ctx + 8 * i, 8).tobytes())[0] & 0xFFFFFFFF
        dst, src, ln = r(3), r(4), r(5)
        if dst + ln <= LO or dst >= HI or n[0] >= MAX: return False
        n[0] += 1
        base = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
        lr = struct.unpack('<Q', inf.read_memory(ctx + 1032, 8).tobytes())[0] & 0xFFFFFFFF
        sb = inf.read_memory(base + src, 32).tobytes().hex()
        print('[mw] t=%.1f dst 0x%08X src 0x%08X len 0x%X lr 0x%08X thr %s | %s | src[0:32] %s' % (
            time.time() - T0, dst, src, ln, lr, gdb.selected_thread().name, guest_frames(), sb), flush=True)
        return False
B('_Z13func_00783384P11ppu_context')
gdb.execute('run')
gdb.execute('kill')
