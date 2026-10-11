#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Source of patches/standby-lhs.json. Run in an unpacked work dir (RT=runtime_0x200000.bin)."""
import sys, json
sys.path.insert(0,'/home/user/dough_es07d03_firmware/tools/aeon')
import aeondis as A, aeonasm as S
import os
d=open(os.environ.get('RT','runtime_0x200000.bin'),'rb').read()
def cur(a,n): return d[a-0x200000:a-0x200000+n]
SUB_245860=0x245860; SUB_245919=0x245919
CAVE=0x203800
R7,R6,R13=7,6,13
mh=lambda r,v:('bg.movhi',{'D':r,'U':v})
lbz=lambda rd,off,ra:('bg.lbz',{'?':rd,'A':ra,'!':off})
sb=lambda off,ra,rb:('bg.sb',{'Y':off,'A':ra,'B':rb})
prog=[
 'cave_a:',            # refusal tail: keep pre-standby (dark, red LED), then panel off
 mh(R7,0x45), lbz(R6,0x51ae,R7), ('bn.ori',{'D':R6,'A':R6,'N':0x10}), sb(0x51ae,R7,R6),
 ('bg.j',{'/':SUB_245860}),
 'cave_b:',            # replaces jal sub_245919 at 0x23AED5 (relight on signal)
 mh(R7,0x45), lbz(R6,0x51cc,R7), ('bg.bnei',{'A':R6,'I':0,';':'b_lhs'}),
 lbz(R6,0x51ae,R7), ('bn.andi',{'D':R6,'A':R6,'N':0x10}), ('bg.bnei',{'A':R6,'I':0,';':'b_ret'}),
 ('bg.lhz',{'D':R6,'A':R7,'X':0x51ac}), ('bn.andi',{'D':R6,'A':R6,'N':0x02}), ('bg.bnei',{'A':R6,'I':0,';':'b_ret'}),  # power-save requested: gate decides first
 ('bg.j',{'/':SUB_245919}),
 'b_lhs:',             # leaving link-held standby on valid timing
 lbz(R6,0x51ae,R7), ('bn.andi',{'D':R6,'A':R6,'N':0xef}), sb(0x51ae,R7,R6),
 ('bg.lwz',{'D':R6,'A':R7,'W':0x3c70}), ('bg.ori',{'D':R6,'A':R6,'t':0x4000}), ('bg.sw',{'W':0x3c70,'A':R7,'B':R6}),
 ('bt.movi',{'D':R6,'I':2}), sb(0x51b5,R7,R6),
 ('bg.j',{'/':SUB_245919}),
 'b_ret:',
 ('bt.jr',{'A':9}),
 'cave_c:',            # key/event cancels pre-standby: leave LHS, full panel-on
 mh(R7,0x45), sb(0x51cc,R7,0),
 ('bg.j',{'/':SUB_245919}),
 'cave_d:',            # sub_263995 @0x263D10: no re-evaluation while refused
 mh(R13,0x45), lbz(R7,0x51cc,R13), ('bg.bnei',{'A':R7,'I':0,';':'d_skip'}),
 ('bg.j',{'/':0x263d14}),
 'd_skip:', ('bg.j',{'/':0x263cc2}),
 'cave_e:',            # sub_263995 @0x263C26: same for the 10-tick re-evaluation
 mh(R6,0x45), lbz(R6,0x51cc,R6), ('bg.bnei',{'A':R6,'I':0,';':'e_skip'}),
 ('bg.ori',{'D':R7,'A':10,'t':0x8000}), ('bg.j',{'/':0x263c2a}),
 'e_skip:', ('bg.j',{'/':0x263a6d}),
 'cave_k:',            # 0x259026: key cancels pre-standby; the power key (code 0x2A, r12) must not light the panel first
 ('bg.ori',{'D':R7,'A':0,'t':0x2a}), ('bg.beq',{'A':12,'B':R7,';':'k_pwr'}),
 ('bg.j',{'/':'cave_c'}),
 'k_pwr:',             # leave LHS; key_process then runs power-off (state 0, power_soft_off)
 mh(R7,0x45), sb(0x51cc,R7,0),
 ('bt.jr',{'A':9}),
]
code,L=S.assemble(prog,CAVE)
print('cave bytes',len(code))
for a,b,x in A.disasm(code,CAVE,CAVE+len(code),CAVE):
    lab=[k for k,v in L.items() if v==a]
    print(('%-8s'%(lab[0]+':' if lab else ''))+'%08x: %-12s %-9s %s'%(a,b.hex(' '),x['mnem'],x['ops']))
assert cur(CAVE,len(code))==b'\0'*len(code)
hooks=[
 (0x26145e,'bg.jal',SUB_245860,'pre-standby: guarded one-shot panel off (was sub_24578B)'),
 (0x261492,'bg.j',L['cave_a'],'refusal tail: set pre-standby flag, then panel off'),
 (0x23aed5,'bg.jal',L['cave_b'],'relight: honour LHS / pre-standby'),
 (0x259026,'bg.jal',L['cave_k'],'cancel pre-standby by key (was sub_2457FB); power key skips the panel-on'),
 (0x266b70,'bg.jal',L['cave_c'],'cancel pre-standby in sub_266B56 (was sub_2457FB)'),
 (0x263d10,'bg.j',L['cave_d'],'re-evaluation arming (2 ticks)'),
 (0x263c26,'bg.j',L['cave_e'],'re-evaluation arming (10 ticks)'),
]
edits=[]
for a,op,t,c in hooks:
    nb=S.encode(op,{'/':t},a); ob=cur(a,4)
    x=A.decode(ob,0,a); y=A.decode(nb,0,a)
    print('%x  %s %-22s -> %s %s   ; %s'%(a,ob.hex(),x['mnem']+' '+x['ops'],nb.hex(),y['mnem']+' '+y['ops'],c))
    edits.append({'addr':'0x%06X'%a,'old':ob.hex(),'new':nb.hex(),'asm':'%s %s -> %s %s (%s)'%(x['mnem'],x['ops'],y['mnem'],y['ops'],c)})
edits.insert(0,{'addr':'0x%06X'%CAVE,'old':'00'*len(code),'new':code.hex(),'asm':'code cave in linker padding 0x203800-0x203FFF (see notes)'})
out=os.environ.get('OUT','standby-lhs.json')
if os.path.exists(out):
    patch=json.load(open(out)); patch['edits']=edits
else:
    patch={'name':'standby-lhs','edits':edits}
json.dump(patch,open(out,'w'),indent=2)
open(out,'a').write('\n')
