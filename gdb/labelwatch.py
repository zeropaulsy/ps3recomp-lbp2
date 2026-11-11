import gdb, os, time
# Hardware watchpoint on one GCM label (env LW_LABEL, default 0x41): logs who writes it
# (host thread name, guest call chain, host frames), first LW_MAX writes per value.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
LABEL = int(os.environ.get('LW_LABEL', '0x41'), 16)
MAX = int(os.environ.get('LW_MAX', '6'))
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
def host_frames(n=6):
    out = []; f = gdb.newest_frame()
    while f is not None and len(out) < n:
        out.append(f.name() or hex(f.pc())); f = f.older()
    return ' < '.join(out)
counts = {}
class WP(gdb.Breakpoint):
    def stop(self):
        b = inf.read_memory(self.addr, 4).tobytes()
        v = int.from_bytes(b, 'big')
        th = gdb.selected_thread()
        k = (v, th.name)
        counts[k] = counts.get(k, 0) + 1
        if counts[k] <= MAX:
            print('[lw] t=%.1f label 0x%02X = 0x%08X by thread %s (lwp %d) #%d | guest %s | host %s' % (
                time.time() - T0, LABEL, v, th.name, th.ptid[1], counts[k], guest_frames(), host_frames()), flush=True)
        return False
armed = []
class Arm(gdb.Breakpoint):
    def stop(self):
        if armed: return False
        base = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
        inj = int(gdb.parse_and_eval('(unsigned int)ppu_hle_inject_base'))
        addr = base + inj + LABEL * 0x10
        w = WP('*(unsigned int*)0x%x' % addr, gdb.BP_WATCHPOINT, gdb.WP_WRITE, internal=False)
        w.addr = addr
        armed.append(w)
        print('[lw] armed label 0x%02X at guest 0x%08X host 0x%x' % (LABEL, inj + LABEL * 0x10, addr), flush=True)
        return False
Arm('cellGcmGetLabelAddress')
gdb.execute('run')
print('[lw] totals:', sorted(((hex(k[0]), k[1]), c) for k, c in counts.items()), flush=True)
gdb.execute('kill')
