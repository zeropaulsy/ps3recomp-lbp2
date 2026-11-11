import gdb,struct
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
n=[0]
class F(gdb.FinishBreakpoint):
    def stop(self):
        gdb.parse_and_eval('$rax = 0'); n[0]+=1
        return False
    def out_of_scope(self): pass
class B(gdb.Breakpoint):
    def stop(self):
        F(gdb.newest_frame(),internal=True); return False
B('cellNetCtlGetState')
inf=lambda:gdb.selected_inferior()
def base(): return int(gdb.parse_and_eval('(unsigned long long)vm_base'))
def r(a,n): return bytes(inf().read_memory(base()+a,n))
def u32(a): return struct.unpack('>I',r(a,4))[0]
def cstr(a):
    if not a: return ''
    try:
        b=r(a,64); return b[:b.index(0)].decode('latin1')
    except Exception: return '?'
def dump():
    head=u32(0xc65af0-0x74ec); node=head; i=0
    print('=== INIT STEP TABLE head=%x'%head,flush=True)
    while node and i<200:
        w=[u32(node+o) for o in (0,4,8,0xc,0x10,0x14,0x18,0x1c,0x20)]
        res=r(node+0x14,1)[0]; t=struct.unpack('>f',r(node+0x1c,4))[0]
        code=u32(w[2]) if w[2] else 0
        print('step %3d node=%08x name=%r skip=%08x init=%08x(code %08x) close=%08x x10=%08x result=%d t=%.3f'%(i,node,cstr(w[0]),w[1],w[2],code,w[3],w[4],res,t),flush=True)
        if w[2]==0 and w[3]==0 and w[4]==0: break
        node=w[6] if w[6] else node+0x24; i+=1
    print('=== END TABLE',flush=True)
b1=gdb.Breakpoint('main',temporary=True)
b2=gdb.Breakpoint('ps3_hle_call'); b2.condition='$rdi==0x3E22CB4B'
import os,time
def first():
    node=u32(0xc65af0-0x74ec); i=0; done=0
    while node and i<200:
        w=[u32(node+o) for o in (0,4,8,0xc,0x10,0x14,0x18)]
        if w[2]==0 and w[3]==0 and w[4]==0: break
        if r(node+0x14,1)[0]==0 and w[1]==0 and w[2]: return i,cstr(w[0])
        node=w[6] if w[6] else node+0x24; i+=1
    return i,'ALL-DONE'
gdb.execute('run')
gdb.execute('call (void)cellGame_init_from_paramsfo("%s/game/PS3_GAME/PARAM.SFO"' % os.environ.get('LBP2_WORKSPACE', '.') + ')')
n=int(os.environ.get('SNAPS','1'))
for k in range(n):
    gdb.execute('continue')
    try:
        print('=== SNAP %d t~%ds first-unfinished-step=%s'%(k,(k+1)*int(os.environ.get('SNAP','0')),first()),flush=True)
    except Exception as e: print('snap failed',e,flush=True)
try: dump()
except Exception as e: print('dump failed',e,flush=True)
gdb.execute('thread apply all bt 16')
gdb.execute('kill')
