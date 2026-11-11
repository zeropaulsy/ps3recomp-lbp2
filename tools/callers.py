import struct,os,json,bisect,sys
d=open(os.environ.get('LBP2_ELF') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lbp2.elf'),'rb').read()
def r32(a): return struct.unpack('>I',d[a-0x10000:a-0x10000+4])[0]
F=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out', 'lbp2.functions.json')))
F=sorted((int(x['start'],16),int(x['end'],16)) for x in F); S=[x[0] for x in F]
def fn(a):
    i=bisect.bisect_right(S,a)-1
    return hex(F[i][0]) if i>=0 and a<F[i][1] else '?'
T={int(x,16) for x in sys.argv[1:]}
# include toc switch stubs that branch to targets
stubs={}
for a in range(0x10200,0xb09d78,4):
    w=r32(a)
    if w>>26==18 and (w&3) in (0,1):
        li=w&0x03fffffc
        if li&0x02000000: li-=0x04000000
        t=a+li
        if t in T:
            if w&1: print('bl',hex(a),'->',hex(t),'in',fn(a))
            else:
                print('b ',hex(a),'->',hex(t),'in',fn(a))
                # stub? previous 3 words
                if r32(a-12)==0xf8410028:
                    stubs[a-12]=t
for a in range(0x10200,0xb09d78,4):
    w=r32(a)
    if w>>26==18 and (w&3)==1:
        li=w&0x03fffffc
        if li&0x02000000: li-=0x04000000
        t=a+li
        if t in stubs: print('bl',hex(a),'via stub',hex(t),'->',hex(stubs[t]),'in',fn(a))
