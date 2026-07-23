"""
MI-SSSEP combined experiment v3.

Usage: python Test/TestProject/MI-SSSEP/generate_mi_graph.py
"""

import json, os

SCENE_PATH = os.path.join(os.path.dirname(__file__), "scenes", "MI-SSSEP.scene")
SEED_DIR = "Test/TestProject/MI-SSSEP/seed"
INITIAL_DELAY = 5.0; TRIAL_COUNT = 60; PULSE_N = 80; PULSE_MS = 0.05
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

# OnGameStart: seed + spawn + vars + 2 timers
rs=N("RandomSetSeed",["exec_in","exec_out","Seed"],{"source":"hardware"})
vsd=N("VarGet",["exec_in","exec_out","Name","Value"],{"var_name":"_global_random_seed"})
pv=N("PathVar",["Path"],{"browse_mode":"directory","path":SEED_DIR})
td=N("TimeGetDate",["DateString"],{"year":True,"month":True,"day":True,"hour":True,"minute":True,"format":"MI-SSSEP-Seed-%Y-%m-%d-%H-%M"})
tfw=N("TextFileWrite",["exec_in","exec_out","FilePath","FileName","Value"],{"mode":"pin","write_mode":"w","delimiter":"newline"})
E(rs,vsd,tfw); L(pv,"Path",tfw,"FilePath"); L(td,"DateString",tfw,"FileName"); L(vsd,"Value",tfw,"Value")
sp=[N("EntitySpawn",["exec_in","exec_out","Entity"],{"template":t}) for t in ["Cross","LeftCue","RightCue","TaskCue","NullCue"]]
E(tfw,*sp)
c0=[N("Constant",["Result"],{"value":0}) for _ in range(7)]
egn=["L_arrow_body","L_arrow_head","R_arrow_head","R_arrow_body","TaskCue","part1","part2"]
eg=[N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":n}) for n in egn]
es=[N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]) for _ in egn]
ch=[sp[-1]]+[n for p in zip(eg,es) for n in p]; E(*ch)
for i,(g,s) in enumerate(zip(eg,es)): L(g,"Entity",s,"EntityID"); L(c0[i],"Result",s,"Visible")
vs_tr=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"manual","var_name":"trial","value":1})
vs_mi=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"manual","var_name":"mi_code","value":0})
vs_ss=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"manual","var_name":"sss_code","value":0})
vs_tg=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"manual","var_name":"trigger_val","value":0})
vs_pc=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"manual","var_name":"pulse_count","value":0})
E(es[-1],vs_tr,vs_mi,vs_ss,vs_tg,vs_pc)
nt1=N("NewTimer",["exec_in","exec_out","Name"],{"mode":"manual","timer_name":"trial_phase"})
st1=N("SetTimer",["exec_in","exec_out","Value"],{"operate":"set_time","mode":"manual","timer_name":"trial_phase","value":-INITIAL_DELAY})
nt2=N("NewTimer",["exec_in","exec_out","Name"],{"mode":"manual","timer_name":"pulse"})
E(vs_pc,nt1,st1,nt2)
L(GS,"exec",rs,"exec_in")

# OnFrameUpdate -> Sequence(5)
seq=N("Sequence",["exec_in","out_0","out_1","out_2","out_3","out_4"])
L(FU,"exec",seq,"exec_in")
def TT(t,tmr): return N("TimeTrigger",["exec_in","exec_out","Time","Elapsed","out_0","out_1","out_2","out_3","out_4","out_5","out_6","out_7"],{"mode":"manual","time":t,"timer":tmr})
tt0=TT(0,"trial_phase"); tt2=TT(2,"trial_phase"); tt6=TT(6,"trial_phase"); tt10=TT(10,"trial_phase"); ttp=TT(0,"pulse")
L(seq,"out_0",tt0,"exec_in"); L(seq,"out_1",tt2,"exec_in"); L(seq,"out_2",tt6,"exec_in"); L(seq,"out_3",tt10,"exec_in"); L(seq,"out_4",ttp,"exec_in")

