import gdb
# 2026-11-20: the 43 s crash is a teardown of libGLX_nvidia on the guest "main fast thread" while the
# RSX thread draws. Break on exit/_exit/dlclose/__cxa_finalize/abort and print who (cap 40 hits).
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
gdb.execute('set breakpoint pending on')
for s in ('SIGUSR1','SIGUSR2','SIGPIPE','SIGILL','SIGFPE','SIGINT'):
    gdb.execute('handle %s nostop noprint pass' % s)
gdb.execute('handle SIGSEGV stop print pass'); gdb.execute('handle SIGBUS stop print pass')
h = [0]
class B(gdb.Breakpoint):
    def stop(self):
        h[0] += 1
        if h[0] <= 40:
            t = gdb.selected_thread()
            print('[exitwho] %s hit %d thread "%s" lwp %d rdi=%s' % (self.location, h[0], t.name, t.ptid[1],
                  gdb.parse_and_eval('$rdi')), flush=True)
            try: gdb.execute('bt 30')
            except gdb.error as e: print('[exitwho] bt error %s' % e)
            print('[exitwho] end', flush=True)
        return False
for f in ('exit', '_exit', 'dlclose', '__cxa_finalize', 'abort', 'quick_exit', 'pthread_exit'):
    B(f)
n = [0]
def on_stop(ev):
    if not isinstance(ev, gdb.SignalEvent): return
    n[0] += 1
    if n[0] > 3: return
    print('[segvbt] #%d %s thread %s' % (n[0], ev.stop_signal, gdb.selected_thread().name), flush=True)
    try: gdb.execute('bt 15')
    except gdb.error as e: print('[segvbt] error %s' % e, flush=True)
gdb.events.stop.connect(on_stop)
gdb.execute('run')
while True:
    try: gdb.execute('continue')
    except gdb.error: break
