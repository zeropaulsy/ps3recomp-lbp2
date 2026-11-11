import gdb, threading, os, time, signal, re, collections
# Poor man's profiler (perf is blocked here): after SNAP's first SIGINT, AS_COUNT stops AS_GAP s apart;
# at each, every thread's name + innermost AS_DEPTH frames (lifted names shortened to F<addr>).
# Prints a per-thread histogram of the innermost "interesting" frame at the end.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
COUNT = int(os.environ.get('AS_COUNT', '8')); GAP = float(os.environ.get('AS_GAP', '2'))
DEPTH = int(os.environ.get('AS_DEPTH', '8'))
gdb.execute('run')
pid = gdb.selected_inferior().pid
hist = collections.defaultdict(collections.Counter)

def short(n):
    n = n or '??'
    n = re.sub(r'_Z\d+(\w+?)_spu_func_([0-9A-F]{8})P11spu_context', r'S:\1:\2', n)
    n = re.sub(r'_Z1[0-9]func_([0-9A-F]{8})P11ppu_context', r'F\1', n)
    return n

for i in range(COUNT):
    print('=== SNAP %d ===' % i, flush=True)
    for th in gdb.selected_inferior().threads():
        try:
            th.switch()
            f = gdb.newest_frame(); names = []
            while f is not None and len(names) < DEPTH:
                names.append(short(f.name())); f = f.older()
        except Exception as e:
            names = ['err %s' % e]
        tname = th.name or '?'
        print('T%d[%s]: %s' % (th.num, tname, ' < '.join(names)), flush=True)
        key = next((n for n in names if not re.match(r'(__|futex|pthread|syscall|clock_|nanosleep|epoll|poll|read|\?\?)', n)), names[0] if names else '?')
        hist[(th.num, tname)][key] += 1
    if i + 1 < COUNT:
        threading.Thread(target=lambda: (time.sleep(GAP), os.kill(pid, signal.SIGINT)), daemon=True).start()
        gdb.execute('continue')
print('=== HISTOGRAM ===')
for (num, name), c in sorted(hist.items()):
    print('T%d[%s]: %s' % (num, name, ', '.join('%s x%d' % kv for kv in c.most_common(4))))
gdb.execute('kill')
