#!/usr/bin/env python3
"""Replay analysis goals through each backend's natural interface.

The workflow is goal-oriented: a backend can take different steps, but every
step must help locate or inspect the evidence. Build, hashing and timing
orchestration are excluded from analysis-call counts.
"""
from __future__ import annotations

import argparse, json, os, random, re, statistics, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
APK = Path(os.environ.get("APK", "douyin-40.7.0.apk"))
TRIALS = 3

GOALS = {
 "manifest_exported_components": dict(kind="manifest", needle="", classes=[], expect=["TTDownloaderProvider","MicroGameContentProvider","DataUnionActivity"]),
 "ttdownloader_provider_db": dict(kind="string", needle="ttdownloaderClickId", classes=["com.ss.android.downloadlib.addownload.TTDownloaderProvider"], expect=["downloadUrl TEXT","SQLiteDatabase","query"]),
 "microgame_fileprovider_io": dict(kind="string", needle="gamecp.micro.order.fileprovider", classes=["com.bytedance.android.gamecp.business.orderdownload.gameresource.preload.MicroGameContentProvider"], expect=["openFile","ParcelFileDescriptor","delete"]),
 "gameres_uri_permissions": dict(kind="string", needle="com.ss.android.ugc.aweme/res_task", classes=["com.bytedance.android.gamecp.business.download.predownload.GameResContentProvider"], expect=["grantUriPermission","fileUri","delete"]),
 "secshare_provider_paths": dict(kind="string", needle="sec_share_data_file", classes=["com.ss.android.account.share.data.write.provider.SecShareDataProvider","X.02ju"], expect=["getLastPathSegment","File","com.ss.android.ucenter.cn"]),
 "aic_gzip_decode_limits": dict(kind="string", needle="gzip-base64url", classes=["com.ss.android.ugc.aweme.aicatom.AicAtomCardProtocolPreviewActivity","X.0Cpb"], expect=["GZIPInputStream","readText","messages"]),
 "widget_confirm_action": dict(kind="string", needle="positive_action", classes=["com.bytedance.android.ug.expore.widget.autoinstall.WidgetConfirmActivity","X.0ltK"], expect=["positive_action","DeepLinkHandlerActivity","setData"]),
 "luckycat_ssl_error_handling": dict(kind="method", needle="onReceivedSslError", extra_searches=[("string","LuckyCatBridge3")], classes=["com.bytedance.ug.sdk.luckycat.impl.browser.webview.LuckyCatWebViewClient"], expect=["SslErrorHandler","proceed","LuckyCatAuthBridge"]),
 "lmhttp_tls_setup": dict(kind="method", needle="setupHttpsTrust", classes=["com.bytedance.llama.cllama.engine.LMHttp","X.0mZq","X.0mZp","X.0oM3"], expect=["checkServerTrusted","return true","FileOutputStream"]),
 "cjpay_webview_config": dict(kind="string", needle="http://atu-pay-test.shouqianpay.com", classes=["com.ss.android.ugc.aweme.cjpay.CJWebScanResultHandler","com.bytedance.caijing.sdk.infra.base.impl.jsb.JsbServiceImpl$getH5JSBridgeHelper$1"], expect=["aweme://webview","http://","JS2NativeBridge"]),
}

def descriptor(name: str) -> str:
 return "L" + name.replace(".", "/") + ";"

class Mcp:
 def __init__(self, cmd):
  self.cmd=cmd; self.next=1
  self.p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
  self.request("initialize",{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"audit-replay","version":"1"}})
  self.send({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})
 def send(self,x):
  self.p.stdin.write(json.dumps(x,separators=(",",":"))+"\n");self.p.stdin.flush()
 def request(self,method,params):
  ident=self.next;self.next+=1;self.send({"jsonrpc":"2.0","id":ident,"method":method,"params":params})
  while True:
   line=self.p.stdout.readline()
   if not line: raise RuntimeError(f"MCP exited: {self.p.stderr.read()}")
   msg=json.loads(line)
   if msg.get("id")==ident:
    if "error" in msg: raise RuntimeError(str(msg["error"]))
    return msg.get("result",{})
 def tool(self,name,args): return self.request("tools/call",{"name":name,"arguments":args})
 def close(self):
  if self.p.poll() is None:
   self.p.terminate()
   try:self.p.wait(5)
   except subprocess.TimeoutExpired:self.p.kill();self.p.wait(5)

