"""Process-isolated CAD conversion: an OCC crash cannot kill the editor/batch."""
import json
from pathlib import Path
import subprocess
import sys
import time
from .diagnostics import describe_result

class ConversionError(ValueError):
    def __init__(self,row):
        super().__init__(row.get('error','CAD analysis failed.'))
        self.technical_detail=row.get('technical_detail','')
        self.result=row


def isolated_convert(path,out,material=None,quantity=None,length_axis='auto',force=False,project=False,timeout=120,cancel_event=None):
    data=dict(path=str(path),out=str(out),material=material,quantity=quantity,length_axis=length_axis,force=force,project=project)
    worker=Path(__file__).resolve().parents[1]/'scripts'/'convert_worker.py'
    row={'source':str(path),'output':str(out),'status':'error'}
    if cancel_event is not None and cancel_event.is_set():
        row.update(status='cancelled',error='Conversion cancelled.');return describe_result(row)
    if getattr(sys,'frozen',False):
        executable=Path(sys.executable).with_name('STEP2NC1-cli'+Path(sys.executable).suffix)
        if not executable.is_file():
            row['error']='Packaged CAD worker is missing. Extract the complete application folder again.'
            return describe_result(row)
        command=[str(executable),'--internal-worker']
    else:command=[sys.executable,'-X','faulthandler',str(worker)]
    with subprocess.Popen(command,text=True,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.PIPE,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as process:
        deadline=time.monotonic()+timeout;payload=json.dumps(data)
        while True:
            try:
                stdout,stderr=process.communicate(input=payload,timeout=.2)
                break
            except subprocess.TimeoutExpired:
                payload=None
                cancelled=cancel_event is not None and cancel_event.is_set()
                if cancelled or time.monotonic()>=deadline:
                    process.kill();stdout,stderr=process.communicate()
                    row.update(status='cancelled' if cancelled else 'error',
                               error='Conversion cancelled.' if cancelled else f'CAD conversion exceeded {timeout} seconds; this file was stopped.')
                    return describe_result(row)
        if process.returncode==0:
            for line in reversed(stdout.splitlines()):
                if line.startswith('STEP2NC1_RESULT='):
                    try:return describe_result(json.loads(line.split('=',1)[1]))
                    except (ValueError,TypeError):break
        row['error']=f'CAD process exited unexpectedly (code {process.returncode}). No output is trusted.'
        row['technical_detail']=stderr[-12000:]
        return describe_result(row)
