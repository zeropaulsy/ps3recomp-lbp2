import struct,os,sys
d=open(os.environ.get('LBP2_ELF') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lbp2.elf'),'rb').read()
for s in sys.argv[1:]:
    a=int(s,16);o=a-0xc30000+0xc20000
    print(s,'->',[hex(x) for x in struct.unpack('>II',d[o:o+8])])
