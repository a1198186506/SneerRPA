"""Build a standalone Windows workflow runner without executing its workflow."""
import json
import copy
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from validation import validate_flow,walk_steps
from runtime_resources import PREFIX,BUILTINS

ROOT=Path(__file__).resolve().parent.parent
RESERVED=re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',re.I)


def export_target(directory,filename):
    if not isinstance(directory,str) or not Path(directory).is_absolute() or not Path(directory).is_dir():
        raise ValueError('请选择存在的绝对路径文件夹')
    if not isinstance(filename,str):raise ValueError('请输入 EXE 文件名')
    if filename.lower().endswith('.exe'):filename=filename[:-4]
    if not filename or filename!=filename.strip() or filename.endswith('.') or len(filename)>100 or any(ord(c)<32 or c in '<>:"/\\|?*' for c in filename) or RESERVED.match(filename):
        raise ValueError('文件名无效，请勿使用路径、保留名称或特殊字符')
    target=Path(directory).resolve()/(filename+'.exe')
    if target.exists():raise ValueError('同名文件已存在，请更换文件名')
    return target


def publish_exe(source,target):
    # Stage on the destination volume, then rename atomically. Windows refuses
    # to replace an existing destination, including one created during the build.
    target=Path(target)
    if target.exists():raise ValueError('同名文件已存在，请更换文件名')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.sneerrpa-',suffix='.tmp',delete=False) as handle:
            temporary=Path(handle.name)
            with Path(source).open('rb') as src:shutil.copyfileobj(src,handle,1024*1024)
        os.rename(temporary,target)
    finally:
        if temporary and temporary.exists():temporary.unlink()
    return target.stat().st_size


def prepare_flow(original):
    flow=copy.deepcopy(validate_flow(original));resources=set()
    def rewrite(value):
        if not isinstance(value,str):return value
        normalized=value.replace('\\','/')
        for relative in BUILTINS:
            if normalized.casefold() in (relative.casefold(),(PREFIX+relative).casefold()) or (Path(value).is_absolute() and Path(value).resolve()==(ROOT/relative).resolve()):
                resources.add(relative);return PREFIX+relative
        return value
    for step in walk_steps(flow['steps']):
        if step['type']=='app.launch':
            params=step['params']
            if 'path' in params:params['path']=rewrite(params['path'])
            if 'args' in params:params['args']=[rewrite(value) for value in params['args']]
    return flow,sorted(resources)


def build(job,emit):
    flow,resources=prepare_flow(json.loads((job/'workflow.json').read_text(encoding='utf-8')))
    (job/'workflow.json').write_text(json.dumps(flow,ensure_ascii=False),encoding='utf-8')
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--onefile','--windowed','--name','workflow',
        '--distpath',str(job/'dist'),'--workpath',str(job/'build'),'--specpath',str(job),
        '--paths',str(ROOT/'extensions'),
        '--add-data',str(job/'workflow.json')+os.pathsep+'.',
        '--add-data',str(ROOT/'resources/actions.json')+os.pathsep+'resources',
        '--collect-submodules','pywinauto','--hidden-import','win32timezone',
        '--exclude-module','pytest','--exclude-module','IPython',
        str(ROOT/'extensions/standalone_runner.py')]
    for relative in resources:
        source=ROOT/relative
        if not source.is_file():raise ValueError('内置资源缺失：'+relative)
        command[3:3]=['--add-data',str(source)+os.pathsep+str(Path(relative).parent)]
    emit('export_progress',message='正在分析并打包 Python、窗口自动化和图像依赖…')
    process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
    tail=[]
    for line in process.stdout:
        message=line.strip()
        if message:
            tail.append(message);tail=tail[-15:]
            emit('export_progress',message=message)
    if process.wait()!=0:raise RuntimeError('EXE 打包失败：'+'\n'.join(tail))
    result=job/'dist/workflow.exe'
    if not result.is_file():raise RuntimeError('未生成 EXE 文件')
    emit('export_built',message='EXE 已生成，正在保存…')


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    def emit(event,**data):print(json.dumps({'event':event,**data},ensure_ascii=False),flush=True)
    try:build(Path(sys.argv[1]),emit)
    except Exception as exc:emit('export_failed',message=str(exc));sys.exit(1)
