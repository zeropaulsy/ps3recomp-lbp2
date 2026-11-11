import os,sys,re
d=open(os.environ.get('LBP2_ELF') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lbp2.elf'),'rb').read()
for pat in sys.argv[1:]:
    for m in re.finditer(pat.encode(),d):
        s=d[m.start():d.index(b'\0',m.start())][:100]
        o=m.start(); print(hex(o+0x10000 if o<0xc20000 else o-0xc20000+0xc30000),s)
