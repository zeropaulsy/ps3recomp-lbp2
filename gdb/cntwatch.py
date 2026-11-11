import gdb, os
# Log every write to the Wws dependency counters at CW_ADDRS (guest EAs, default 0xD1516C,0xD15194):
# new value (u16 count + 2 control bytes, big-endian), writer thread and the host call stack
# (lifted PPU funcs are func_XXXXXXXX, SPU code pm_wwsjob_spu_func_* / jobmod_*).
# Armed at the first spu_run_policy_module call (vm_base is set by then). At SNAP's SIGINT,
# prints the counters' current values plus the 0xD15100..0xD15400 block and kills the game.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('handle SIGINT stop print nopass')
ADDRS = [int(x, 16) for x in os.environ.get('CW_ADDRS', 'D1516C,D15194').split(',')]
inf = lambda: gdb.selected_inferior()
vb = [0]
n = [0]
def be32(a): return int.from_bytes(bytes(inf().read_memory(vb[0] + a, 4)), 'big')
def stack(depth=8):
    out = []; f = gdb.newest_frame()
    while f and len(out) < depth:
        nm = f.name() or '?'
        nm = nm.replace('(ppu_context*)', '').replace('(spu_context*)', '')
        out.append(nm); f = f.older()
    return ' < '.join(out)

class Watch(gdb.Breakpoint):
    def __init__(self, ea):
        super().__init__('*(unsigned int*)%d' % (vb[0] + ea), gdb.BP_WATCHPOINT, gdb.WP_WRITE, internal=False)
        self.ea = ea
    def stop(self):
        n[0] += 1
        try:
            print('[cw] #%d ea=%06X val=%08X thr=%s :: %s' % (n[0], self.ea, be32(self.ea),
                  gdb.selected_thread().name, stack()), flush=True)
        except Exception as e:
            print('[cw] #%d err %r' % (n[0], e), flush=True)
        return False

arm = gdb.Breakpoint('spu_run_policy_module')
gdb.execute('run')                      # stops at the first policy-module run
arm.delete()
vb[0] = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
print('[cw] armed vm_base=%x addrs=%s' % (vb[0], ','.join('%X' % a for a in ADDRS)), flush=True)
for a in ADDRS:
    print('[cw] initial ea=%06X val=%08X' % (a, be32(a)), flush=True)
ws = [Watch(a) for a in ADDRS]
gdb.execute('continue')                 # until SNAP's SIGINT
for a in ADDRS:
    print('[cw] final ea=%06X val=%08X' % (a, be32(a)), flush=True)
# Every Wws workload's row (w08 selects it), the header at its cursor and, for a cmd-2 header,
# the dependency word it waits on (count:u16 kickwid:u8 ready:u8).
import re, glob
log = max(glob.glob(os.path.join(os.environ.get('LBP2_WORKSPACE', '.'), 'runs', '*.log')), key=os.path.getmtime)
ea = None; names = {}
for line in open(log, errors='replace'):
    m = re.search(r'Initialize2 .* ea=0x([0-9A-F]+)', line)
    if m: ea = int(m.group(1), 16)
    m = re.search(r'AddWorkloadWA: .*data=0x0*([0-9A-F]+) .*name=(\S+)', line)
    if m: names[int(m.group(1), 16)] = m.group(2)
rd = lambda a, k: bytes(inf().read_memory(vb[0] + a, k))
b32 = lambda b, o: int.from_bytes(b[o:o+4], 'big')
b16 = lambda b, o: int.from_bytes(b[o:o+2], 'big')
inst = rd(ea, 0x100)
print('[cw] ready ' + ' '.join('%02x' % x for x in inst[0:16]) + ' signal1=%04X' % b16(inst, 0x70), flush=True)
for wid in range(16):
    data = b32(rd(ea + 0xB00 + wid * 0x20, 0x20), 12)
    if not data: continue
    line = rd(data, 0x80); row = b32(line, 8) & 3; jl = b32(line, 0x30 + 4 * row)
    hw = [b16(line, 0x40 + 16 * row + 2 * j) for j in range(8)]
    s = '[cw] wid%-2d %-24s row%d hw0=%d cur=%d slots=%s' % (wid, names.get(data, '?'), row, hw[0], hw[1],
        ' '.join('-' if x == 0xFFFF else str(x) for x in hw[2:]))
    if jl and hw[1] < 4096:
        h = rd(jl + 8 * hw[1], 8); cmd = b16(h, 2); arg = b32(h, 4)
        s += ' hdr[cur]=%s' % h.hex()
        if cmd == 2: s += ' dep@%06X=%08X' % (arg, b32(rd(arg & ~3, 4), 0))
    print(s, flush=True)

for base in (0xD15100, 0xD15500):
    b = bytes(inf().read_memory(vb[0] + base, 0x300))
    for o in range(0, 0x300, 16):
        print('[cw] mem %06X: %s' % (base + o, ' '.join(b[o+i:o+i+4].hex() for i in range(0, 16, 4))), flush=True)
gdb.execute('kill')
