#!/usr/bin/env python3
"""Replay analysis goals using prepared garlic output plus necessary rg reads."""
from __future__ import annotations
import json, random, statistics, subprocess, time
from pathlib import Path
from replay_audit import GOALS, Mcp, ROOT, RESULTS, APK, timed, text_of

ANALYSIS=RESULTS/"garlic-analysis"; DB=ANALYSIS/"analysis.duckdb"; SRC=ANALYSIS/"decompiled"
BIN=ROOT/"garlic/build-release/garlic"

def source_path(name):
 p=SRC/(name.replace(".","/")+".java")
 if p.exists():return p
 outer=name.split("$",1)[0]
 return SRC/(outer.replace(".","/")+".java")
def sql_for(g):
 q=g["needle"].replace("'","''")
 if g["kind"]=="method": return f"SELECT method_raw FROM java_cg_nodes WHERE method_raw ILIKE '%{q}%' ORDER BY method_raw LIMIT 100"
 return "SELECT DISTINCT n.method_raw FROM string_nodes s JOIN string_edges e ON e.string_id=s.id JOIN java_cg_nodes n ON n.node_id=e.method_id " + f"WHERE s.str LIKE '%{q}%' ORDER BY n.method_raw LIMIT 100"

def mcp_call(name,args):
 c=Mcp([str(BIN),"-m"])
 try:return c.tool(name,args)
 finally:c.close()

def run_goal(g):
 calls=[];out=[]
 if g["kind"]=="manifest":
  value,ms=timed(lambda:mcp_call("android_manifest",{"output_dir":str(ANALYSIS/'decompiled')}));calls.append({"tool":"garlic.android_manifest","arguments":{"output_dir":str(ANALYSIS/'decompiled')},"ms":ms});out.append(text_of(value))
 else:
  sql=sql_for(g);value,ms=timed(lambda:mcp_call("cg_query",{"db_path":str(DB),"sql":sql}));calls.append({"tool":"garlic.cg_query","arguments":{"db_path":str(DB),"sql":sql},"ms":ms});out.append(text_of(value))
  for kind,needle in g.get("extra_searches",[]):
   extra={**g,"kind":kind,"needle":needle};sql=sql_for(extra);value,ms=timed(lambda s=sql:mcp_call("cg_query",{"db_path":str(DB),"sql":s}));calls.append({"tool":"garlic.cg_query","arguments":{"db_path":str(DB),"sql":sql},"ms":ms});out.append(text_of(value))
  paths=[source_path(c) for c in g["classes"] if source_path(c).exists()]
  cmd=["rg","-n","--fixed-strings"]
  for token in g["expect"]:cmd += ["-e",token]
  cmd += [str(p) for p in paths]
  def grep():
   p=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   if p.returncode not in (0,1):raise RuntimeError(p.stderr)
   return p.stdout
  value,ms=timed(grep);calls.append({"external_tool":"rg","purpose":"read only the already identified decompiled classes for the goal evidence","command":cmd,"ms":ms});out.append(value)
  combined="\n".join(out)
  for token in (x for x in g["expect"] if x not in combined):
   locate=["rg","-l","--fixed-strings",token,str(SRC)]
   def find_files(c=locate):
    p=subprocess.run(c,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode not in (0,1):raise RuntimeError(p.stderr)
    return p.stdout
   files,ms=timed(find_files);calls.append({"external_tool":"rg","purpose":"follow missing evidence token from the identified class into linked decompiled sources","command":locate,"ms":ms})
   candidates=files.splitlines()[:5]
   if candidates:
    inspect=["rg","-n","--fixed-strings",token,*candidates]
    value,ms=timed(lambda c=inspect:subprocess.run(c,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout)
    calls.append({"external_tool":"rg","purpose":"inspect candidate sources located by the prior evidence search","command":inspect,"ms":ms});out.append(value);combined += "\n"+value
 return calls,"\n".join(out)

def main():
 RESULTS.mkdir(exist_ok=True);trials=3;first={};validation={}
 for name,g in GOALS.items():
  calls,out=run_goal(g);first[name]={"calls":calls,"total_ms":sum(x["ms"] for x in calls)};validation[name]={"missing_tokens":[x for x in g["expect"] if x not in out],"output_bytes":len(out.encode())}
 samples={x:[] for x in GOALS};order=[x for x in GOALS for _ in range(trials)];random.Random(1937).shuffle(order)
 for name in order:
  calls,_=run_goal(GOALS[name]);samples[name].append(sum(x["ms"] for x in calls))
 result={"backend":"garlic-mcp","apk":str(APK),"trials":trials,"preparation":{"tool":"garlic.analyze","elapsed_ms":json.load(open(RESULTS/'garlic-analyze.json'))["elapsed_ms"],"output_dir":str(ANALYSIS)},"first_use":first,"hot":{n:{"median_ms":statistics.median(v),"samples_ms":sorted(v)} for n,v in samples.items()},"validation":validation,"analysis_call_count_first_pass":sum(len(x["calls"]) for x in first.values()),"external_helpers":["DuckDB CLI 1.5.6: required internally by garlic cg_import/cg_query","rg: exact reads of identified Java files; one invocation per non-manifest goal"]}
 p=RESULTS/'garlic-audit-replay.json';p.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(p)
 for n,v in result["hot"].items():print(n,round(v["median_ms"],3),validation[n]["missing_tokens"])
if __name__=='__main__':main()
