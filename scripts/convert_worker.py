"""Private subprocess boundary; JSON in, a tagged JSON result out."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def run():
    from main import convert_one
    try:
        request=json.load(sys.stdin)
        result=convert_one(**request)
    except Exception as exc:
        result={'source':str(locals().get('request',{}).get('path','')),'status':'error','error':str(exc)}
    print('STEP2NC1_RESULT='+json.dumps(result,ensure_ascii=True,allow_nan=False),flush=True)
    return 0

if __name__=='__main__':raise SystemExit(run())
