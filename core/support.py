"""Local support bundle. Source CAD files are never copied automatically."""
from datetime import datetime,timezone
from importlib.metadata import version,PackageNotFoundError
from pathlib import Path
import json
import platform
import sys
import os
import tempfile
import zipfile
from .version import VERSION


def runtime_info():
    dependencies={}
    for name in ('cadquery','cadquery-ocp','numpy'):
        try:dependencies[name]=version(name)
        except PackageNotFoundError:dependencies[name]='not installed'
    return {'app_version':VERSION,'python':sys.version,'platform':platform.platform(),
            'architecture':platform.architecture()[0],'dependencies':dependencies,
            'created_utc':datetime.now(timezone.utc).isoformat()}


def write_support_bundle(path,diagnostics=None,log_path=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.support-',suffix='.zip',dir=path.parent);os.close(fd)
    try:
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('environment.json',json.dumps(runtime_info(),indent=2))
            archive.writestr('diagnostics.json',json.dumps(diagnostics or {},indent=2,ensure_ascii=False))
            archive.writestr('README.txt','Support information only. Source CAD and NC1 files are not included.\nReview diagnostics and logs before sharing; they may contain local file paths.\n')
            if log_path and Path(log_path).is_file():archive.write(log_path,'application.log')
        os.replace(tmp,path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True);raise
    return path
