import gdb, threading, os, time, signal, re
# Several snapshots of the busy threads, N seconds apart (after the first SNAP SIGINT).
# Env: MS_COUNT (default 6), MS_GAP seconds (default 3), MS_THREADS gdb thread nums (default "1 15").
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
COUNT = int(os.environ.get('MS_COUNT', '6')); GAP = float(os.environ.get('MS_GAP', '3'))
THREADS = os.environ.get('MS_THREADS', '1 15')
gdb.execute('run')

def frames(tnum, depth=40):
    out = gdb.execute('thread apply %s bt %d' % (tnum, depth), to_string=True)
    names = []
    for line in out.splitlines():
        m = re.search(r' in (\S+)', line)
        if m:
            n = m.group(1)
            n = re.sub(r'_Z1[0-9]func_([0-9A-F]{8})P11ppu_context', r'F\1', n)
            n = re.sub(r'\(ppu_context\*\)', '', n).replace('func_', 'F')
            names.append(n)
    return names

def guest_lr(tnum):
    # $rdi in the innermost lifted frame = ppu_context*; LR at +1032, r3 at +24
    try:
        gdb.execute('thread %s' % tnum, to_string=True)
        f = gdb.newest_frame()
        while f is not None and 'func_' not in (f.name() or ''):
            f = f.older()
        if f is None: return ''
        f.select()
        ctx = int(gdb.parse_and_eval('(unsigned long long)$rdi'))
        lr = int(gdb.parse_and_eval('*(unsigned long long*)%d' % (ctx + 1032)))
        r3 = int(gdb.parse_and_eval('*(unsigned long long*)%d' % (ctx + 24)))
        return 'innermost=%s guestLR=0x%X r3=0x%X' % (f.name(), lr & 0xFFFFFFFF, r3)
    except Exception as e:
        return 'lr? %s' % e

pid = gdb.selected_inferior().pid
for i in range(COUNT):
    print('=== SNAP %d ===' % i)
    for t in THREADS.split():
        print('T%s: %s' % (t, ' < '.join(frames(t))))
        print('T%s: %s' % (t, guest_lr(t)))
    if i + 1 < COUNT:
        threading.Thread(target=lambda: (time.sleep(GAP), os.kill(pid, signal.SIGINT)), daemon=True).start()
        gdb.execute('continue')
gdb.execute('kill')
