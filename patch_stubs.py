# Restores the ABI step the real import stub performs: save the caller's r2 to 0x28(r1).
# Needed because ps3_hle_call's fast path returns before _TocGuard. Applies to generated code only.
import glob,re
pat=re.compile(r'^(\s*)(ps3_hle_call\(0x[0-9A-F]{8}u, ctx\); return;  /\* import stub \*/)$',re.M)
tot=0
for f in sorted(glob.glob('recompiled/ppu_recomp_*.cpp')):
    s=open(f,newline='').read()
    if 'import stub */' not in s: continue
    n,c=pat.subn(lambda m:f'{m[1]}vm_write64(ctx->gpr[1] + 0x28, ctx->gpr[2]); {m[2]}',s)
    if c: open(f,'w',newline='').write(n); tot+=c; print(f,c)
print('patched',tot)