def text_of(x):
 if isinstance(x,str):return x
 if isinstance(x,(int,float,bool)) or x is None:return json.dumps(x)
 if isinstance(x,list):return "\n".join(text_of(v) for v in x)
 if isinstance(x,dict):
  parts=[]
  if x.get("structuredContent") is not None:parts.append(text_of(x["structuredContent"]))
  for item in x.get("content",[]):
   if isinstance(item,dict) and item.get("type")=="text":parts.append(item.get("text",""))
  return "\n".join(parts) if parts else json.dumps(x,ensure_ascii=False)
 return str(x)

def timed(fn):
 t=time.perf_counter(); value=fn(); return value,(time.perf_counter()-t)*1000

class Ddc:
 name="ddc-mcp"
 def __init__(self):
  self.c=Mcp([str(ROOT/"ddc/target/release/ddc"),"mcp","stdio"]);self.startup_ms=None
 def run(self,g):
  calls=[]; outputs=[]
  if g["kind"]=="manifest": specs=[("ddc.manifest",{"input":str(APK)})]
  else:
   specs=[("ddc.findrefs",{"input":str(APK),"kind":g["kind"],"query":g["needle"]})]
   specs += [("ddc.findrefs",{"input":str(APK),"kind":k,"query":q}) for k,q in g.get("extra_searches",[])]
   specs += [("ddc.getclass",{"input":str(APK),"class":c}) for c in g["classes"]]
  for name,args in specs:
   value,ms=timed(lambda n=name,a=args:self.c.tool(n,a));calls.append({"tool":name,"arguments":args,"ms":ms});outputs.append(text_of(value))
  return calls,"\n".join(outputs)
 def close(self):self.c.close()

class DexDec:
 name="dexdec-mcp"
 def __init__(self):
  t=time.perf_counter();self.c=Mcp([str(ROOT/"dexdec/target/release/dexdec-mcp"),"--allow-root",str(APK.parent)]);self.initialize_ms=(time.perf_counter()-t)*1000
  value,self.open_ms=timed(lambda:self.c.tool("open_project",{"path":str(APK)}))
  body=value.get("structuredContent") or json.loads(value["content"][0]["text"]);self.pid=body["projectId"]
 def run(self,g):
  calls=[];outputs=[]
  if g["kind"]=="manifest":specs=[("read_archive_resource",{"projectId":self.pid,"path":"AndroidManifest.xml"})]
  else:
   specs=[("search_symbols",{"projectId":self.pid,"query":g["needle"],"limit":100})]
   specs += [("search_symbols",{"projectId":self.pid,"query":q,"limit":100}) for _,q in g.get("extra_searches",[])]
   specs += [("decompile_class",{"projectId":self.pid,"descriptor":descriptor(c),"language":"java","includeNested":True}) for c in g["classes"]]
  for name,args in specs:
   value,ms=timed(lambda n=name,a=args:self.c.tool(n,a));calls.append({"tool":name,"arguments":args,"ms":ms});outputs.append(text_of(value))
  return calls,"\n".join(outputs)
 def close(self):
  try:self.c.tool("close_project",{"projectId":self.pid})
  finally:self.c.close()

class JadxApi:
 name="jadx-api"
 def __init__(self,threads=12):
  cmd=["java","-Xmx24g","-Djava.util.concurrent.ForkJoinPool.common.parallelism="+str(threads),"-cp",str(ROOT)+os.pathsep+os.environ.get("JADX_JAR", "jadx-1.5.6-all.jar"),"JadxAuditProbe",str(APK),str(threads)]
  t=time.perf_counter();self.p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
  self.ready=self._read();self.open_ms=(time.perf_counter()-t)*1000
 def _read(self):
  while True:
   line=self.p.stdout.readline()
   if not line:raise RuntimeError(self.p.stderr.read())
   if line.startswith("AUDIT_JSON:"):return json.loads(line[11:])
 def call(self,kind,needle=""):
  self.p.stdin.write(json.dumps({"kind":kind,"needle":needle})+"\n");self.p.stdin.flush();return self._read()
 def run(self,g):
  calls=[];outputs=[]; specs=[("manifest","")] if g["kind"]=="manifest" else [(g["kind"],g["needle"]),*g.get("extra_searches",[]),*[("class",c) for c in g["classes"]]]
  for kind,needle in specs:
   value,ms=timed(lambda k=kind,n=needle:self.call(k,n));calls.append({"api":kind,"needle":needle,"ms":ms});outputs.append(text_of(value.get("result","")))
  return calls,"\n".join(outputs)
 def close(self):
  self.p.terminate()
  try:self.p.wait(5)
  except subprocess.TimeoutExpired:self.p.kill();self.p.wait(5)