# Phase 0: pick MI(1-3) + SSSEP(11-24) + encode + show cue
rand_mi=N("Random",["Min","Max","Mean","StdDev","Result"],{"distribution":"discrete","mode":"manual","min":1,"max":3})
rand_ss=N("Random",["Min","Max","Mean","StdDev","Result"],{"distribution":"discrete","mode":"manual","min":11,"max":24})
vs_ss0=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"pin","var_name":"sss_code"})
cmp1=N("Compare",["A","B","Result"],{"operation":"eq"}); c1m=N("Constant",["Result"],{"value":1})
br1=N("Branch",["exec_in","exec_out","Condition","True","False"])
cmp2=N("Compare",["A","B","Result"],{"operation":"eq"}); c2m=N("Constant",["Result"],{"value":2})
br2=N("Branch",["exec_in","exec_out","Condition","True","False"])
vg_ss=N("VarGet",["exec_in","exec_out","Name","Value"],{"var_name":"sss_code"})

# -- Left (MI=1)
cL_mi=N("Constant",["Result"],{"value":1}); vsL_mi=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"pin","var_name":"mi_code"})
egL1=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"L_arrow_body"})
esL1=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); cL1=N("Constant",["Result"],{"value":1})
egL2=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"L_arrow_head"})
esL2=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); cL2=N("Constant",["Result"],{"value":1})
cL64=N("Constant",["Result"],{"value":64}); smL=N("ScalarMath",["In_0","In_1","Result","In_2","In_3","In_4","In_5","In_6","In_7"],{"operation":"sum"})
vsL_tg=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"pin","var_name":"trigger_val"})
E(vsL_mi,egL1,esL1,egL2,esL2,vsL_tg)
L(cL_mi,"Result",vsL_mi,"Value"); L(egL1,"Entity",esL1,"EntityID"); L(cL1,"Result",esL1,"Visible")
L(egL2,"Entity",esL2,"EntityID"); L(cL2,"Result",esL2,"Visible")
L(cL64,"Result",smL,"In_0"); L(vg_ss,"Value",smL,"In_1"); L(smL,"Result",vsL_tg,"Value")

# -- Right (MI=2)
cR_mi=N("Constant",["Result"],{"value":2}); vsR_mi=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"pin","var_name":"mi_code"})
egR1=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"R_arrow_head"})
esR1=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); cR1=N("Constant",["Result"],{"value":1})
egR2=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"R_arrow_body"})
esR2=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); cR2=N("Constant",["Result"],{"value":1})
cR128=N("Constant",["Result"],{"value":128}); smR=N("ScalarMath",["In_0","In_1","Result","In_2","In_3","In_4","In_5","In_6","In_7"],{"operation":"sum"})
vsR_tg=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"pin","var_name":"trigger_val"})
E(vsR_mi,egR1,esR1,egR2,esR2,vsR_tg)
L(cR_mi,"Result",vsR_mi,"Value"); L(egR1,"Entity",esR1,"EntityID"); L(cR1,"Result",esR1,"Visible")
L(egR2,"Entity",esR2,"EntityID"); L(cR2,"Result",esR2,"Visible")
L(cR128,"Result",smR,"In_0"); L(vg_ss,"Value",smR,"In_1"); L(smR,"Result",vsR_tg,"Value")

# -- None (MI=3) — 显示 NullCue (part1+part2) 告知被试不 MI
cN_mi=N("Constant",["Result"],{"value":3}); vsN_mi=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"pin","var_name":"mi_code"})
egN1=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"part1"})
esN1=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); cN1=N("Constant",["Result"],{"value":1})
egN2=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"part2"})
esN2=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); cN2=N("Constant",["Result"],{"value":1})
cN192=N("Constant",["Result"],{"value":192}); smN=N("ScalarMath",["In_0","In_1","Result","In_2","In_3","In_4","In_5","In_6","In_7"],{"operation":"sum"})
vsN_tg=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"pin","var_name":"trigger_val"})
E(vsN_mi,egN1,esN1,egN2,esN2,vsN_tg)
L(cN_mi,"Result",vsN_mi,"Value"); L(egN1,"Entity",esN1,"EntityID"); L(cN1,"Result",esN1,"Visible")
L(egN2,"Entity",esN2,"EntityID"); L(cN2,"Result",esN2,"Visible")
L(cN192,"Result",smN,"In_0"); L(vg_ss,"Value",smN,"In_1"); L(smN,"Result",vsN_tg,"Value")

