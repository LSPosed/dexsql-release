"""JSON-lines adapter over ASC's unmodified APK and findrefs APIs."""
import sys,json,re,mmap
from concurrent.futures import ProcessPoolExecutor
from droidasc.asc_client.apk_handler import ApkHandler
from droidasc.asc_client.apk.loader import _parse_cd_dex_entries
from droidasc.asc_client.apk.worker import _findrefs_worker

def refs(apk,kind,value,workers):
 if kind=='string': query={'string':re.escape(value)}
 else:
  targets=value; classes={x.split('->')[0] for x in targets}; names={x.split('->')[1].split('(')[0] for x in targets}
  query={'method':{'class':['(?:'+'|'.join(re.escape(x) for x in classes)+')',False], 'method':'(?:'+'|'.join(re.escape(x) for x in names)+')'}}
 with open(apk,'rb') as f:
  with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mm: entries=_parse_cd_dex_entries(mm)
 rows=set()
 with ProcessPoolExecutor(max_workers=workers) as pool:
  futures=[pool.submit(_findrefs_worker,apk,e,kind,query,False) for e in entries]
  for future in futures:
   for line in future.result()[1]:
    _,method,matched=line.split(' | ',2)
    target=matched.removeprefix('matched=(').rsplit(') | occurrence=',1)[0]
    if (target==value if kind=='string' else canonical(target) in targets): rows.add(canonical(method))
 return rows

def canonical(s):
 owner,rest=s.split('->',1)
 if not owner.startswith('L') or not owner.endswith(';'): owner='L'+owner.replace('.','/')+';'
 return owner+'->'+rest

def main():
 apk,workers=sys.argv[1],int(sys.argv[2]); handler=ApkHandler(apk,max_workers=workers)
 print(json.dumps({'ready':True}),flush=True)
 for line in sys.stdin:
  try:
   q=json.loads(line);kind=q['kind']
   if kind=='class': rows=[q['value']] if handler.get_class_dex(q['value']) else []
   else: rows=sorted(refs(apk,kind,q['value'],workers))
   print(json.dumps({'rows':rows}),flush=True)
  except Exception as e:print(json.dumps({'error':repr(e)}),flush=True)
if __name__=='__main__':main()
