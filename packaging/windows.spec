# Build only on Windows. Both launchers share one CAD runtime directory.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all,copy_metadata

root=Path(SPECPATH).parent
extra_data=[];extra_binaries=[];hidden=[]
for package in ('cadquery','OCP'):
    data,binaries,imports=collect_all(package)
    extra_data+=data;extra_binaries+=binaries;hidden+=imports
for distribution in ('cadquery','cadquery-ocp','numpy'):
    extra_data+=copy_metadata(distribution)
a=Analysis([str(root/'main.py')],pathex=[str(root)],
           binaries=extra_binaries,datas=[(str(root/'data'),'data')]+extra_data,
           hiddenimports=hidden+['scripts.convert_worker','scripts.verify_installation'],
           hookspath=[],runtime_hooks=[],excludes=[])
pyz=PYZ(a.pure)
gui=EXE(pyz,a.scripts,[],exclude_binaries=True,name='STEP2NC1',console=False,upx=False)
cli=EXE(pyz,a.scripts,[],exclude_binaries=True,name='STEP2NC1-cli',console=True,upx=False)
COLLECT(gui,cli,a.binaries,a.datas,name='STEP2NC1',strip=False,upx=False)