# wire MI decision
L(tt0,"out_0",vs_ss0,"exec_in"); L(rand_ss,"Result",vs_ss0,"Value")
E(vs_ss0,br1)
L(rand_mi,"Result",cmp1,"A"); L(c1m,"Result",cmp1,"B"); L(cmp1,"Result",br1,"Condition")
L(br1,"True",vsL_mi,"exec_in")
L(br1,"False",br2,"exec_in")
L(rand_mi,"Result",cmp2,"A"); L(c2m,"Result",cmp2,"B"); L(cmp2,"Result",br2,"Condition")
L(br2,"True",vsR_mi,"exec_in"); L(br2,"False",vsN_mi,"exec_in")

# Phase 2: show TaskCue + start pulse
eg_t2=N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":"TaskCue"})
es_t2=N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]); ct2=N("Constant",["Result"],{"value":1})
vs_pc0=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"manual","var_name":"pulse_count","value":0})
st_pulse=N("SetTimer",["exec_in","exec_out","Value"],{"operate":"set_time","mode":"manual","timer_name":"pulse","value":-PULSE_MS})
E(eg_t2,es_t2,vs_pc0,st_pulse)
L(eg_t2,"Entity",es_t2,"EntityID"); L(ct2,"Result",es_t2,"Visible")
L(tt2,"out_0",eg_t2,"exec_in")

# Pulse loop: 80 pulses @50ms
vg_pc=N("VarGet",["exec_in","exec_out","Name","Value"],{"var_name":"pulse_count"})
cmp80=N("Compare",["A","B","Result"],{"operation":"lt"}); c80=N("Constant",["Result"],{"value":PULSE_N})
br_pulse=N("Branch",["exec_in","exec_out","Condition","True","False"])
vg_tg=N("VarGet",["exec_in","exec_out","Name","Value"],{"var_name":"trigger_val"})
ps=N("ParallelSend",["exec_in","exec_out","Address","Value"],{"mode":"pin","address":PARALLEL_ADDR})
vg_ss2=N("VarGet",["exec_in","exec_out","Name","Value"],{"var_name":"sss_code"})
ss=N("SerialSend",["exec_in","exec_out","Value"],{"mode":"pin","format":"string","port":"COM3","baud_rate":115200})
vg_pc2=N("VarGet",["exec_in","exec_out","Name","Value"],{"var_name":"pulse_count"})
sm_pc=N("ScalarMath",["In_0","In_1","Result","In_2","In_3","In_4","In_5","In_6","In_7"],{"operation":"sum"})
c1_pc=N("Constant",["Result"],{"value":1})
vs_pcN=N("VarSet",["exec_in","exec_out","Name","Value"],{"mode":"pin","var_name":"pulse_count"})
st_rearm=N("SetTimer",["exec_in","exec_out","Value"],{"operate":"set_time","mode":"manual","timer_name":"pulse","value":-PULSE_MS})
E(vg_pc,br_pulse)
L(vg_pc,"Value",cmp80,"A"); L(c80,"Result",cmp80,"B"); L(cmp80,"Result",br_pulse,"Condition")
E(ps,ss,vg_pc2,vs_pcN,st_rearm)
L(vg_tg,"Value",ps,"Value"); L(vg_ss2,"Value",ss,"Value")
L(vg_pc2,"Value",sm_pc,"In_0"); L(c1_pc,"Result",sm_pc,"In_1"); L(sm_pc,"Result",vs_pcN,"Value")
L(ttp,"out_0",vg_pc,"exec_in"); L(br_pulse,"True",ps,"exec_in")

# Phase 6: hide all
eh=[N("EntityGet",["exec_in","exec_out","Name","Entity"],{"entity_name":n}) for n in egn]
sh=[N("EntitySetRenderVisible",["exec_in","exec_out","EntityID","Visible"]) for _ in egn]
ch6=[N("Constant",["Result"],{"value":0}) for _ in egn]
chx=[n for p in zip(eh,sh) for n in p]; E(*chx)
for i,(g,s) in enumerate(zip(eh,sh)): L(g,"Entity",s,"EntityID"); L(ch6[i],"Result",s,"Visible")
L(tt6,"out_0",eh[0],"exec_in")

# Phase 10: trial+=1, check exit, reset
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
    print(f"[MI-SSSEP v3] {len(nodes)} nodes, {len(links)} links -> {SCENE_PATH}")
