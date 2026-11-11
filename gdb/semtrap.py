import gdb, re
# Pairs with GCM_SEMA_TRAP_MS: at each SIGTRAP, print every non-idle thread's frames
# (lifted names shortened), then continue. Stops after SEMTRAP_N traps.
import os
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
gdb.execute('handle SIGTRAP stop print nopass')
N = int(os.environ.get('SEMTRAP_N', '3'))
def short(n):
    n = n or '??'
    n = re.sub(r'_Z\d+(\w+?)_spu_func_([0-9A-F]{8})P11spu_context', r'S:\1:\2', n)
    n = re.sub(r'_Z1[0-9]func_([0-9A-F]{8})P11ppu_context', r'F\1', n)
    n = re.sub(r'func_([0-9A-F]{8})\(ppu_context\*\)', r'F\1', n)
    return n
IDLE = ('spurs_pm_worker', 'spu_taskset_wait_signal', 'cellSpursEventFlagWait')
gdb.execute('run')
for i in range(N):
    print('=== TRAP %d ===' % i, flush=True)
    for th in gdb.selected_inferior().threads():
        th.switch(); f = gdb.newest_frame(); names = []
        while f is not None and len(names) < 24:
            names.append(short(f.name())); f = f.older()
        txt = ' < '.join(names)
        if any(x in txt for x in IDLE) and 'S:' not in txt: continue
        if 'F' not in txt and 'S:' not in txt and 'cellGcm' not in txt and 'rsx' not in txt: continue
        print('T%d[%s]: %s' % (th.num, th.name, txt), flush=True)
    try:
        gdb.execute('continue')
    except gdb.error:
        break
gdb.execute('kill')
