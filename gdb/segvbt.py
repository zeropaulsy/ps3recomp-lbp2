import gdb
# Print a backtrace for every SIGSEGV (capped at SEGV_MAX, default 30) and pass it on, so the
# last one printed before the process dies is the crash. Other noisy signals pass silently.
import os
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGUSR1','SIGUSR2','SIGPIPE','SIGILL','SIGFPE','SIGINT'):
    gdb.execute('handle %s nostop noprint pass' % s)
gdb.execute('handle SIGSEGV stop print pass')
gdb.execute('handle SIGBUS stop print pass')
MAX = int(os.environ.get('SEGV_MAX', '30'))
n = [0]
def on_stop(ev):
    if not isinstance(ev, gdb.SignalEvent): return
    n[0] += 1
    if n[0] <= MAX:
        print('[segvbt] #%d %s thread %s' % (n[0], ev.stop_signal, gdb.selected_thread().name), flush=True)
        try:
            gdb.execute('bt 25')
            gdb.execute('info registers rip rsp rdi rsi rdx rcx rax')
            gdb.execute('x/3i $pc')
        except gdb.error as e:
            print('[segvbt] bt error %s' % e, flush=True)
gdb.events.stop.connect(on_stop)
gdb.execute('run')
while True:
    try:
        gdb.execute('continue')
    except gdb.error:
        break
