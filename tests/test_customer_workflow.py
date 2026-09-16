import json
import subprocess
import threading
import time
from pathlib import Path
import pytest
from core import conversion
from core.recovery import RecoveryStore
from core.project import load_project
from core.dstv_writer import NC1Header
from core.support import write_support_bundle
from test_conversion import analyze,beam


def test_recovery_preserves_unapplied_text_and_excludes_live_sessions(tmp_path):
    a=RecoveryStore(tmp_path);b=RecoveryStore(tmp_path)
    try:
        a.save(analyze(beam()),NC1Header(),'/parts/original.step',{'quantity':'unfinished edit','steel_quality':'A36'})
        assert b.available()==[]
        a.close()
        available=b.available();assert len(available)==1
        path,data=available[0]
        assert data['recovery']['form']['quantity']=='unfinished edit'
        fs,_,source=load_project(path)
        assert fs.section.family=='W' and source=='/parts/original.step'
        b.discard_path(path);assert b.available()==[]
    finally:a.close();b.close(discard=True)


@pytest.mark.parametrize('cancel',[True,False])
def test_active_worker_is_reaped_on_cancel_or_timeout(tmp_path,monkeypatch,cancel):
    (tmp_path/'scripts').mkdir();(tmp_path/'core').mkdir()
    (tmp_path/'scripts/convert_worker.py').write_text('import time\ntime.sleep(30)\n')
    monkeypatch.setattr(conversion,'__file__',str(tmp_path/'core/conversion.py'))
    processes=[];real_popen=subprocess.Popen
    def tracked(*args,**kwargs):
        p=real_popen(*args,**kwargs);processes.append(p);return p
    monkeypatch.setattr(conversion.subprocess,'Popen',tracked)
    event=threading.Event();timer=threading.Timer(.35,event.set)
    out=tmp_path/'existing.nc1';out.write_text('Keep this')
    if cancel:timer.start()
    start=time.monotonic()
    try:row=conversion.isolated_convert('part.step',out,force=True,timeout=10 if cancel else .3,cancel_event=event)
    finally:
        if cancel:timer.join()
    assert time.monotonic()-start<5
    assert row['diagnostic']['code']==('CANCELLED' if cancel else 'TIMEOUT')
    assert processes[0].poll() is not None
    assert out.read_text()=='Keep this'


def test_support_bundle_excludes_source_files(tmp_path):
    import zipfile
    path=write_support_bundle(tmp_path/'support.zip',{'errors':['example']})
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist())=={'README.txt','environment.json','diagnostics.json'}
        assert json.loads(archive.read('diagnostics.json'))['errors']==['example']


def test_header_miter_preview_follows_the_cut_plane():
    import cadquery as cq
    from core.stock_preview import end_outline
    cutter=cq.Workplane('XY',origin=(0,0,-1)).polyline([(-1,-1),(-.25,-1),(50.25,201),(-1,201)]).close().extrude(102).val()
    fs=analyze(beam().cut(cutter))
    points=end_outline(fs.section,fs.end_cuts,'v')
    assert points[:2]==pytest.approx([(0,0),(50,200)])


def test_round_pipe_preview_has_unrolled_circumference():
    import math
    from test_round_pipe import pipe,analyze as analyze_pipe
    from core.stock_preview import end_outline,face_span
    fs=analyze_pipe(pipe())
    assert face_span(fs.section,'v')==pytest.approx(math.pi*100)
    assert max(y for x,y in end_outline(fs.section,fs.end_cuts,'v'))==pytest.approx(math.pi*100)
    assert end_outline(fs.section,fs.end_cuts,'o')==[]


def test_exclusive_atomic_publish_preserves_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from core.dstv_writer import atomic_write
    barrier=Barrier(2);target=tmp_path/'part.nc1'
    def publish(text):
        barrier.wait()
        try:
            atomic_write(target,text,overwrite=False)
            return text
        except FileExistsError:
            return None
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(publish,['A'*10000,'B'*10000]))
    winners=[r for r in results if r is not None]
    assert len(winners)==1
    assert target.read_text()==winners[0]
    assert list(tmp_path.iterdir())==[target]
