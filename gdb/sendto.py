import gdb, struct
# Log guest UDP traffic: every netSocket / netSendTo (fd, len, dest sockaddr_in, first bytes) and netBind.
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
inf = gdb.selected_inferior()
def gpr(ctx, i): return struct.unpack('<Q', bytes(inf.read_memory(ctx + 8*i, 8)))[0]
def lr(ctx): return struct.unpack('<Q', bytes(inf.read_memory(ctx + 1032, 8)))[0]
n = {}
class Bp(gdb.Breakpoint):
    def __init__(self, spec, name):
        super().__init__(spec, internal=True); self.name = name
    def stop(self):
        k = self.name; n[k] = n.get(k, 0) + 1
        if n[k] > 60: return False
        B = int(gdb.parse_and_eval('(unsigned long long)vm_base'))
        ctx = int(gdb.parse_and_eval('$rdi'))
        r = [gpr(ctx, i) & 0xffffffff for i in range(3, 9)]
        def m(a, l):
            try: return bytes(inf.read_memory(B + a, l)).hex()
            except Exception: return '?'
        if k == 'sendto':
            print('SENDTO fd=%d len=%d flags=%#x to=%s data=%s lr=%#x' % (r[0], r[2], r[3], m(r[4], 8) if r[4] else '-', m(r[1], min(r[2], 24)), lr(ctx)), flush=True)
        else:
            print('%s r3..r5=%#x %#x %#x lr=%#x' % (k.upper(), r[0], r[1], r[2], lr(ctx)), flush=True)
        return False
Bp('hle_net_sendto', 'sendto')
Bp('hle_net_socket', 'socket')
gdb.execute('run')
gdb.execute('kill')
