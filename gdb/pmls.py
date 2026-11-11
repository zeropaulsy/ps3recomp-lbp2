import gdb, os, re, glob
# At SNAP's SIGINT: for the stalled Wws_Job workloads (PMLS_WIDS, default 10-13), dump the job-list
# line + first headers in RAM and every resident PM context's LS state (spurs_policy.c s_pm_instances).
# No debug info, so the layout is hand-computed (Linux, SRWLOCK = void*):
#   PmSlot (64 B): lock 0, ctx 8, data 16, owner 24, pm 32, size 40, wid 44, entry 48, image_id 56
#   PmInstance (12432 B): used 0, retiring 4, users 8, workload_users[32] 12, ea 140, slots[32][6] 144
# spu_context: ls ptr 264192, pc 264200, image_id 264220.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
WIDS = [int(x) for x in os.environ.get('PMLS_WIDS', '10,11,12,13').split(',')]
NSNAP = int(os.environ.get('SNAPS', '1'))
inf = lambda: gdb.selected_inferior()
rdh = lambda a, n: bytes(inf().read_memory(a, n))
le = lambda a, n: int.from_bytes(rdh(a, n), 'little')
be32 = lambda b, o: int.from_bytes(b[o:o+4], 'big')
be16 = lambda b, o: int.from_bytes(b[o:o+2], 'big')
def hexd(b, base):
    return '\n'.join('      %05X: %s' % (base + o, ' '.join(b[o+i:o+i+4].hex() for i in range(0, 16, 4)))
                     for o in range(0, len(b), 16) if any(b[o:o+16]) or o == 0)

def dump(snapno):
    log = max(glob.glob(os.path.join(os.environ.get('LBP2_WORKSPACE', '.'), 'runs', '*.log')), key=os.path.getmtime)
    ea = None; names = {}
    for line in open(log, errors='replace'):
        m = re.search(r'Initialize2 .* ea=0x([0-9A-F]+)', line)
        if m: ea = int(m.group(1), 16)
        m = re.search(r'AddWorkloadWA: .*data=0x0*([0-9A-F]+) .*name=(\S+)', line)
        if m: names[int(m.group(1), 16)] = m.group(2)
    vb = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
    rd = lambda a, n: rdh(vb + a, n)
    print('[pmls] snap %d instance=0x%08X' % (snapno, ea), flush=True)
    for wid in WIDS:
        info = rd(ea + 0xB00 + wid * 0x20, 0x20)
        data = be32(info, 12)
        line = rd(data, 0x80); jl = be32(line, 0x3C)
        print('[pmls] wid%d %s line=%08X jl=%08X' % (wid, names.get(data, '?'), data, jl), flush=True)
        print(hexd(line, 0), flush=True)
        hdrs = rd(jl, 8 * 16)
        print('[pmls]   hdr[0..15]: ' + ' '.join(hdrs[i:i+8].hex() for i in range(0, len(hdrs), 8)), flush=True)
        for row in range(4):
            pushed = be16(line, 0x40 + 16 * row)
            if pushed and pushed != 0xFFFF and pushed < 4096:
                h = rd(jl + 8 * max(pushed - 4, 0), 8 * 8)
                print('[pmls]   row%d around pushed=%d: hdr[%d..]: %s' % (row, pushed, max(pushed - 4, 0),
                      ' '.join(h[i:i+8].hex() for i in range(0, len(h), 8))), flush=True)
    base = int(gdb.parse_and_eval('(unsigned long long)&s_pm_instances'))
    for i in range(4):
        pi = base + i * 12432
        if not le(pi, 4): continue
        print('[pmls] PmInstance %d ea=%08X users=%d' % (i, le(pi + 140, 4), le(pi + 8, 4)), flush=True)
        for wid in WIDS:
            for lane in range(6):
                s = pi + 144 + (wid * 6 + lane) * 64
                ctx = le(s + 8, 8)
                if not ctx: continue
                ls = le(ctx + 264192, 8); pc = le(ctx + 264200, 4) & 0x3FFFF
                print('[pmls] wid%d lane%d ctx=%x data=%08X locked=%x pc=%05X img=%d' % (
                    wid, lane, ctx, le(s + 16, 8), le(s, 8), pc, le(ctx + 264220, 4)), flush=True)
                for (a, n) in ((0x80, 0x80), (0x1C0, 0x30), (0xD00, 0x80), (0x1200, 0x400)):
                    print(hexd(rdh(ls + a, n), a), flush=True)

for k in range(NSNAP):
    gdb.execute('run' if k == 0 else 'continue')
    try:
        dump(k + 1)
    except Exception as e:
        print('[pmls] error %r' % (e,), flush=True)
gdb.execute('kill')