class DroidSaw:
 name="droidsaw-cli"
 def __init__(self,threads=8):
  self.bin=str(ROOT/"droidsaw-install/bin/droidsaw");self.env={**os.environ,"RAYON_NUM_THREADS":str(threads)}
 def call(self,args):
  cmd=[self.bin,"--no-auto-splits",*args];p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=self.env,timeout=180)
  if p.returncode:raise RuntimeError(f"{cmd}: {p.stderr}\n{p.stdout}")
  return cmd,p.stdout
 def run(self,g):
  if g["kind"]=="manifest":specs=[["manifest",str(APK)]]
  elif g["kind"]=="string":specs=[["xrefs",str(APK),"--search",re.escape(g["needle"])]]
  else:specs=[["dex","methods",str(APK),"--implementations","--search",re.escape(g["needle"])]]
  for kind,needle in g.get("extra_searches",[]):
   specs.append(["xrefs",str(APK),"--search",re.escape(needle)] if kind=="string" else ["dex","methods",str(APK),"--implementations","--search",re.escape(needle)])
  # droidsaw 2.0.0 reports an exact inner-class descriptor as a close match but
  # then rejects it; opening the outer class is the fastest usable fallback.
  specs += [["decompile",str(APK),descriptor(c.split("$",1)[0])] for c in g["classes"]]
  calls=[];outputs=[]
  for args in specs:
   (cmd,value),ms=timed(lambda a=args:self.call(a));calls.append({"command":cmd,"ms":ms});outputs.append(value)
  return calls,"\n".join(outputs)
 def close(self):pass

def bench(backend, trials):
 first={}; validation={}
 for name,g in GOALS.items():
  calls,out=backend.run(g); first[name]={"calls":calls,"total_ms":sum(c["ms"] for c in calls)}
  validation[name]={"missing_tokens":[x for x in g["expect"] if x not in out],"output_bytes":len(out.encode())}
 samples={name:[] for name in GOALS};order=[n for n in GOALS for _ in range(trials)];random.Random(1937).shuffle(order)
 for name in order:
  calls,_=backend.run(GOALS[name]);samples[name].append(sum(c["ms"] for c in calls))
 return {"backend":backend.name,"apk":str(APK),"trials":trials,"first_use":first,"hot":{n:{"median_ms":statistics.median(v) if v else None,"samples_ms":sorted(v)} for n,v in samples.items()},"validation":validation,"analysis_call_count_first_pass":sum(len(x["calls"]) for x in first.values()),"external_helpers":[]}

def main():
 ap=argparse.ArgumentParser();ap.add_argument("backend",choices=["ddc","dexdec","jadx-api","droidsaw"]);ap.add_argument("--trials",type=int,default=TRIALS);a=ap.parse_args();RESULTS.mkdir(exist_ok=True)
 cls={"ddc":Ddc,"dexdec":DexDec,"jadx-api":JadxApi,"droidsaw":DroidSaw}[a.backend];backend=cls()
 try:result=bench(backend,a.trials)
 finally:backend.close()
 for attr in ("initialize_ms","open_ms","ready"):
  if hasattr(backend,attr):result[attr]=getattr(backend,attr)
 path=RESULTS/(a.backend+"-audit-replay.json");path.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(path)
 for n,v in result["hot"].items():print(n,round(v["median_ms"],3) if v["median_ms"] is not None else "no-hot-trials",result["validation"][n]["missing_tokens"])

if __name__=="__main__":main()
