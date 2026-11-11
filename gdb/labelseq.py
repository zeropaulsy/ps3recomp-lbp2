import gdb, os, time
# Compact write log for several GCM labels (env LW_LABELS="43,44,45"): one line per write,
# "[ls] t label=value P|S|R" (P = PPU recompiled code, S = SPU DMA, R = RSX FIFO walker).
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
LABELS = [int(x, 16) for x in os.environ.get('LW_LABELS', '43,44,45').split(',')]
inf = gdb.selected_inferior(); T0 = time.time()
def who():
    f = gdb.newest_frame(); k = 0
    while f is not None and k < 4:
        nm = f.name() or ''
        if 'mfc_do_transfer' in nm: return 'S'
        if 'rsx_process_fifo' in nm: return 'R'
        if '_Z13func_' in nm: return 'P:' + nm.replace('_Z13func_', '').split('P11')[0]
        f = f.older(); k += 1
    return '?'
class WP(gdb.Breakpoint):
    def stop(self):
        v = int.from_bytes(inf.read_memory(self.addr, 4).tobytes(), 'big')
        print('[ls] %.3f %02X=%d %s' % (time.time() - T0, self.label, v, who()), flush=True)
        return False
armed = []
class Arm(gdb.Breakpoint):
    def stop(self):
        if armed: return False
        base = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
        inj = int(gdb.parse_and_eval('(unsigned int)ppu_hle_inject_base'))
        for L in LABELS:
            w = WP('*(unsigned int*)0x%x' % (base + inj + L * 0x10), gdb.BP_WATCHPOINT, gdb.WP_WRITE)
            w.addr = base + inj + L * 0x10; w.label = L; armed.append(w)
        return False
Arm('cellGcmGetLabelAddress')
gdb.execute('run')
gdb.execute('kill')
