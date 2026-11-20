import gdb, os, re
# 2026-11-20: the 43 s vkCmdBindDescriptorSets crash. Like segvbt.py, plus: once libnvidia-glcore
# (595.99.02) loads, watch its `call *%rax` at +0xdcbdfd (BindDescriptorSets calling the per-set
# routine stored at pipeline-layout record +0x138) and print the first targets with their mapping;
# at a SIGSEGV print the registers, the layout record and the mappings around rip.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGUSR1','SIGUSR2','SIGPIPE','SIGILL','SIGFPE','SIGINT'):
    gdb.execute('handle %s nostop noprint pass' % s)
gdb.execute('handle SIGSEGV stop print pass'); gdb.execute('handle SIGBUS stop print pass')
OFF = 0xdcbdfd
st = {'base': None, 'seen': {}}
def maps():
    out = gdb.execute('info proc mappings', to_string=True); r = []
    for l in out.splitlines():
        f = l.split()
        if len(f) >= 4 and f[0].startswith('0x'):
            r.append((int(f[0],16), int(f[1],16), l.strip()))
    return r
def where(a, m=None):
    for lo, hi, l in (m or maps()):
        if lo <= a < hi: return l
    return 'UNMAPPED'
def near(a, m):
    return [l for lo, hi, l in m if hi > a - 0x400000 and lo < a + 0x400000]
class Watch(gdb.Breakpoint):
    def stop(self):
        rax = int(gdb.parse_and_eval('$rax')) & (2**64-1)
        r14 = int(gdb.parse_and_eval('$r14')) & (2**64-1)
        if rax not in st['seen'] and len(st['seen']) < 12:
            st['seen'][rax] = 1
            print('[segvmap] call target 0x%x rec r14=0x%x -> %s | rec in %s' % (rax, r14, where(rax), where(r14)), flush=True)
        if len(st['seen']) >= 12: self.enabled = False
        return False
def on_obj(ev):
    if st['base'] or 'libnvidia-glcore' not in (ev.new_objfile.filename or ''): return
    for lo, hi, l in maps():
        if 'libnvidia-glcore' in l and l.split()[3] in ('0x0', '0'):
            st['base'] = lo; break
    if st['base']:
        print('[segvmap] glcore base 0x%x' % st['base'], flush=True)
        Watch('*0x%x' % (st['base'] + OFF), internal=True)
gdb.events.new_objfile.connect(on_obj)
n = [0]
def on_stop(ev):
    if not isinstance(ev, gdb.SignalEvent): return
    n[0] += 1
    if n[0] > 30: return
    print('[segvbt] #%d %s thread %s' % (n[0], ev.stop_signal, gdb.selected_thread().name), flush=True)
    try:
        gdb.execute('bt 12'); gdb.execute('info registers')
        rip = int(gdb.parse_and_eval('$pc')) & (2**64-1)
        m = maps()
        print('[segvmap] rip in: %s' % where(rip, m), flush=True)
        for l in near(rip, m): print('[segvmap]   near: ' + l, flush=True)
        for r in ('r14', 'r15', 'rbx', 'r13'):
            v = int(gdb.parse_and_eval('$' + r)) & (2**64-1)
            print('[segvmap] %s=0x%x in %s' % (r, v, where(v, m)), flush=True)
        try: gdb.execute('x/12gx $r14+0x100')
        except gdb.error as e: print('[segvmap] r14 read error %s' % e)
        try: gdb.execute('x/12gx $rsp')
        except gdb.error as e: print('[segvmap] rsp read error %s' % e)
    except gdb.error as e:
        print('[segvbt] error %s' % e, flush=True)
gdb.events.stop.connect(on_stop)
gdb.execute('run')
while True:
    try: gdb.execute('continue')
    except gdb.error: break
