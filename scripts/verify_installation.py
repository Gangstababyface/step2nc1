"""Run on the customer's Windows installation; save an actionable JSON report."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.support import runtime_info
from core.dstv_writer import atomic_write


def run(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui',action='store_true',help='Require the desktop workflow test; a real display is required.')
    parser.add_argument('--output',default='installation-check.json')
    args=parser.parse_args(argv);report={'environment':runtime_info(),'checks':[]}
    def check(name,func):
        try:detail=func();report['checks'].append({'name':name,'status':'passed','detail':detail or ''});return True
        except Exception as exc:
            report['checks'].append({'name':name,'status':'failed','detail':str(exc),'traceback':traceback.format_exc()});return False
    def architecture():
        if sys.maxsize<=2**32:raise RuntimeError('64-bit Python is required.')
        return '64-bit runtime'
    check('Runtime architecture',architecture)
    with tempfile.TemporaryDirectory(prefix='step2nc1-check-') as temp:
        directory=Path(temp);source=directory/'installation-test.step';out=directory/'installation-test.nc1'
        def conversion():
            import cadquery as cq
            from core.conversion import isolated_convert
            from core.dstv_reader import read_nc1
            from core.validation import validate_features
            from core.project import load_project
            shape=cq.Solid.makeBox(200,50,6).cut(cq.Solid.makeCylinder(5,10,(100,25,-2),(0,0,1)))
            shape.exportStep(str(source))
            result=isolated_convert(source,out,material='TEST',project=True)
            if result['status']!='ok':raise RuntimeError(result.get('error','Conversion failed.'))
            doc=read_nc1(out);validate_features(doc.features,doc.header)
            if len(doc.features.holes)!=1:raise RuntimeError('Expected one through-hole.')
            hole=doc.features.holes[0]
            if abs(hole.diameter_mm-10)>.001:raise RuntimeError('Hole diameter changed.')
            saved,header,_=load_project(out.with_suffix('.step2nc.json'))
            if len(saved.holes)!=1 or header.steel_quality!='TEST':raise RuntimeError('Saved project readback failed.')
            return 'STEP import, isolated worker, NC1 export/readback and saved project passed.'
        converted=check('End-to-end CAD conversion',conversion)
        def iges_conversion():
            from core.conversion import isolated_convert
            result=isolated_convert(source,directory/'installation-test.igs',output_format='iges')
            if result.get('status')!='ok':raise RuntimeError(result.get('error','IGES conversion failed.'))
            if result.get('readback')!='passed':raise RuntimeError('IGES readback did not pass.')
            if result.get('encoding')!='trimmed-surfaces':raise RuntimeError('Incorrect IGES encoding.')
            return 'STEP to trimmed-surface IGES worker, face checks and sewn solid count/volume readback passed.'
        check('IGES conversion',iges_conversion)
        def desktop():
            if not converted:raise RuntimeError('Resolve the CAD conversion failure first.')
            import tkinter as tk
            from unittest.mock import patch
            from gui.app import App
            from core.project import load_project
            from core.dstv_reader import read_nc1
            project=directory/'edited.step2nc.json';edited=directory/'edited.nc1'
            def fail_dialog(title,message,**kwargs):raise RuntimeError(title+': '+message)
            with patch.dict(os.environ,{'LOCALAPPDATA':str(directory/'state'),'XDG_STATE_HOME':str(directory/'state')}),patch('gui.app.messagebox.showerror',side_effect=fail_dialog),patch('gui.app.messagebox.showwarning',side_effect=fail_dialog):
                root=tk.Tk();app=None
                try:
                    app=App(root);callback_errors=[]
                    root.report_callback_exception=lambda kind,value,tb:callback_errors.append(str(value))
                    root.update()
                    app.loaded((*load_project(out.with_suffix('.step2nc.json')),None));root.update()
                    app.vars['quantity'].set('2')
                    with patch('gui.app.filedialog.asksaveasfilename',return_value=str(project)):
                        app.save()
                    if not project.exists() or load_project(project)[1].quantity!=2:raise RuntimeError('Desktop project save failed.')
                    with patch('gui.app.filedialog.asksaveasfilename',return_value=str(edited)):
                        app.export()
                    if not edited.exists() or read_nc1(edited).header.quantity!=2:raise RuntimeError('Desktop NC1 export failed.')
                    app.vars['quantity'].set('unfinished edit');app.autosave()
                    data=json.loads(app.recovery.path.read_text())
                    if data['recovery']['form']['quantity']!='unfinished edit':raise RuntimeError('Draft recovery did not retain field text.')
                    app.vars['quantity'].set('2')
                    app.run_job(lambda:app.cancel_event.wait(5),lambda result:None)
                    app.cancel_job();deadline=time.monotonic()+5
                    while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                    if app.busy:raise RuntimeError('Desktop cancellation did not finish.')
                    root.update()
                    iges_directory=directory/'gui-iges';iges_directory.mkdir()
                    reports=[]
                    with patch('gui.app.filedialog.askopenfilenames',return_value=(str(source),)),patch('gui.app.filedialog.askdirectory',return_value=str(iges_directory)),patch.object(app,'batch_results',side_effect=lambda path:reports.append(path)):
                        app.export_iges();deadline=time.monotonic()+30
                        while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                    if app.busy or not reports:raise RuntimeError('Desktop IGES action did not finish.')
                    result=json.loads(reports[0].read_text())
                    if result['converted']!=1 or not (iges_directory/'installation-test.igs').is_file():raise RuntimeError('Desktop IGES export failed.')
                    if callback_errors:raise RuntimeError('; '.join(callback_errors))
                    return 'Desktop opened, displayed the part, edited quantity, saved/reopened, exported, autosaved, cancelled a job and exported IGES through the desktop action.'
                finally:
                    if app:app.finish_close()
                    else:root.destroy()
        if args.gui:check('Desktop workflow',desktop)
        else:report['checks'].append({'name':'Desktop workflow','status':'not_run','detail':'Run with --gui on a machine with a display.'})
    report['status']='passed' if all(c['status']=='passed' for c in report['checks']) else 'incomplete' if not any(c['status']=='failed' for c in report['checks']) else 'failed'
    atomic_write(args.output,json.dumps(report,indent=2)+'\n','utf-8')
    print(json.dumps(report,indent=2))
    return int(report['status']=='failed')

if __name__=='__main__':raise SystemExit(run())
