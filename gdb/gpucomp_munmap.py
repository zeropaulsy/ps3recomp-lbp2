import gdb
# 2026-11-20: the 43 s crash. Break at libnvidia-gpucomp 595.99.02 +0x4128a98 (its `call munmap@plt`
# in a {ptr,size} free helper), print thread, range and backtrace for each hit (cap 60), continue.
# SIGSEGVs: backtrace and registers, like segvbt.py.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGUSR1','SIGUSR2','SIGPIPE','SIGILL','SIGFPE','SIGINT'):
    gdb.execute('handle %s nostop noprint pass' % s)
gdb.execute('handle SIGSEGV stop print pass'); gdb.execute('handle SIGBUS stop print pass')
OFF = 0x4128a98
st = {'base': None, 'hits': 0}
class B(gdb.Breakpoint):
    def stop(self):
        st['hits'] += 1
        if st['hits'] <= 60:
            t = gdb.selected_thread()
            print('[gpmunmap] hit %d thread "%s" lwp %d: munmap(%s, %s)' % (st['hits'], t.name, t.ptid[1],
                  gdb.parse_and_eval('$rdi'), gdb.parse_and_eval('$rsi')), flush=True)
            try: gdb.execute('bt 40')
            except gdb.error as e: print('[gpmunmap] bt error %s' % e)
            print('[gpmunmap] end', flush=True)
        return False
def on_obj(ev):
    if st['base'] or 'libnvidia-gpucomp' not in (ev.new_objfile.filename or ''): return
    out = gdb.execute('info proc mappings', to_string=True)
    for l in out.splitlines():
        f = l.split()
        if len(f) >= 5 and 'libnvidia-gpucomp' in l and f[3] in ('0x0', '0'):
            st['base'] = int(f[0], 16); break
    if st['base']:
        print('[gpmunmap] gpucomp base 0x%x' % st['base'], flush=True)
        B('*0x%x' % (st['base'] + OFF), internal=True)
gdb.events.new_objfile.connect(on_obj)
n = [0]
def on_stop(ev):
    if not isinstance(ev, gdb.SignalEvent): return
    n[0] += 1
    if n[0] > 4: return
    print('[segvbt] #%d %s thread %s' % (n[0], ev.stop_signal, gdb.selected_thread().name), flush=True)
    try: gdb.execute('bt 20'); gdb.execute('info registers rip rsp rax rdi rsi')
    except gdb.error as e: print('[segvbt] error %s' % e, flush=True)
gdb.events.stop.connect(on_stop)
gdb.execute('run')
while True:
    try: gdb.execute('continue')
    except gdb.error: break
