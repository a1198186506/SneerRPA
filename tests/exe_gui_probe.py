import subprocess
import sys
import time
import tempfile
import json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'extensions'))
from automation import find_window,NotFound

process=subprocess.Popen([sys.argv[1]],creationflags=subprocess.CREATE_NO_WINDOW)
window=None
try:
    deadline=time.monotonic()+25
    while True:
        try:
            window=find_window({'backend':'win32','title':'独立 EXE 验证 · SneerRPA'});break
        except NotFound:
            if process.poll() is not None:raise RuntimeError('Exported GUI exited before opening')
            if time.monotonic()>deadline:raise
            time.sleep(.2)
    assert window.is_visible()
    # Tk draws its buttons as TkChild windows. Locate the two-button toolbar by
    # its geometry, then exercise actual clicks; inspect only this runner's logs.
    bar=next(c for c in window.descendants() if len(c.children())==2 and c.rectangle().height()<90 and c.rectangle().width()>window.rectangle().width()*.6)
    run_button,stop_button=sorted(bar.children(),key=lambda c:c.rectangle().left)
    directory=next(Path(tempfile.gettempdir()).glob(f'SneerRPA-run-{window.process_id()}-*'))
    def finish_run():
        before=set(directory.iterdir());run_button.click_input();deadline=time.monotonic()+30
        while True:
            created=set(directory.iterdir())-before
            for folder in created:
                file=folder/'events.jsonl'
                if file.exists():
                    items=[json.loads(line) for line in file.read_text(encoding='utf-8').splitlines() if line.strip()]
                    terminal=next((item for item in items if item['event']=='run_finished'),None)
                    if terminal:
                        assert terminal['status']=='completed',items
                        assert any(item.get('name')=='typed_value' and item.get('value')=='Frozen RPA 中文' for item in items),items
                        assert any(item.get('message','').startswith('FROZEN_DONE 已确认：') for item in items),items
                        time.sleep(1);return
            if time.monotonic()>deadline:raise TimeoutError('GUI run did not complete')
            time.sleep(.2)
    finish_run()
    run_button.click_input();stop_button.click_input();time.sleep(2)
    finish_run()
    window.close();process.wait(timeout=10)
    assert process.returncode==0,process.returncode
    print('PASS: frozen Tk runtime Run, Stop, rerun and close')
finally:
    if window:
        try:window.close()
        except Exception:pass
    if process.poll() is None:process.terminate()
