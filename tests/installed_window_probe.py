"""Launch installed native WebView2 window from an unrelated working directory."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import win32con
import win32gui
import win32process

app = Path(sys.argv[1]).resolve()
environment = dict(os.environ)
for key in list(environment):
    if key.lower() in ('pythonhome', 'pythonpath', 'psmodulepath', 'sneerrpa_projects_dir'):
        del environment[key]
environment['PATH'] = r'C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0'
with tempfile.TemporaryDirectory(prefix='sneerrpa-installed-window-') as temporary:
    environment['SNEERRPA_DATA_DIR'] = str(Path(temporary) / 'data')
    process = subprocess.Popen([str(app / 'SneerRPA.exe')], cwd=temporary, env=environment)
    try:
        windows = []
        for _ in range(120):
            def inspect(hwnd, _):
                if win32process.GetWindowThreadProcessId(hwnd)[1] == process.pid and win32gui.IsWindowVisible(hwnd):
                    windows.append(hwnd)
            win32gui.EnumWindows(inspect, None)
            if windows:
                break
            if process.poll() is not None:
                raise RuntimeError('Installed GUI exited: ' + str(process.returncode))
            time.sleep(.1)
        assert windows, 'Installed WebView2 window did not appear'
        title = win32gui.GetWindowText(windows[0])
        assert 'SneerRPA' in title, title
        time.sleep(2)
        win32gui.PostMessage(windows[0], win32con.WM_CLOSE, 0, 0)
        assert process.wait(timeout=15) == 0
        print('PASS: installed native WebView2 window opens and closes normally: ' + title)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
