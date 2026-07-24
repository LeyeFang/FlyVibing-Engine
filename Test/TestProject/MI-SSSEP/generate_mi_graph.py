"""
MI 纯实验节点图生成器 v2 — Timer 驱动。

实验设计:
  - 初始 5s 延迟, 60 trial, 每 trial 10s
  - Phase 0-2s: 随机 Left/Right cue 出现 + 发送 Parallel(11/12)
  - Phase 2-6s: cue 保持 + TaskCue 出现
  - Phase 6-10s: 所有 cue 隐藏
  - Cross 全程可见
  - 种子保存到 seed/

用法: python Test/TestProject/MI-SSSEP/generate_mi_graph.py
"""

import json, os

SCENE_PATH = os.path.join(os.path.dirname(__file__), "scenes", "MI.scene")
SEED_DIR = "Test/TestProject/MI-SSSEP/seed"
INITIAL_DELAY = 5.0; TRIAL_COUNT = 60
PARALLEL_ADDR = 0x3FF8

_nid, _pid, _lid = 200, 10000, 500
def nid(): global _nid; v=_nid; _nid+=1; return v
def pid(): global _pid; v=_pid; _pid+=1; return v
def lid(): global _lid; v=_lid; _lid+=1; return v

nodes: dict[str,dict] = {}; links: dict[str,dict] = {}
def N(t,pins,props=None,pos=(0,0)):
    i=nid(); nodes[str(i)]={"id":i,"node_type":t,"pos":list(pos),"props":props or {},"pin_ids":{p:pid() for p in pins}}; return i
def L(f,fp,t,tp):
    l=lid(); links[str(l)]={"id":l,"from_pin":nodes[str(f)]["pin_ids"][fp],"to_pin":nodes[str(t)]["pin_ids"][tp]}
def E(*c):
    for i in range(len(c)-1): L(c[i],"exec_out",c[i+1],"exec_in")

# event nodes
GS=161;FU=163;GP=166
nodes["161"]={"id":161,"node_type":"OnGameStart","pos":[80,80],"props":{},"pin_ids":{"exec":162}}
nodes["163"]={"id":163,"node_type":"OnFrameUpdate","pos":[80,280],"props":{},"pin_ids":{"exec":164,"delta":165}}
nodes["166"]={"id":166,"node_type":"OnGameStop","pos":[80,480],"props":{},"pin_ids":{"exec":167}}

# OnGameStart: seed + spawn + vars + timer
rs=N("RandomSetSeed",["exec_in","exec_out","Seed"],{"source":"hardware"})
vsd=N("VarGet",["exec_in","exec_out","Name","Value"],{"var_name":"_global_random_seed"})
pv=N("PathVar",["Path"],{"browse_mode":"directory","path":SEED_DIR})
td=N("TimeGetDate",["DateString"],{"year":True,"month":True,"day":True,"hour":True,"minute":True,"format":"MI-Seed-%Y-%m-%d-%H-%M"})
tfw=N("TextFileWrite",["exec_in","exec_out","FilePath","FileName","Value"],{"mode":"pin","write_mode":"w","delimiter":"newline"})
E(rs,vsd,tfw); L(pv,"Path",tfw,"FilePath"); L(td,"DateString",tfw,"FileName"); L(vsd,"Value",tfw,"Value")
sp=[N("EntitySpawn",["exec_in","exec_out","Entity"],{"template":t}) for t in ["Cross","LeftCue","RightCue","TaskCue"]]
E(tfw,*sp)

# initial hide
c0s=[N("Constant",["Result"],{"value":0}) for _ in range(5)]
egn=["arrow_body","arrow_head_copy","arrow_head","arrow_body_copy","TaskCue"]
egs=[N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":n}) for n in egn]
esrvs=[N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]) for _ in egn]
ch=[sp[-1]]+[n for p in zip(egs,esrvs) for n in p]; E(*ch)
for i,(eg,es) in enumerate(zip(egs,esrvs)): L(eg,"Entity",es,"EntityID"); L(c0s[i],"Result",es,"Visible")

vs_tr=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"manual","var_name":"trial","value":1})
vs_cv=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"manual","var_name":"cue_val","value":0})
nt=N("NewTimer",["exec_in","exec_out","Name"],{"mode":"manual","timer_name":"trial_phase"})
st=N("SetTimer",["exec_in","exec_out","Value"],{"operate":"set_time","mode":"manual","timer_name":"trial_phase","value":-INITIAL_DELAY})
E(esrvs[-1],vs_tr,vs_cv,nt,st)
L(GS,"exec",rs,"exec_in")

# OnFrameUpdate -> Sequence(4) -> 4x TimeTrigger
seq=N("Sequence",["exec_in","out_0","out_1","out_2","out_3","out_4"])
L(FU,"exec",seq,"exec_in")
def TT(t): return N("TimeTrigger",["exec_in","exec_out","Time","Elapsed","out_0","out_1","out_2","out_3","out_4","out_5","out_6","out_7"],{"mode":"manual","time":t,"timer":"trial_phase"})
tt0=TT(0); tt2=TT(2); tt6=TT(6); tt10=TT(10)
L(seq,"out_0",tt0,"exec_in"); L(seq,"out_1",tt2,"exec_in"); L(seq,"out_2",tt6,"exec_in"); L(seq,"out_3",tt10,"exec_in")

