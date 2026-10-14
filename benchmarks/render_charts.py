"""Render measured query and process-tree memory charts from the expanded JSON."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT=Path(__file__).resolve().parent
ORDER=['dexsql','dexdec','ddc','asc','garlic','jadx-core','jadx-mcp','droidsaw-cli']
LABELS={'dexsql':'DexSQL MCP','dexdec':'DexDec MCP','ddc':'ddc MCP / CLI','asc':'ASC API','garlic':'garlic MCP','jadx-core':'JADX API','jadx-mcp':'JADX-MCP','droidsaw-cli':'droidsaw CLI'}
COLORS={'dexsql':'#16734a','dexdec':'#6477a2','ddc':'#c78832','asc':'#a45e70','garlic':'#b56c46','jadx-core':'#668a95','jadx-mcp':'#8a799b','droidsaw-cli':'#6b7769'}
TITLES={'class':'Exact class lookup','method':'Method-name search','string':'Exact string reference','callers':'Direct callers','twohop':'Two-hop callers','string_call':'String + method call','four_fact':'String + call + field + number','complex':'Signature + 4 strings + field + call count'}
AXIS_LIMITS={'class':500,'method':600,'string':400,'callers':800,'twohop':1600,'string_call':1600,'four_fact':240,'complex':120}

def style():
 plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'svg.fonttype':'path','svg.hashsalt':'dexsql-expanded-20261014','figure.facecolor':'white','axes.facecolor':'white','text.color':'#202830','axes.labelcolor':'#58636e','xtick.color':'#58636e','ytick.color':'#202830'})

def save(fig,name,args):
 (ROOT/'charts').mkdir(exist_ok=True)
 svg=ROOT/'charts'/(name+'.svg')
 fig.savefig(svg,metadata={'Date':None,'Title':name},facecolor='white')
 svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
 if args.preview_dir:
  args.preview_dir.mkdir(parents=True,exist_ok=True);fig.savefig(args.preview_dir/(name+'.png'),dpi=130)
 plt.close(fig)

def decorate(ax):
 for s in ['left','right','top']:ax.spines[s].set_visible(False)
 ax.spines['bottom'].set_color('#bac2ca');ax.set_axisbelow(True);ax.grid(axis='x',color='#e5e9ed',linewidth=.7);ax.tick_params(axis='y',length=0,pad=10)

def timing(data,kinds,name,args):
 style();height=2.25+len(kinds)*(3.35+.35*(len(ORDER)-7))
 fig,axes=plt.subplots(len(kinds),1,figsize=(11,height),squeeze=False)
 fig.subplots_adjust(left=.21,right=.95,top=1-1.35/height,bottom=1.7/height,hspace=.5)
 fig.text(.045,1-.28/height,'QQ 9.3.55 · query latency',fontsize=20,weight='bold',va='top')
 fig.text(.045,1-.78/height,'Linear scales from zero · clipped bars labeled with actual times · lower is better',fontsize=11,color='#58636e')
 for ax,kind in zip(axes[:,0],kinds):
  limit=AXIS_LIMITS[kind]
  decorate(ax);ax.set_ylim(len(ORDER)-.4,-.6);ax.tick_params(axis='x',labelsize=9)
  ax.set_xlim(0,limit);ax.set_yticks(range(len(ORDER)),[LABELS[x] for x in ORDER],fontsize=10)
  ax.set_xticks([limit*i/4 for i in range(5)],[f'{limit*i/4:,.0f}' for i in range(5)])
  ax.set_xlabel('Milliseconds',fontsize=10,labelpad=5)
  ax.set_title(TITLES[kind],loc='left',fontsize=13,weight='bold',pad=10)
  for y,backend in enumerate(ORDER):
   entry=data['summary'].get(backend,{}).get('cases',{}).get(kind,{'status':'not_run'})
   status=entry['status']
   if status=='ok':
    value=entry['median_ms'];color=COLORS[backend]
    if value>limit:
     ax.barh(y,limit,height=.53,color=color,alpha=.22,zorder=3)
     ax.plot(limit,y,marker='>',markersize=6,color=color,clip_on=False,zorder=4)
     ax.annotate(f'{value:,.2f} ms · clipped',(limit,y),xytext=(-8,0),textcoords='offset points',ha='right',va='center',fontsize=10,color='#47515a')
    else:
     ax.barh(y,value,height=.53,color=color,zorder=3)
     inside=value>.75*limit
     ax.annotate(f'{value:,.2f} ms',(value,y),xytext=(-5 if inside else 5,0),textcoords='offset points',ha='right' if inside else 'left',va='center',fontsize=10,color='white' if inside else '#202830',weight='bold' if backend=='dexsql' else 'normal')
   elif status=='timeout':
    ax.barh(y,limit,height=.53,facecolor='#f1f2f4',edgecolor='#9a849f',hatch='////',linewidth=.6,zorder=3)
    ax.plot(limit,y,marker='>',markersize=6,color='#9a849f',clip_on=False,zorder=4)
    ax.annotate('≥60,000 ms · timeout',(limit,y),xytext=(-8,0),textcoords='offset points',ha='right',va='center',fontsize=10,bbox={'facecolor':'white','edgecolor':'none','alpha':.93,'pad':1.5})
   elif status=='name_only_result':
    label=f"{entry['probe_ms']:,.2f} ms · single probe, owner/name only"
    ax.text(.015,y,label,transform=ax.get_yaxis_transform(),va='center',fontsize=9.6,color='#727d87')
   else:
    label=entry.get('chart_note') or '; '.join(entry.get('reasons',[]))
    if not label:raise ValueError(f'Missing chart reason for {backend}/{kind}: {status}')
    ax.text(.015,y,label,transform=ax.get_yaxis_transform(),va='center',fontsize=9.6,color='#727d87')
 notes=['Linear scales from zero. Arrows mark clipped bars; their labels show the actual elapsed time.',
        'Hatching marks the 60 s timeout, not a completed query. Gray entries explain missing comparisons.',
        '9 repeats after preparation (garlic: fresh MCP per call). droidsaw: 3 fresh CLI invocations, including loading.',
        'JADX-MCP source search differs from exact DEX references. Completed, plotted result sets are checked.']
 for i,line in enumerate(notes):fig.text(.045,(1.08-i*.22)/height,line,fontsize=9,color='#58636e')
 save(fig,name,args)

def memory(data,args,metric='rss'):
 style();fig,ax=plt.subplots(figsize=(11,6.8+.45*(len(ORDER)-7)));fig.subplots_adjust(left=.21,right=.93,top=.77,bottom=.22)
 title='process-tree memory'+(' · Private Bytes' if metric=='private' else ' · RSS')
 fig.text(.045,.94,'QQ 9.3.55 · '+title,fontsize=20,weight='bold')
 subtitle='50 ms polling wait · GiB · median of per-run peaks'
 fig.text(.045,.888,subtitle,fontsize=11,color='#58636e');decorate(ax)
 ax.set_yticks(range(len(ORDER)),[LABELS[x] for x in ORDER]);ax.set_ylim(len(ORDER)-.4,-.6)
 maxvalue=0
 for y,backend in enumerate(ORDER):
  mem=data['summary'].get(backend,{}).get('memory',{})
  for j,field in enumerate(['class_workflow_peak_'+metric+'_bytes','suite_peak_'+metric+'_bytes']):
   value=mem.get(field)
   if value is None:continue
   value/=2**30;maxvalue=max(maxvalue,value);yy=y+(-.17 if j==0 else .17)
   ax.barh(yy,value,height=.28,color=COLORS[backend],alpha=.43 if j==0 else 1)
   ax.annotate(f'{value:.2f}',(value,yy),xytext=(5,0),textcoords='offset points',va='center',fontsize=10)
 ax.set_xlim(0,maxvalue*1.16);ax.set_xlabel('GiB',labelpad=6)
 labels=['Load + class lookup peak','Peak over all executed cases']
 fig.legend(handles=[Patch(facecolor='#485866',alpha=.43,label=labels[0]),Patch(facecolor='#485866',label=labels[1])],loc='upper left',bbox_to_anchor=(.20,.851),ncol=2,frameon=False,fontsize=10)
 notes=['RSS sums working sets across the process tree; shared pages can be counted more than once.',
         'Executed cases differ. Light bars use the common class-lookup workflow. droidsaw has one CLI round.',
         'Sampled peaks are not memory limits. JVM heap cap: 24 GiB. Private Bytes are also recorded.']
 if metric=='private':notes[0]='Private Bytes are committed private memory, including nonresident pages; they are not RSS.'
 for i,line in enumerate(notes):fig.text(.045,.109-i*.028,line,fontsize=9.1,color='#58636e')
 save(fig,'memory' if metric=='rss' else 'private-memory',args)

def startup(data,args):
 style();fig,ax=plt.subplots(figsize=(11,4.8+.35*(len(ORDER)-7)));fig.subplots_adjust(left=.21,right=.93,top=.76,bottom=.23)
 fig.text(.045,.92,'QQ 9.3.55 · start to first class result',fontsize=20,weight='bold')
 fig.text(.045,.85,'Process startup + preparation + first SplashActivity lookup · median of 3 runs',fontsize=11,color='#58636e')
 decorate(ax);ax.set_yticks(range(len(ORDER)),[LABELS[x] for x in ORDER]);ax.set_ylim(len(ORDER)-.4,-.6)
 values=[data['summary'][b]['first_class_total_median_ms']/1000 for b in ORDER]
 for y,(backend,value) in enumerate(zip(ORDER,values)):
  ax.barh(y,value,height=.53,color=COLORS[backend]);ax.annotate(f'{value:.2f} s',(value,y),xytext=(5,0),textcoords='offset points',va='center',fontsize=10)
 ax.set_xlim(0,max(values)*1.17);ax.set_xlabel('Seconds · linear scale from zero')
 fig.text(.045,.10,'This is readiness for one class lookup, not completed decompilation or a full application index.',fontsize=9.3,color='#58636e')
 fig.text(.045,.06,'droidsaw uses 3 fresh CLI invocations. The OS file cache was not flushed.',fontsize=9.3,color='#58636e')
 save(fig,'startup',args)

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--preview-dir',type=Path);args=ap.parse_args()
 data=json.loads((ROOT/'qq-9.3.55-expanded.json').read_text(encoding='utf-8'))
 timing(data,['class','method','string'],'warm',args)
 timing(data,['callers','twohop'],'calls',args)
 timing(data,['string_call','four_fact','complex'],'compound',args)
 memory(data,args)
 memory(data,args,'private')
 startup(data,args)
if __name__=='__main__':main()
