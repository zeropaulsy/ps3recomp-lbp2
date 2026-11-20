# Check every PNG inside a file (default: the game's HDD cache hdd1/cache/BCUS98245/output/temp):
# chunk CRCs + zlib stream; prints damaged ones and their first 256-byte zero run. (2026-11-20)
# usage: venv/bin/python -I tools/cachecheck.py [file] [start-offset]
import struct, zlib, sys
b=open(sys.argv[1] if len(sys.argv)>1 else "hdd1/cache/BCUS98245/output/temp","rb").read(); lo=int(sys.argv[2]) if len(sys.argv)>2 else 0
i=b.find(b'\x89PNG\r\n\x1a\n', lo); good=bad=0
while i>=0:
    o=i+8; ok=True; idat=b''
    while o+8<=len(b):
        L=struct.unpack('>I',b[o:o+4])[0]; t=b[o+4:o+8]
        if L>1<<24: ok=False; break
        c=struct.unpack('>I',b[o+8+L:o+12+L])[0]
        if c!=zlib.crc32(b[o+4:o+8+L])&0xffffffff: ok=False
        if t==b'IDAT': idat+=b[o+8:o+8+L]
        o+=12+L
        if t==b'IEND': break
    try: zlib.decompress(idat)
    except Exception: ok=False
    if ok: good+=1
    else:
        bad+=1; z=b[i:o]; k=z.find(bytes(256))
        print('BAD png at', i, hex(i), 'len', o-i, 'first 256-zero run at png+%d (file 0x%x)' % (k, i+k) if k>=0 else 'no zero run')
    i=b.find(b'\x89PNG\r\n\x1a\n', i+8)
print('good',good,'bad',bad)