# Phase 0: Random(1-2) -> Left(11) or Right(12)
rand_mi=N("Random",["Min","Max","Mean","StdDev","Result"],{"distribution":"discrete","mode":"manual","min":1,"max":2})
cmp1=N("Compare",["A","B","Result"],{"operation":"eq"}); c1=N("Constant",["Result"],{"value":1})
br1=N("Branch",["exec_in","exec_out","Condition","True","False"])

# Left
c11=N("Constant",["Result"],{"value":11}); vs11=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"pin","var_name":"cue_val"})
egL1=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"arrow_body"})
esL1=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); cL1=N("Constant",["Result"],{"value":1})
egL2=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"arrow_head_copy"})
esL2=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); cL2=N("Constant",["Result"],{"value":1})
psL=N("ParallelSend",["exec_in","exec_out","Address","Value"],{"mode":"pin","address":PARALLEL_ADDR})
E(vs11,egL1,esL1,egL2,esL2,psL)
L(c11,"Result",vs11,"Value"); L(egL1,"Entity",esL1,"EntityID"); L(cL1,"Result",esL1,"Visible")
L(egL2,"Entity",esL2,"EntityID"); L(cL2,"Result",esL2,"Visible"); L(c11,"Result",psL,"Value")

# Right
c22=N("Constant",["Result"],{"value":12}); vs22=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"pin","var_name":"cue_val"})
egR1=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"arrow_head"})
esR1=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); cR1=N("Constant",["Result"],{"value":1})
egR2=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"arrow_body_copy"})
esR2=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); cR2=N("Constant",["Result"],{"value":1})
psR=N("ParallelSend",["exec_in","exec_out","Address","Value"],{"mode":"pin","address":PARALLEL_ADDR})
E(vs22,egR1,esR1,egR2,esR2,psR)
L(c22,"Result",vs22,"Value"); L(egR1,"Entity",esR1,"EntityID"); L(cR1,"Result",esR1,"Visible")
L(egR2,"Entity",esR2,"EntityID"); L(cR2,"Result",esR2,"Visible"); L(c22,"Result",psR,"Value")

L(tt0,"out_0",br1,"exec_in")
L(rand_mi,"Result",cmp1,"A"); L(c1,"Result",cmp1,"B"); L(cmp1,"Result",br1,"Condition")
L(br1,"True",vs11,"exec_in"); L(br1,"False",vs22,"exec_in")

# Phase 2: show TaskCue
eg_t2=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"TaskCue"})
es_t2=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); ct2=N("Constant",["Result"],{"value":1})
E(eg_t2,es_t2); L(eg_t2,"Entity",es_t2,"EntityID"); L(ct2,"Result",es_t2,"Visible")
L(tt2,"out_0",eg_t2,"exec_in")

# Phase 6: hide all
eh=[N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":n}) for n in egn]
sh=[N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]) for _ in egn]
ch6=[N("Constant",["Result"],{"value":0}) for _ in egn]
chx=[n for p in zip(eh,sh) for n in p]; E(*chx)
for i,(g,s) in enumerate(zip(eh,sh)): L(g,"Entity",s,"EntityID"); L(ch6[i],"Result",s,"Visible")
L(tt6,"out_0",eh[0],"exec_in")

# Phase 10: trial+=1, check exit, reset timer
vs_s0=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"manual","var_name":"second","value":0})
vg_tr=N("VarGet",["exec_in","exec_out","Name","Value"],{"var_name":"trial"})
sm_tr=N("ScalarMath",["In_0","In_1","Result","In_2","In_3","In_4","In_5","In_6","In_7"],{"operation":"sum"})
c1tr=N("Constant",["Result"],{"value":1})
vs_trN=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"pin","var_name":"trial"})
E(vs_s0,vg_tr,vs_trN)
L(vg_tr,"Value",sm_tr,"In_0"); L(c1tr,"Result",sm_tr,"In_1"); L(sm_tr,"Result",vs_trN,"Value")

vg_tc=N("VarGet",["exec_in","exec_out","Name","Value"],{"var_name":"trial"})
cmp60=N("Compare",["A","B","Result"],{"operation":"gt"}); c60v=N("Constant",["Result"],{"value":TRIAL_COUNT})
br_ex=N("Branch",["exec_in","exec_out","Condition","True","False"])
exit_n=N("ExitGame",["exec_in"])
E(vs_trN,vg_tc,br_ex)
L(vg_tc,"Value",cmp60,"A"); L(c60v,"Result",cmp60,"B"); L(cmp60,"Result",br_ex,"Condition")
L(br_ex,"True",exit_n,"exec_in")
st_rst=N("SetTimer",["exec_in","exec_out","Value"],{"operate":"set_time","mode":"manual","timer_name":"trial_phase","value":-0.02})
L(br_ex,"False",st_rst,"exec_in")
L(tt10,"out_0",vs_s0,"exec_in")

# next_id
all_ids=set()
for n in nodes.values():
    all_ids.add(n["id"])
    for v in n["pin_ids"].values(): all_ids.add(v)
for l in links.values(): all_ids.add(l["id"])
graph={"version":"0.1.0","nodes":nodes,"links":links,"next_id":max(all_ids)+1 if all_ids else 200}

if __name__=="__main__":
    if not os.path.exists(SCENE_PATH): print(f"ERROR: {SCENE_PATH}"); exit(1)
    with open(SCENE_PATH,"r",encoding="utf-8") as f: data=json.load(f)
    data["scene"]["node_graph"]=graph
    with open(SCENE_PATH,"w",encoding="utf-8") as f: json.dump(data,f,indent=2,ensure_ascii=False)
    print(f"[MI v2] {len(nodes)} nodes, {len(links)} links -> {SCENE_PATH}")
