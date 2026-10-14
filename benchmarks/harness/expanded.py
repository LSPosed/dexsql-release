"""Pinned-backend query benchmark. Pass a JSON config with local tool paths.

Measured wall time includes tool calls, result decoding and set composition.
Memory is sampled over the complete child-process tree every 50 ms.
"""
import argparse,json,os,queue,re,statistics,subprocess,sys,threading,time
from pathlib import Path
import psutil
from run import Process,SQL,ANCHOR,CLASS,normalize,rows_digest,digest
from garlic import GarlicClient,QUERIES as GARLIC_QUERIES,UNSUPPORTED as GARLIC_UNSUPPORTED

TARGET='Liu3/a;->a(JZ)Ljava/lang/String;'
GIF='gifFilePath gifPath:'
BITMAP='Landroid/graphics/Bitmap;->getWidth()I'
CASES=['class','method','string','callers','twohop','string_call','four_fact','complex']
SQL.update({k:(Path(__file__).parent/'queries'/(k+'.sql')).read_text(encoding='utf-8') for k in ['string_call','four_fact','complex']})
SQL['callers']=f"SELECT DISTINCT method FROM method_calls WHERE callee = '{TARGET}' ORDER BY method"
SQL['twohop']=f"WITH first_hop AS (SELECT DISTINCT method FROM method_calls WHERE callee = '{TARGET}') SELECT DISTINCT c.method FROM method_calls c JOIN first_hop f ON c.callee=f.method ORDER BY c.method"

def owner(s):
 if s.startswith('L') and s.endswith(';'):return s
 return 'L'+s.replace('.','/')+';'

class Unsupported(Exception):pass

class Memory:
 def __init__(self,roots):
  self.roots=roots;self.stop=threading.Event();self.samples=[]
  self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
 def sample(self):
  processes={}
  for p in list(self.roots):
   try:
    root=psutil.Process(p.p.pid);processes[root.pid]=root
    processes.update({x.pid:x for x in root.children(recursive=True)})
   except psutil.Error:pass
  private=rss=0
  for p in processes.values():
   try:
    m=p.memory_info();rss+=m.rss;private+=getattr(m,'private',0)
   except psutil.Error:pass
  return {'private_bytes':private,'rss_bytes':rss,'processes':len(processes)}
 def run(self):
  while not self.stop.wait(.05):self.samples.append(self.sample())
 def close(self):
  self.stop.set();self.thread.join();self.samples.append(self.sample())
  return self.summary()
 def summary(self):
  return {'sampling_interval_ms':50,'sample_count':len(self.samples),
          'peak_private_bytes':max((x['private_bytes'] for x in self.samples),default=0),
          'peak_rss_bytes':max((x['rss_bytes'] for x in self.samples),default=0)}

