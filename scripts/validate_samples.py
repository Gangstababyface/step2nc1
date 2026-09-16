"""Reproducible STEP corpus audit; writes NC1, draft projects and a JSON report."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.conversion import isolated_convert
from core.dstv_writer import atomic_write


def run(task):
    source,output,timeout=task
    try:row=isolated_convert(source,output,force=True,project=True,timeout=timeout)
    except Exception as exc:row={'source':str(source),'output':str(output),'status':'error','error':str(exc)}
    row['source_sha256']=hashlib.sha256(Path(source).read_bytes()).hexdigest()
    return row


def main():
    p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('output');p.add_argument('--workers',type=int,default=2);p.add_argument('--timeout',type=int,default=120);args=p.parse_args()
    if args.workers<1 or args.timeout<1:p.error('Workers and timeout must be positive.')
    root=Path(args.input);out=Path(args.output);tasks=[]
    for source in sorted(root.rglob('*')):
        if source.suffix.lower() in ('.step','.stp') and source.is_file():tasks.append((source,out/source.relative_to(root).with_suffix('.nc1'),args.timeout))
    names=[str(t[1]).casefold() for t in tasks]
    if len(names)!=len(set(names)):p.error('Two STEP files would produce the same output name. Separate or rename them first.')
    rows=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(run,t) for t in tasks]
        for f in as_completed(futures):
            row=f.result();rows.append(row)
            atomic_write(out/'checkpoint.json',json.dumps(rows,indent=2)+'\n','utf-8')
            print(len(rows),len(tasks),Path(row['source']).name,row['status'],flush=True)
    from core.version import VERSION
    report={'version':VERSION,'timeout_seconds':args.timeout,'total':len(rows),'converted':sum(r['status']=='ok' for r in rows),'results':sorted(rows,key=lambda r:r['source'])}
    atomic_write(out/'report.json',json.dumps(report,indent=2,ensure_ascii=False)+'\n','utf-8')
    print('Completed',report['converted'],'of',report['total'])

if __name__=='__main__':main()
