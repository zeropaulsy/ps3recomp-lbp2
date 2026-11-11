import gdb, struct
# Like snap.py, but after the SIGINT also dumps the Network init object (step 70):
# 16 sub-task states at +0x50 and their member-function pointers at +0x90.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
gdb.execute('run')
inf = gdb.selected_inferior()
B = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
def rd(a, n): return bytes(inf.read_memory(B + a, n))
def u32(a): return struct.unpack('>I', rd(a, 4))[0]
TOC = 0xC65AF0
obj = u32(u32(TOC - 0x7fb0 + 0) if False else TOC - 0x7fb0)
print('NETOBJ toc-slot value', hex(obj))
o = obj
print('NETOBJ +0x00..0x50', rd(o, 0x50).hex())
for i in range(16):
    st = u32(o + 0x50 + 4*i)
    m0, m1 = u32(o + 0x90 + 8*i), u32(o + 0x94 + 8*i)
    fn = u32(m0) if (m0 & 1) == 0 and 0x10000 < m0 < 0xd60000 else 0
    print('NETOBJ task %2d state=%d mptr=%08x adj=%08x fn=%08x' % (i, st, m0, m1, fn))
print('NETOBJ +0x150', rd(o + 0x150, 8).hex())
sub = u32(o + 0x14)
print('SUB14 obj=%08x +0x16f0: %s' % (sub, rd(sub + 0x16f0, 0x30).hex()))
TOC2 = 0xC75A98
for off in (0x2e44, 0x2e48, 0x2efc):
    p = u32(TOC2 + off)
    print('FLAG toc2+%#x -> %08x = %s' % (off, p, rd(p, 8).hex()))
gdb.execute('thread apply all bt 22')
gdb.execute('kill')
