"""Desktop app and batch conversion/inspection CLI."""
import argparse
import glob
import json
from pathlib import Path
import sys
from core.dstv_writer import default_header_from_filename,write_nc1,atomic_write
from core.validation import validate_features

from core.version import VERSION


def expand_inputs(inputs,recursive=False):
    result=[];seen=set()
    for pattern in inputs:
        matches=glob.glob(pattern,recursive=recursive) or [pattern]
        for value in matches:
            path=Path(value)
            if path.is_dir():
                paths=sorted(path.rglob('*') if recursive else path.iterdir())
                paths=[p for p in paths if p.suffix.lower() in ('.step','.stp') and p.is_file()]
            else:paths=[path]
            for p in paths:
                key=str(p.resolve())
                if key not in seen:seen.add(key);result.append(p)
    return result


def convert_one(path,out,material=None,quantity=None,length_axis='auto',force=False,project=False):
    from core.step_reader import load_step
    from core.section_detector import detect_section
    from core.feature_extractor import extract_features
    from core.project import save_project
    row={'source':str(path),'output':str(out),'status':'error'}
    if Path(path).resolve()==Path(out).resolve():raise ValueError('Output cannot replace a source file.')
    if Path(out).exists() and not force:raise FileExistsError(f'{out} exists; use --force to replace it.')
    model,_=load_step(path,length_axis);sec=detect_section(model);fs=extract_features(model,sec)
    h=default_header_from_filename(path)
    if material is not None:h.steel_quality=material
    if quantity is not None:h.quantity=quantity
    row.update(profile=sec.profile.name,family=sec.family,length_mm=sec.length_in*25.4,
               depth_mm=sec.profile.d_mm,width_mm=sec.profile.bf_mm,holes=len(fs.holes),
               outer_contours=len(fs.all_outer_contours()),inner_contours=len(fs.inner_contours),
               warnings=fs.warnings,errors=fs.errors,frame=sec.frame,quantity=h.quantity)
    try:
        validate_features(fs,h)
        write_nc1(fs,out,h,str(path),overwrite=force);row['status']='ok'
    except ValueError as exc:row['error']=str(exc)
    if project:
        project_path=Path(out).with_suffix('.step2nc.json')
        if project_path.exists() and not force:row.setdefault('warnings',[]).append('Existing project file retained.')
        else:save_project(project_path,fs,h,str(Path(path).resolve()))
    return row


def cli_convert(paths,output=None,recursive=False,material=None,quantity=None,length_axis='auto',force=False,project=False,report=None,cancel_event=None):
    files=expand_inputs(paths,recursive);rows=[];used=set()
    for path in files:
        if cancel_event is not None and cancel_event.is_set():break
        if output:
            # Preserve hierarchy for directory inputs; individual files retain their stem.
            rel=Path(path.name)
            for root in paths:
                if Path(root).is_dir():
                    try:rel=path.relative_to(Path(root));break
                    except ValueError:pass
            out=Path(output)/rel.with_suffix('.nc1')
        else:out=path.with_suffix('.nc1')
        try:
            target=str(out.resolve()).casefold()
            if target in used:raise ValueError('Duplicate output name; use separate output folders.')
            used.add(target)
            from core.conversion import isolated_convert
            row=isolated_convert(path,out,material,quantity,length_axis,force,project,cancel_event=cancel_event)
        except Exception as exc:row={'source':str(path),'output':str(out),'status':'error','error':str(exc)}
        rows.append(row)
        print(f"{row['status'].upper()}: {path.name}: "+(str(out) if row['status']=='ok' else row.get('error','')),flush=True)
    if not files:
        print('No STEP files found.',file=sys.stderr)
    result={'version':VERSION,'requested':len(files),'total':len(rows),'converted':sum(r['status']=='ok' for r in rows),
            'cancelled':bool(cancel_event is not None and cancel_event.is_set()),'results':rows}
    if report:atomic_write(report,json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n','utf-8')
    print(f"Converted {result['converted']}/{result['requested']} requested files; {result['total']} processed.")
    return 0 if files and len(rows)==len(files) and result['converted']==result['total'] else 1


def main(argv=None):
    args=sys.argv[1:] if argv is None else argv
    if args==['--internal-worker']:
        from scripts.convert_worker import run
        return run()
    if args and args[0]=='doctor':
        from scripts.verify_installation import run
        return run(args[1:])
    if not args:
        from gui.app import main as gui_main
        gui_main();return 0
    if args[0]=='inspect':
        from core.dstv_reader import read_nc1
        p=argparse.ArgumentParser(description='Inspect existing NC1 files without changing them.')
        p.add_argument('files',nargs='+');p.add_argument('--report')
        opt=p.parse_args(args[1:]);rows=[]
        for pattern in opt.files:
            for path in glob.glob(pattern) or [pattern]:
                try:
                    doc=read_nc1(path);f=doc.features;issues=[]
                    try:validate_features(f,doc.header)
                    except ValueError as exc:issues.append(str(exc))
                    rows.append({'file':path,'profile':f.section.profile.name,'length_mm':f.section.length_in*25.4,'holes':len(f.holes),'contours':len(f.all_outer_contours()),'issues':issues})
                except Exception as exc:rows.append({'file':path,'error':str(exc)})
        text=json.dumps(rows,indent=2)
        if opt.report:atomic_write(opt.report,text+'\n','utf-8')
        else:print(text)
        return int(any(r.get('error') or r.get('issues') for r in rows))
    if args[0]=='nest':
        from core.dstv_plus import Nest,write_ba
        p=argparse.ArgumentParser(description='Write a DSTV+ BA manifest from an ordered JSON nest.')
        p.add_argument('manifest');p.add_argument('-o','--output',required=True);p.add_argument('--force',action='store_true')
        opt=p.parse_args(args[1:])
        try:
            if Path(opt.output).exists() and not opt.force:raise ValueError('Output exists; use --force to replace.')
            data=json.loads(Path(opt.manifest).read_text('utf-8'))
            print(json.dumps(write_ba(Nest(**data),opt.output,Path(opt.manifest).parent),indent=2));return 0
        except Exception as exc:print(str(exc),file=sys.stderr);return 1
    p=argparse.ArgumentParser(description='Convert individual STEP structural parts to DSTV NC1. No arguments opens the desktop app.')
    p.add_argument('files',nargs='+');p.add_argument('-o','--output',help='Output directory; directory input hierarchy is retained.')
    p.add_argument('-r','--recursive',action='store_true');p.add_argument('--material',help='Material grade; never inferred from geometry.')
    p.add_argument('--quantity',type=int,help='Override quantity (default: X<number> filename suffix, otherwise 1).')
    p.add_argument('--length-axis',choices=('auto','x','y','z'),default='auto')
    p.add_argument('--force',action='store_true');p.add_argument('--project',action='store_true',help='Save editable project sidecars, including failed drafts.')
    p.add_argument('--report',help='Write a JSON batch report.');p.add_argument('--version',action='version',version=VERSION)
    opt=p.parse_args(args)
    return cli_convert(opt.files,opt.output,opt.recursive,opt.material,opt.quantity,opt.length_axis,opt.force,opt.project,opt.report)

if __name__=='__main__':raise SystemExit(main())