class Backend:
 def __init__(self,name,c,out,label):
  self.name=name;self.c=c;self.out=out;self.label=label;self.ps=[];self.memory=Memory(self.ps)
  self.deadline=time.perf_counter()+240
 def launch(self,args):
  env=dict(os.environ,RAYON_NUM_THREADS=str(self.c.get('threads',8)),
           JADX_CONFIG_DIR=self.c.get('jadx_config',''),JADX_CACHE_DIR=str(self.out/(self.label+'-cache')))
  p=Process(args,self.out/(self.label+f'-{len(self.ps)}.log'),env);self.ps.append(p);return p
 def start(self):
  c=self.c;n=self.name;t=time.perf_counter()
  if n=='dexsql':
   self.p=self.launch([c[n],'--threads',str(c.get('threads',8)),'mcp','--timeout-ms','120000','--max-dex-bytes','2147483648']);self.p.init()
   self.did=self.p.call('open_dataset',{'inputs':[c['apk']]},240)['dataset_id']
  elif n in ['jadx-core','jadx-mcp']:
   self.p=self.launch([c.get('java','java'),'-Xmx24g','-Djava.util.concurrent.ForkJoinPool.common.parallelism=8','-cp',c['probe_classes']+os.pathsep+c['jadx_jar'],'JadxProbe','gui' if n=='jadx-mcp' else 'core',c['apk'],'8'])
   d=self.p.q.get(timeout=240)
   if not d.get('ready'):raise RuntimeError(d)
   if n=='jadx-mcp':self.p=self.launch([c['mcp_python'],c['jadx_mcp_server']]);self.p.init()
  elif n=='asc':
   self.p=self.launch([c['asc_python'],str(Path(__file__).with_name('asc_probe.py')),c['apk'],'8'])
   if not self.p.q.get(timeout=30).get('ready'):raise RuntimeError('ASC start failed')
  elif n=='droidsaw-cli':pass
  elif n=='garlic':
   self.garlic=GarlicClient(c,self.out,self.label,self.ps);self.garlic.prepare()
  else:
   cmd=[c[n]]
   if n=='ddc':cmd+=['mcp','stdio']
   if n=='dexdec':cmd+=['--allow-root',str(Path(c['apk']).parent)]
   self.p=self.launch(cmd);self.p.init()
   if n=='dexdec':self.pid=self.p.call('open_project',{'path':c['apk']},240)['projectId']
   if n=='droidsaw':self.p.call('load',{'path':c['apk']},240)
  self.ready=self.memory.sample();return (time.perf_counter()-t)*1000
 def cli(self,command):
  class Holder:pass
  holder=Holder()
  holder.p=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',env=dict(os.environ,RAYON_NUM_THREADS='8'),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));self.ps.append(holder)
  try:
   stdout,stderr=holder.p.communicate(timeout=max(.001,self.deadline-time.perf_counter()))
   if holder.p.returncode:raise RuntimeError(stderr[:1000] or stdout[:1000])
   return stdout
  except subprocess.TimeoutExpired:holder.p.kill();holder.p.communicate();raise queue.Empty()
  finally:self.ps.remove(holder)
 def droid(self,command,pattern):
  args=[self.c['droidsaw_cli'],'--no-auto-splits']+command+[self.c['apk'],'--search',pattern]
  if command==['dex','methods']:args+=['--implementations']
  if command==['xrefs']:args+=['--limit','10000']
  data=json.loads(self.cli(args))
  if data.get('_meta',{}).get('truncated'):raise RuntimeError('truncated')
  return data
 def call(self,name,args):
  remaining=self.deadline-time.perf_counter()
  if remaining<=0:raise queue.Empty()
  return self.p.call(name,args,remaining)
 def asc(self,kind,value):
  self.p.send({'kind':kind,'value':sorted(value) if isinstance(value,set) else value});d=self.p.q.get(timeout=max(.001,self.deadline-time.perf_counter()))
  if 'rows' not in d:raise RuntimeError(d)
  return set(d['rows'])
 def refs(self,kind,value):
  n=self.name
  if n=='asc':return self.asc(kind,value)
  if n=='droidsaw-cli':
   values={value} if kind=='string' else value
   data=self.droid(['xrefs'],'^(?:'+'|'.join(re.escape(x) for x in values)+')$')
   return {m for x in data['xrefs'] if x['kind']==kind and x['string'] in values for m in x['functions']}
  if n=='dexdec':
   rows=set()
   for target in sorted(value):
    cl,rest=target.split('->');name,proto=rest.split('(',1)
    d=self.call('find_references',{'projectId':self.pid,'kind':'method','class':cl,'name':name,'descriptor':'('+proto})
    rows.update(x['classDescriptor']+'->'+x['method']+x['descriptor'] for x in d['locations'])
   return rows
  if n=='ddc':
   rows=set()
   if kind=='string':pairs=[(None,value)]
   else:pairs=sorted({(x.split('->')[0],x.split('->')[1].split('(')[0]) for x in value})
   for cl,name in pairs:
    args={'input':self.c['apk'],'kind':kind,'query':name}
    if cl:args['class']=cl[1:-1].replace('/','.')
    d=self.call('ddc.findrefs',args)
    if isinstance(d,dict) and 'result' in d:d=d['result']
    for x in d:
     if any((r==value or r.strip('"')==value) if kind=='string' else r in value for r in x['refs']):rows.add(owner(x['class'])+'->'+x['method'])
   return rows
  raise Unsupported('No equivalent reference query in this adapter')
 def query(self,kind):
  t=time.perf_counter();self.deadline=t+self.c.get('timeout',60);n=self.name
  if n=='dexsql':
   d=self.call('query',{'dataset_id':self.did,'sql':[SQL[kind]],'limit':1000,'timing':True})['statements'][0]
   if d['truncated'] or d['next_offset'] is not None:raise RuntimeError('truncated results')
   rows={r[0]['value'] for r in d['rows']}
  elif n=='garlic':
   if kind not in GARLIC_QUERIES:raise Unsupported(GARLIC_UNSUPPORTED[kind])
   rows=self.garlic.query(kind,self.deadline)
  elif n=='jadx-core':
   self.p.send({'kind':kind,'needle':{'class':CLASS,'method':'matchPayload','string':ANCHOR}.get(kind,'')});d=self.p.q.get(timeout=self.c.get('timeout',60))
   if 'rows' not in d:raise RuntimeError(d)
   rows=set(d['rows'])
  elif n=='jadx-mcp':
   if kind=='class':
    d=self.call('search_classes_by_keyword',{'search_term':'SplashActivity','search_in':'class','count':1000});rows={x for x in d.get('items',[]) if normalize(x)==CLASS}
   elif kind=='method':
    d=self.call('search_method_by_name',{'method_name':'matchPayload'})
    if isinstance(d,dict):d=d.get('result',d.get('results',d))
    if isinstance(d,str):rows=set(d.strip().splitlines())
    elif isinstance(d,list):rows=set(d)
    else:raise RuntimeError(d)
   elif kind=='string':
    d=self.call('search_classes_by_keyword',{'search_term':ANCHOR,'search_in':'code','count':1000});raise Unsupported('Source-text search completed but is not an equivalent const-string reference query')
   elif kind=='callers':
    d=self.call('get_xrefs_to_method',{'class_name':'iu3.a','method_name':'a','count':1000})
    if isinstance(d,dict) and 'error' in d:raise RuntimeError(d)
    observed_ms=(time.perf_counter()-t)*1000
    (self.out/(self.label+'-caller-response.json')).write_text(json.dumps(d,indent=2),encoding='utf-8')
    error=Unsupported('Xref tool omits caller prototypes and target overload selection; response received')
    error.observation={'wall_ms':observed_ms,'response_sha256':rows_digest([json.dumps(d,sort_keys=True)])}
    raise error
   else:raise Unsupported('No equivalent query through the tested MCP tool surface')
  elif kind=='class':
   if n=='asc':rows=self.asc('class',owner(CLASS))
   elif n=='ddc':rows={owner(x) for x in self.call('ddc.listclasses',{'input':self.c['apk'],'pattern':'SplashActivity'}) if normalize(owner(x))==CLASS}
   elif n=='dexdec':
    d=self.call('search_symbols',{'projectId':self.pid,'query':CLASS,'limit':500})
    if len(d['results'])>=500:raise RuntimeError('possibly truncated')
    rows={x['classDescriptor'] for x in d['results'] if x['kind']=='class' and normalize(x['classDescriptor'])==CLASS}
   elif n=='droidsaw-cli':rows={x['name'] for x in self.droid(['dex','classes'],'^'+re.escape(owner(CLASS))+'$')['classes']}
  elif kind=='method':
   if n=='dexdec':
    d=self.call('search_symbols',{'projectId':self.pid,'query':'matchPayload','limit':500})
    if len(d['results'])>=500:raise RuntimeError('possibly truncated')
    rows={x['classDescriptor'] for x in d['results'] if x['kind']=='method' and 'matchpayload' in x['name'].lower()}
   elif n=='ddc':
    lines=self.cli([self.c['ddc'],'members',self.c['apk'],'matchPayload','--method']).splitlines()
    rows={owner(line.split()[2]) for line in lines if len(line.split())>=4 and line.split()[1]=='method'}
   elif n=='droidsaw-cli':rows={x['class'] for x in self.droid(['dex','methods'],'matchPayload')['methods'] if 'matchpayload' in x['name'].lower()}
   else:raise Unsupported('No global method-declaration search command in the tested ASC interface')
  elif kind=='string':
   if n=='dexdec':raise Unsupported('find_references supports class/field/method, not const-string')
   rows={x.split('->')[0] for x in self.refs('string',ANCHOR)}
  elif kind=='callers':rows=self.refs('method',{TARGET})
  elif kind=='twohop':rows=self.refs('method',self.refs('method',{TARGET}))
  elif kind=='string_call':
   if n=='dexdec':raise Unsupported('No const-string reference tool')
   rows=self.refs('string',GIF)&self.refs('method',{BITMAP})
  else:raise Unsupported('No equivalent numeric/field/count predicate query implemented for this exposed interface')
  if kind in ['class','method','string']:rows={normalize(x) for x in rows}
  rows=sorted(rows);return {'wall_ms':(time.perf_counter()-t)*1000,'count':len(rows),'answer_sha256':rows_digest(rows),'rows':rows}
 def close(self):
  mem=self.memory.close()
  for p in reversed(self.ps):
   try:
    root=psutil.Process(p.p.pid)
    for child in root.children(recursive=True):
     try:child.kill()
     except psutil.Error:pass
   except psutil.Error:pass
   p.close()
  return mem

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--config',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--backends',default='dexsql,jadx-core,dexdec,ddc,asc,droidsaw');ap.add_argument('--cases',default=','.join(CASES));ap.add_argument('--trials',type=int,default=3);ap.add_argument('--warm',type=int,default=3)
 a=ap.parse_args()
 if min(a.trials,a.warm)<1:ap.error('trial and repeat counts must be positive')
 if set(a.cases.split(','))-set(CASES):ap.error('unknown case')
 if set(a.backends.split(','))-{'dexsql','jadx-core','jadx-mcp','dexdec','ddc','asc','garlic','droidsaw','droidsaw-cli'}:ap.error('unknown backend')
 c=json.loads(a.config.read_text(encoding='utf-8'));a.out.mkdir(parents=True,exist_ok=False);records=[];names=a.backends.split(',')
 for trial in range(a.trials):
  for name in names[trial%len(names):]+names[:trial%len(names)]:
   label=f'{trial+1}-{name}';b=Backend(name,c,a.out,label);r={'backend':name,'trial':trial+1,'cases':{}};records.append(r)
   try:
    r['prepare_ms']=b.start();r['ready_memory']=b.ready
    if name=='garlic':r['preparation_steps']=b.garlic.steps
    print(label,'ready',round(r['prepare_ms'],2),flush=True)
    for kind in a.cases.split(','):
     try:
      first=b.query(kind);r.setdefault('after_first_query_memory',b.memory.sample());samples=[b.query(kind) for _ in range(a.warm)]
      r['cases'][kind]={'status':'ok','first':first,'samples':samples}
      if kind=='class':r['class_workflow_memory']=b.memory.summary()
      print(label,kind,'ok',first['count'],round(statistics.median(x['wall_ms'] for x in samples),3),flush=True)
     except Unsupported as e:r['cases'][kind]={'status':'unsupported','reason':str(e),**({'non_equivalent_probe':e.observation} if hasattr(e,'observation') else {})};print(label,kind,'unsupported',flush=True)
     except queue.Empty:
      r['cases'][kind]={'status':'timeout','deadline_seconds':c.get('timeout',60)};print(label,kind,'TIMEOUT',flush=True);break
     except Exception as e:r['cases'][kind]={'status':'error','reason':str(e)};print(label,kind,'ERROR',str(e)[:200],flush=True);break
   except Exception as e:r['setup_error']=str(e);print(label,'SETUP ERROR',str(e)[:250],flush=True)
   finally:r['memory']=b.close();(a.out/'results.json').write_text(json.dumps({'config':c,'trials':a.trials,'warm':a.warm,'records':records},indent=2),encoding='utf-8')
if __name__=='__main__':main()
