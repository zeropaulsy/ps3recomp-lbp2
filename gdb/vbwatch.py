import gdb, os, time, struct
# Hardware write watchpoints on guest EAs (env VW_ADDRS, comma list of hex; default: the letterbox
# mask's vertex-2 y in the three per-frame vertex rings). Logs value (as float), thread, guest chain.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
ADDRS = [int(a, 16) for a in os.environ.get('VW_ADDRS', '13A00064,1A600064,1AF00064').split(',')]
MAX = int(os.environ.get('VW_MAX', '12'))
inf = gdb.selected_inferior()
T0 = time.time()
def guest_frames(n=10):
    out = []; f = gdb.newest_frame()
    while f is not None and len(out) < n:
        nm = f.name() or ''
        if '_Z13func_' in nm or nm.startswith('func_'):
            out.append(nm.replace('_Z13func_', '').replace('func_', '').split('(')[0].replace('P11ppu_context', ''))
        f = f.older()
    return ' < '.join(out)
counts = {}
class WP(gdb.Breakpoint):
    def stop(self):
        v = struct.unpack('>f', inf.read_memory(self.addr, 4).tobytes())[0]; hx = inf.read_memory(self.addr, 4).tobytes().hex()
        th = gdb.selected_thread()
        g = guest_frames()
        k = (self.ga, g)
        counts[k] = counts.get(k, 0) + 1
        if counts[k] <= MAX:
            print('[vw] t=%.1f 0x%08X = %g (%s) by %s | guest %s | host pc 0x%x %s' % (
                time.time() - T0, self.ga, v, hx, th.name, g, gdb.newest_frame().pc(), gdb.newest_frame().name()), flush=True)
        return False
armed = []
class Arm(gdb.Breakpoint):
    def stop(self):
        if armed: return False
        base = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
        for ga in ADDRS:
            w = WP('*(unsigned int*)0x%x' % (base + ga), gdb.BP_WATCHPOINT, gdb.WP_WRITE, internal=False)
            w.addr = base + ga; w.ga = ga
            armed.append(w)
        print('[vw] armed', [hex(a) for a in ADDRS], flush=True)
        return False
Arm('cellGcmGetLabelAddress')
gdb.execute('run')
print('[vw] totals:', sorted(((hex(k[0]), k[1]), c) for k, c in counts.items()), flush=True)
gdb.execute('kill')
