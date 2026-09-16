"""Per-session atomic draft recovery with OS locks, including multiple windows."""
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
import json
import os
import uuid
from .dstv_writer import atomic_write
from .project import project_data


def user_data_dir():
    if os.name=='nt':return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'STEP2NC1'
    return Path(os.environ.get('XDG_STATE_HOME',Path.home()/'.local/state'))/'step2nc1'


def lock(handle):
    handle.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)


def unlock(handle):
    handle.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


@contextmanager
def claim(path):
    handle=Path(path).open('a+b')
    if handle.tell()==0:handle.write(b'0');handle.flush()
    try:
        lock(handle)
    except OSError:
        handle.close();yield None;return
    try:yield handle
    finally:unlock(handle);handle.close()


class RecoveryStore:
    def __init__(self,directory=None):
        self.directory=Path(directory) if directory else user_data_dir()/'recovery'
        self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/(datetime.now().strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex+'.step2nc.json')
        self.lock_path=self.path.with_suffix('.lock')
        self._claim=claim(self.lock_path);self._handle=self._claim.__enter__()
        if self._handle is None:raise OSError('Could not reserve a draft recovery file.')

    def save(self,features,header,source,form):
        data=project_data(features,header,source)
        data['recovery']={'saved_utc':datetime.now(timezone.utc).isoformat(),'form':dict(form)}
        atomic_write(self.path,json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2)+'\n','utf-8')

    def clear(self):self.path.unlink(missing_ok=True)

    def available(self):
        result=[]
        for path in self.directory.glob('*.step2nc.json'):
            if path==self.path:continue
            with claim(path.with_suffix('.lock')) as handle:
                if handle is None:continue
                try:
                    data=json.loads(path.read_text('utf-8'))
                    if data.get('schema')=='step2nc1-project':result.append((path,data))
                except (OSError,ValueError):continue
        return sorted(result,key=lambda item:item[1].get('recovery',{}).get('saved_utc',''),reverse=True)

    def discard_path(self,path):
        path=Path(path)
        if path.parent.resolve()!=self.directory.resolve():return
        with claim(path.with_suffix('.lock')) as handle:
            if handle is None:return
            path.unlink(missing_ok=True)
        path.with_suffix('.lock').unlink(missing_ok=True)

    def close(self,discard=False):
        if discard:self.clear()
        if self._handle is not None:
            self._claim.__exit__(None,None,None);self._handle=None
        if discard:self.lock_path.unlink(missing_ok=True)
