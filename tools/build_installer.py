"""Build a self-contained Windows x64 editor and offline NSIS installer.

Run with the project's venv Python. NSIS and the signed WebView2 offline
installer are build tools in .tmp/installer-tools (never shipped as app data).
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / '.tmp/installer-tools'


def copy_tree(source, target):
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'), dirs_exist_ok=True)


def stage_app(stage):
    if stage.exists():
        raise ValueError('Staging directory already exists; choose a new directory')
    stage.mkdir(parents=True)
    version = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version']
    base = Path(sys.base_prefix)
    runtime = stage / 'runtime'
    runtime.mkdir()
    for pattern in ('python*.exe', 'python*.dll', 'vcruntime*.dll', 'LICENSE.txt'):
        for source in base.glob(pattern):
            shutil.copy2(source, runtime / source.name)
    for folder in ('DLLs', 'tcl', 'libs', 'include'):
        copy_tree(base / folder, runtime / folder)
    shutil.copytree(base / 'Lib', runtime / 'Lib', ignore=shutil.ignore_patterns('site-packages', '__pycache__', '*.pyc', 'test', 'tests'))
    copy_tree(Path(sys.prefix) / 'Lib/site-packages', runtime / 'Lib/site-packages')
    # Isolate from Python installations, registry entries, and PYTHONPATH on the
    # target computer while retaining site setup required by pywin32.
    (runtime / 'python311._pth').write_text('.\nLib\nDLLs\nLib/site-packages\n../extensions\nimport site\n', encoding='utf-8')
    config = json.loads((ROOT / 'neutralino.config.json').read_text(encoding='utf-8'))
    config['extensions'][0]['commandWindows'] = '"${NL_PATH}/runtime/python.exe" -u "${NL_PATH}/extensions/backend.py"'
    config['modes']['window']['enableInspector'] = False
    config['exportAuthInfo'] = False
    resource_stage = stage.parent / (stage.name + '-resources')
    copy_tree(ROOT / 'resources', resource_stage / 'resources')
    (resource_stage / 'neutralino.config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    # Build from a clean directory: neu's default bundler archives all of .tmp,
    # which can contain test data and build artifacts in a development checkout.
    subprocess.run(['node', '-e', "require('@electron/asar').createPackage(process.argv[1],process.argv[2]).catch(e=>{console.error(e);process.exit(1)})", str(resource_stage), str(stage / 'resources.neu')], cwd=ROOT, check=True)
    shutil.copy2(ROOT / 'bin/neutralino-win_x64.exe', stage / 'SneerRPA.exe')
    for folder in ('extensions', 'tools'):
        (stage / folder).mkdir()
    for source in (ROOT / 'extensions').glob('*.py'):
        shutil.copy2(source, stage / 'extensions' / source.name)
    # Python engine and exporter read the catalog and built-in sample by path.
    copy_tree(ROOT / 'resources', stage / 'resources')
    shutil.copy2(ROOT / 'tools/test-window.ps1', stage / 'tools/test-window.ps1')
    (stage / 'installed.json').write_text(json.dumps({'name': 'SneerRPA', 'version': version}), encoding='utf-8')
    (stage / '使用说明.txt').write_text('SneerRPA 工作室 '+version+'\n\n直接启动 SneerRPA.exe，无需安装 Python 或 Node.js。\n项目自动保存在 %LOCALAPPDATA%\\SneerRPA\\projects。\n升级、卸载不会删除此目录。\n可通过项目菜单导入原开发版导出的工作流 JSON。\n安装包包含 Python、OpenCV、窗口自动化、EXE 导出依赖和 WebView2 离线安装程序。\n', encoding='utf-8')
    shutil.copy2(ROOT / 'README.md', stage / 'README.md')
    return version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path, default=ROOT / '.tmp' / ('installer-stage-' + str(int(time.time()))))
    parser.add_argument('--compile-only', action='store_true')
    parser.add_argument('--stage-only', action='store_true')
    args = parser.parse_args()
    stage = args.stage.resolve()
    version = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))['version'] if args.compile_only else stage_app(stage)
    print('Staged application: ' + str(stage), flush=True)
    if args.stage_only:
        return
    compilers = list(TOOLS.rglob('makensis.exe'))
    if not compilers:
        raise RuntimeError('Place a Windows NSIS distribution in .tmp/installer-tools')
    webview = TOOLS / 'MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
    if not webview.is_file():
        raise RuntimeError('Download the Microsoft WebView2 x64 offline installer into .tmp/installer-tools')
    signature_env = {key: value for key, value in os.environ.items() if key.lower() != 'psmodulepath'}
    subprocess.run(['powershell.exe', '-NoProfile', '-Command', "$s=Get-AuthenticodeSignature -LiteralPath '"+str(webview).replace("'", "''")+"'; if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notlike '*O=Microsoft Corporation,*'){throw 'Invalid Microsoft signature'}"], check=True, env=signature_env)
    output = ROOT / 'dist' / ('SneerRPA-Setup-' + version + '-x64.exe')
    output.parent.mkdir(exist_ok=True)
    subprocess.run([str(compilers[0]), '/INPUTCHARSET', 'UTF8', '/DAPP_STAGE='+str(stage), '/DWEBVIEW_INSTALLER='+str(webview), '/DAPP_VERSION='+version, '/DOUTPUT_FILE='+str(output), str(ROOT / 'tools/installer.nsi')], check=True)
    print('Installer: ' + str(output), flush=True)


if __name__ == '__main__':
    main()
