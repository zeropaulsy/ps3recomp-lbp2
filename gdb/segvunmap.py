import gdb, os
# 2026-11-20: who unmaps / reprotects the driver's generated-code page that vkCmdBindDescriptorSets
# calls (0x7ffef401f000 under gdb, ASLR off; PAGE env overrides). Stops on munmap/mprotect/madvise/
# mremap/mmap calls whose range covers it, prints the backtrace, continues; SIGSEGVs as segvbt.py.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGUSR1','SIGUSR2','SIGPIPE','SIGILL','SIGFPE','SIGINT'):
    gdb.execute('handle %s nostop noprint pass' % s)
gdb.execute('handle SIGSEGV stop print pass'); gdb.execute('handle SIGBUS stop print pass')
P = int(os.environ.get('PAGE', '0x7ffef401f000'), 16)
gdb.execute('catch syscall munmap mprotect madvise mremap mmap')
gdb.execute('condition $bpnum ($rdi <= 0x%x && $rdi + $rsi > 0x%x) || $rdi == 0x%x' % (P, P, P))
n = [0]; hits = [0]
def on_stop(ev):
    if isinstance(ev, gdb.SignalEvent):
        n[0] += 1
        if n[0] > 5: return
        print('[segvbt] #%d %s thread %s' % (n[0], ev.stop_signal, gdb.selected_thread().name), flush=True)
        try: gdb.execute('bt 12'); gdb.execute('info registers rip rax r14')
        except gdb.error as e: print('[segvbt] error %s' % e, flush=True)
        return
    if isinstance(ev, gdb.BreakpointEvent):
        hits[0] += 1
        if hits[0] > 40: return
        try:
            print('[unmap] hit %d thread %s: orig_rax=%s rdi=%s rsi=%s rdx=%s r10=%s rax=%s' % (hits[0],
                  gdb.selected_thread().name,
                  *[str(gdb.parse_and_eval('$' + r)) for r in ('orig_rax', 'rdi', 'rsi', 'rdx', 'r10', 'rax')]), flush=True)
            gdb.execute('bt 25')
        except gdb.error as e: print('[unmap] error %s' % e, flush=True)
gdb.events.stop.connect(on_stop)
gdb.execute('run')
while True:
    try: gdb.execute('continue')
    except gdb.error: break
