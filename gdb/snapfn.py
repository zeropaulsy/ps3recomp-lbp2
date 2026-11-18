# gdb: at the Nth entry of a lifted SPU function, dump its spu_context and LS. env: SNAPFN, SNAPN, SNAPDIR
import gdb, os
gdb.execute('set pagination off'); gdb.execute('set confirm off'); gdb.execute('set debuginfod enabled off')
for s in ('SIGSEGV','SIGUSR1','SIGUSR2','SIGPIPE','SIGBUS','SIGILL','SIGFPE'):
    gdb.execute('handle %s nostop noprint pass'%s)
fn = os.environ['SNAPFN']; n = int(os.environ.get('SNAPN', '200')); d = os.environ['SNAPDIR']
gdb.execute('break %s' % fn)
gdb.execute('ignore 1 %d' % (n - 1))
gdb.execute('run')
rdi = int(gdb.parse_and_eval('$rdi'))
ls = int(gdb.parse_and_eval('*(unsigned long*)(%d + 264192)' % rdi))
gdb.execute('dump binary memory %s/ctx.bin %d %d' % (d, rdi, rdi + 268912))
gdb.execute('dump binary memory %s/ls.bin %d %d' % (d, ls, ls + 0x40000))
print('SNAP done ctx=0x%x ls=0x%x' % (rdi, ls))
gdb.execute('kill')
