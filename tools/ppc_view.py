import sys,struct,capstone,os
d=open(os.environ.get('LBP2_ELF') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lbp2.elf'),'rb').read()
md=capstone.Cs(capstone.CS_ARCH_PPC,capstone.CS_MODE_64|capstone.CS_MODE_BIG_ENDIAN)
for spec in sys.argv[1:]:
    a,n=spec.split(':');a=int(a,16);n=int(n)
    print('---',hex(a))
    code=d[a-0x10000:a-0x10000+n*4]
    for off in range(0,len(code),4):
        l=list(md.disasm(code[off:off+4],a+off))
        print(hex(a+off),code[off:off+4].hex(),(l[0].mnemonic+' '+l[0].op_str) if l else '??')
