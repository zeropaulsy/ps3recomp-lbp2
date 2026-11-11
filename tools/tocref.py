import struct,sys,json,bisect,os
d=open(os.environ.get('LBP2_ELF') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lbp2.elf'),'rb').read()
def off(a): return a-0x10000 if a<0xc30000 else a-0xc30000+0xc20000
r=lambda a:struct.unpack('>I',d[off(a):off(a)+4])[0]
F=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out', 'lbp2.functions.json')))
F=sorted((int(x['start'],16),int(x['end'],16)) for x in F); S=[x[0] for x in F]
def fn(a):
    i=bisect.bisect_right(S,a)-1
    return hex(F[i][0]) if i>=0 and a<F[i][1] else '?'
target=int(sys.argv[1],16)
tocs=[0xC65AF0,0xC75A98]+[int(x,16) for x in sys.argv[2:]]
for T in tocs:
  for o in range(-0x8000,0x8000,4):
    try:
      if r(T+o)==target: print('TOC',hex(T),'slot',hex(o))
      else: continue
    except Exception: continue
    for a in range(0x10200,0xb09d78,4):
      w=r(a)
      if w>>26 in (32,58) and ((w>>16)&31)==2 and (struct.unpack('>h',struct.pack('>H',w&0xffff))[0])==o:
        print('  ',hex(a),'in',fn(a))
