import gdb, os, re, glob
# At SNAP's SIGINT: dump the SPURS instance's per-workload kernel fields and each Wws_Job
# workload's job-list line, so a lane-starvation stall shows which lists have work.
# Instance EA comes from this run's own log ("Initialize2 ... ea=0x...").
# Layout (libs/spurs/cellSpurs.c enum): ready1 +0x00, curcont +0x20, maxcont +0x50,
# signal1 +0x70 (be16), state1 +0x80, enabled +0xB0 (be32), wkl info +0xB00 + wid*0x20 (data u64 at +8).
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
gdb.execute('run')
log = max(glob.glob(os.path.join(os.environ.get('LBP2_WORKSPACE', '.'), 'runs', '*.log')), key=os.path.getmtime)
ea = None
for line in open(log, errors='replace'):
    m = re.search(r'Initialize2 .* ea=0x([0-9A-F]+)', line)
    if m: ea = int(m.group(1), 16)
names = {}
for line in open(log, errors='replace'):
    m = re.search(r'AddWorkloadWA: .*data=0x0*([0-9A-F]+) .*name=(\S+)', line)
    if m: names[int(m.group(1), 16)] = m.group(2)
vb = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
rd = lambda a, n: bytes(gdb.selected_inferior().read_memory(vb + a, n))
be32 = lambda b, o: int.from_bytes(b[o:o+4], 'big')
be16 = lambda b, o: int.from_bytes(b[o:o+2], 'big')
print('[spursdump] log=%s instance=0x%08X' % (log, ea), flush=True)
inst = rd(ea, 0x100)
print('[spursdump] ready  ' + ' '.join('%02x' % x for x in inst[0x00:0x10]))
print('[spursdump] curcon ' + ' '.join('%02x' % x for x in inst[0x20:0x30]))
print('[spursdump] maxcon ' + ' '.join('%02x' % x for x in inst[0x50:0x60]))
print('[spursdump] state  ' + ' '.join('%02x' % x for x in inst[0x80:0x90]))
print('[spursdump] signal1=%04X enabled=%08X flagrecv=%02X flagword=%08X' % (be16(inst, 0x70), be32(inst, 0xB0), inst[0x77], be32(inst, 0x6C)), flush=True)
for wid in range(16):
    info = rd(ea + 0xB00 + wid * 0x20, 0x20)
    data = be32(info, 12)
    if not data: continue
    line = rd(data, 0x80)
    idx = be32(line, 8); jl = be32(line, 0x3C)
    slots = ' | '.join(' '.join('%d' % be16(line, 0x40 + 16*k + 2*j) if be16(line, 0x40 + 16*k + 2*j) != 0xFFFF else '-' for j in range(8)) for k in range(4))
    hdr = rd(jl + 8 * idx, 8) if jl else b''
    print('[spursdump] wid%-2d %-26s line=%08X w08(idx)=%d w0C=%08X w1C=%d w2C=%X jl=%08X hdr[idx]=%s slots: %s'
          % (wid, names.get(data, '?'), data, idx, be32(line, 0x0C), be32(line, 0x1C), be32(line, 0x2C), jl, hdr.hex(), slots), flush=True)
gdb.execute('kill')
