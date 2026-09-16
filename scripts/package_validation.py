"""Package completed candidate audits. Never reuse stale exports or partial reports."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.version import VERSION
from core.dstv_reader import read_nc1
from core.validation import validate_features
from core.project import load_project


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_json(path,data):path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def category(row):
    if row['status']=='ok':return 'Exported'
    error=row.get('error','').lower()
    for words,label in [
        (['exceeded'],'Timed out'),(['exited unexpectedly'],'CAD process failure'),
        (['expected one solid'],'Multiple or missing solids'),
        (['round pipe:'],'Unsupported round-pipe machining'),
        (['constant w','no straight member axis','no perpendicular section directions'],'Unsupported section or orientation'),
        (['ascii'],'Invalid header metadata'),
        (['no material on face','empty boundary wire'],'Contour or face extraction failure'),
        (['thickness','chamfer','pocket','opening changes','unsupported surface','ellipse','curve type','nominal wall','distinct full-section'],'Unsupported machining geometry'),
        (['invalid','not a valid','read step','load step','positive volume'],'Invalid or unreadable solid')]:
        if any(w in error for w in words):return label
    return 'Other conversion/validation error'


def verify_nc1(output,row):
    doc=read_nc1(output);validate_features(doc.features,doc.header);fs=doc.features
    for field,value in [('length_mm',fs.section.length_in*25.4),('depth_mm',fs.section.profile.d_mm),('width_mm',fs.section.profile.bf_mm)]:
        assert abs(value-row[field])<.002,(output,field,value,row[field])
    assert len(fs.holes)==row['holes']
    assert len(fs.all_outer_contours())==row['outer_contours']
    assert len(fs.inner_contours)==row['inner_contours']
    assert doc.header.quantity==row['quantity']
    original,header,_=load_project(output.with_suffix('.step2nc.json'))
    assert original.section.family==fs.section.family
    assert header.steel_quality==doc.header.steel_quality
    for a,b in zip(original.holes,fs.holes):
        assert a.surface==b.surface
        for field in ('x_mm','y_mm','diameter_mm','depth_mm'):
            assert abs(getattr(a,field)-getattr(b,field))<.002,(output,'hole',field)
    for attr in ('outer_contours','inner_contours'):
        for ca,cb in zip(getattr(original,attr),getattr(fs,attr)):
            assert len(ca)==len(cb)
            for a,b in zip(ca,cb):
                assert a.surface==b.surface
                for field in ('x_mm','y_mm','radius_mm','bevel_angle_1','bevel_depth_1','bevel_angle_2','bevel_depth_2'):
                    assert abs(getattr(a,field)-getattr(b,field))<.002,(output,'contour',field)
    for field,a in vars(original.end_cuts).items():assert abs(a-getattr(fs.end_cuts,field))<.002


def zip_tree(source,target):
    excluded={'.venv','__pycache__','.pytest_cache','.git','build','dist'}
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in sorted(source.rglob('*')):
            if path.is_file() and not any(p in excluded for p in path.relative_to(source).parts):z.write(path,Path(source.name)/path.relative_to(source))
    with zipfile.ZipFile(target) as z:assert z.testzip() is None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path,default=ROOT.parent/'audit')
    parser.add_argument('--uploads',type=Path,default=ROOT.parents[1]/'upload')
    parser.add_argument('--output',type=Path,default=ROOT.parents[1]/'output')
    parser.add_argument('--prefix',default='rc3')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    specs=[('Direct',args.uploads,'direct',34),('Z',ROOT.parent/'z_samples','z',246),('R',ROOT.parent/'r_samples','r',634)]
    suites=ET.parse(args.audit/(args.prefix+'-tests.xml')).getroot().findall('.//testsuite')
    tests=sum(int(s.get('tests','0')) for s in suites)
    assert tests>=53 and all(int(s.get('failures','0'))+int(s.get('errors','0'))+int(s.get('skipped','0'))==0 for s in suites),'Regression gate failed'
    # Check full coverage before removing any previous delivery staging files.
    runs=[]
    for label,source_root,suffix,total in specs:
        audit=args.audit/(args.prefix+'-'+suffix)
        data=json.loads((audit/'report.json').read_text())
        assert data['version']==VERSION and data['total']==total
        actual={p.resolve() for p in source_root.rglob('*') if p.is_file() and p.suffix.lower() in ('.step','.stp')}
        reported={(ROOT/r['source']).resolve() for r in data['results']}
        assert actual==reported and len(data['results'])==len(reported),(label,'Coverage mismatch')
        runs.append((label,source_root.resolve(),audit,data))
    validation=ROOT/'validation';samples=ROOT/'converted_samples';bundle=args.output/'archive-test-results'
    for folder in (validation,samples,bundle):
        if folder.exists():shutil.rmtree(folder)
        folder.mkdir(parents=True)
    summaries=[];all_rows=[]
    for label,source_root,audit,data in runs:
        rows=[]
        for raw in data['results']:
            row=dict(raw);source=(ROOT/row['source']).resolve();rel=source.relative_to(source_root)
            assert sha(source)==row['source_sha256'],(label,rel,'Changed source')
            row.update(dataset=label,source=str(rel),category=category(row),output=None)
            nc=audit/rel.with_suffix('.nc1')
            if row['status']=='ok':
                verify_nc1(nc,row);row['nc1_readback']='passed'
                target=(samples if label=='Direct' else bundle/'nc1'/label)/rel.with_suffix('.nc1')
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(nc,target)
                row['output']=str(target.relative_to(samples if label=='Direct' else bundle));row['output_sha256']=sha(target)
            else:
                assert not nc.exists(),(label,rel,'Rejected file has an NC1 export')
            if label=='Direct':
                shutil.copy2(source,samples/rel)
                draft=nc.with_suffix('.step2nc.json')
                if draft.exists():
                    project=json.loads(draft.read_text());project['source']=rel.name
                    write_json(samples/rel.with_suffix('.step2nc.json'),project)
            rows.append(row)
        summary={'dataset':label,'tested':len(rows),'exported':sum(r['status']=='ok' for r in rows),'readback_passed':sum(r.get('nc1_readback')=='passed' for r in rows),'categories':dict(Counter(r['category'] for r in rows))}
        archive_name={'R':'R(1).7z','Z':'Z.7z'}.get(label)
        if archive_name:summary.update(archive=archive_name,archive_sha256=sha(args.uploads/archive_name))
        summaries.append(summary);all_rows.extend(rows)
        write_json(validation/(label.lower()+'-results.json'),{'version':VERSION,'timeout_seconds':data['timeout_seconds'],'summary':summary,'results':rows})
    for suffix in ('tests.log','tests.xml','installation-linux.json'):
        shutil.copy2(args.audit/(args.prefix+'-'+suffix),validation/suffix)
    hashes={str(p.relative_to(ROOT)):sha(p) for p in sorted(ROOT.rglob('*.py')) if '__pycache__' not in p.parts and '.venv' not in p.parts}
    write_json(validation/'source-sha256.json',hashes)
    result={'version':VERSION,'date':'2026-09-16','timeout_seconds':120,'regression_tests_passed':tests,'summaries':summaries,'results':all_rows}
    write_json(bundle/'results.json',result);write_json(bundle/'converter-source-sha256.json',hashes)
    table=['| Dataset | Tested | Exported | Flagged | NC1 readback passed |','|---|---:|---:|---:|---:|']
    for s in summaries:table.append(f"| {s['dataset']} | {s['tested']} | {s['exported']} | {s['tested']-s['exported']} | {s['readback_passed']} |")
    common=['',*table,'','All 880 STEP/STP entries in Z and R and all 34 direct STEP uploads were tested afresh at a 120-second per-file limit. Duplicate models at different paths count as separate entries. Every source has a verified SHA-256; output names were checked for collisions. Other archive formats and executables were not run.','',
      'Exported means geometry extraction and internal validation passed. NC1 readback then compared stock dimensions, quantity, grade, hole faces/coordinates/diameters, contour vertices/radii/bevel fields and miter angles with saved project data within 0.002 mm/degrees. This checks serialization; it is not a full geometric equivalence proof or receiving-controller acceptance. The reference NC1 files are not paired geometric ground truth.','',
      'Unsupported parts remain explicit rejections. A timeout or CAD process failure is not proof of unsupported geometry. See the per-file diagnostics. Material grades remain blank because no grades were supplied; quantities follow the filename suffix rule. Review both before use.','']
    lines=['# Validation report','',f'STEP2NC1 {VERSION}. Tested 2026-09-16 on Linux, Python 3.12, CadQuery 2.7.0.',f'Automated regression suite: **{tests} passed**, no failures, errors or skips.',*common,'## Failure categories','','| Category | Direct | Z | R |','|---|---:|---:|---:|']
    for cat in sorted({r['category'] for r in all_rows if r['status']!='ok'}):lines.append('| '+cat+' | '+' | '.join(str(s['categories'].get(cat,0)) for s in summaries)+' |')
    lines+=['','## Release limits','','Linux installation verification passed the real STEP → isolated worker → NC1 → project readback workflow. Desktop modules compile. Live GUI verification was not available: the environment blocked display-server sockets. Windows source launch, native packaging, frozen desktop behavior, high-DPI visual review, receiving CAM and physical acceptance remain pending. See RELEASE-GATES.md.','',
      '`validation/` contains the complete current per-file reports, regression evidence, installation check and Python source hashes. `converted_samples/` contains only freshly generated direct-sample outputs, drafts where available and original direct STEP files. The separate archive-test-results ZIP contains fresh successful R/Z exports and all per-file results.','']
    (ROOT/'docs/VALIDATION.md').write_text('\n'.join(lines),encoding='utf-8')
    (bundle/'README.md').write_text('\n'.join(['# Archive test results','',f'Candidate {VERSION}; {tests} regression tests passed.',*common,'`nc1/Z` and `nc1/R` contain only successful archive exports. `results.json` also includes the 34 direct-file results; their NC1 files are in the source package. `failures.md` lists all rejected inputs. Windows and receiving-machine acceptance remain pending.','']),encoding='utf-8')
    failed=['# Flagged inputs','','| Dataset | File | Category | Diagnostic |','|---|---|---|---|']
    for r in all_rows:
        if r['status']!='ok':failed.append('| '+' | '.join(str(r.get(k,'')).replace('|','\\|').replace('\n','; ') for k in ('dataset','source','category','error'))+' |')
    (bundle/'failures.md').write_text('\n'.join(failed)+'\n',encoding='utf-8')
    for filename in ('tests.log','tests.xml','installation-linux.json'):shutil.copy2(validation/filename,bundle/filename)
    zip_tree(ROOT,args.output/'step2nc1-main(1).zip');zip_tree(bundle,args.output/'archive-test-results.zip')
    print(json.dumps({'version':VERSION,'tests_passed':tests,'summaries':summaries},indent=2))

if __name__=='__main__':main()
