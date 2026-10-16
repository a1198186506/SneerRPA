"""Frozen single-workflow UI and isolated execution process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


def embedded_flow():
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    return json.loads((root/'workflow.json').read_text(encoding='utf-8'))


def run_worker(events,start=None,cancel=None):
    import worker
    try:output=Path(events).open('w',encoding='utf-8',buffering=1)
    except OSError:return 1
    with output:
        def emit(event,**data):output.write(json.dumps({'event':event,**data},ensure_ascii=False)+'\n');output.flush()
        worker.emit=emit
        emit('worker_ready',pid=os.getpid())
        if start:
            deadline=time.monotonic()+15
            while not Path(start).exists():
                if cancel and Path(cancel).exists():return 0
                if time.monotonic()>deadline:return 1
                time.sleep(.05)
        if cancel and Path(cancel).exists():return 0
        try:
            worker.execute(embedded_flow());emit('run_finished',status='completed',message='流程执行完成');return 0
        except Exception as exc:
            emit('run_finished',status='failed',message=str(exc));return 1


def main():
    import tkinter as tk
    from tkinter import ttk,messagebox
    from tkinter.scrolledtext import ScrolledText
    import win32api,win32con
    flow=embedded_flow()
    root=tk.Tk();root.title(flow.get('name','工作流')+' · SneerRPA');root.geometry('720x460');root.minsize(560,340)
    root.configure(background='#f6f7fb')
    ttk.Label(root,text=flow.get('name','工作流'),font=('Microsoft YaHei UI',16)).pack(anchor='w',padx=20,pady=(20,8))
    status=tk.StringVar(value='准备就绪，点击运行开始执行工作流')
    ttk.Label(root,textvariable=status).pack(anchor='w',padx=20,pady=(0,12))
    bar=ttk.Frame(root);bar.pack(fill='x',padx=20)
    text=ScrolledText(root,font=('Microsoft YaHei UI',10),state='disabled',wrap='word');text.pack(fill='both',expand=True,padx=20,pady=16)
    temporary=tempfile.TemporaryDirectory(prefix=f'SneerRPA-run-{os.getpid()}-');directory=Path(temporary.name)
    state={'process':None,'pid':None,'handle':None,'offset':0,'terminal':False,'stopped':False,'started':False}
    events=directory/'events.jsonl';start=directory/'start';cancel=directory/'cancel'

    def log(message):
        text.configure(state='normal');text.insert('end',message+'\n')
        if int(text.index('end-1c').split('.')[0])>1500:text.delete('1.0','100.0')
        text.see('end');text.configure(state='disabled')

    def poll_events():
        if not events.exists():return
        with events.open(encoding='utf-8') as handle:
            handle.seek(state['offset'])
            while True:
                offset=handle.tell();line=handle.readline()
                if not line.endswith('\n'):handle.seek(offset);break
                data=json.loads(line)
                if data['event']=='worker_ready':
                    if not state['stopped']:state['handle']=win32api.OpenProcess(win32con.PROCESS_TERMINATE|win32con.SYNCHRONIZE,False,data['pid'])
                    state['pid']=data['pid']
                elif data['event']=='run_finished':
                    state['terminal']=True
                    if not state['stopped']:status.set('执行成功' if data['status']=='completed' else '执行失败')
                if data.get('message'):log(data['message'])
            state['offset']=handle.tell()

    def run():
        nonlocal events,start,cancel
        if state['process'] is not None:return
        run_directory=directory/str(uuid.uuid4());run_directory.mkdir()
        events=run_directory/'events.jsonl';start=run_directory/'start';cancel=run_directory/'cancel'
        state.update(pid=None,offset=0,terminal=False,stopped=False,started=False)
        command=[sys.executable,'--sneerrpa-worker','--events',str(events),'--start',str(start),'--cancel',str(cancel)]
        if not getattr(sys,'frozen',False):command.insert(1,str(Path(__file__).resolve()))
        try:
            state['process']=subprocess.Popen(command,cwd=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent,
                creationflags=subprocess.CREATE_NO_WINDOW,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            status.set('正在启动执行器…');run_button.configure(state='disabled');stop_button.configure(state='normal')
        except Exception as exc:status.set('启动失败');log(str(exc))

    def stop():
        process=state['process']
        if not process:return
        state['stopped']=True;cancel.touch()
        try:poll_events()
        except Exception as exc:log(str(exc))
        # Terminate the actual Python worker, not applications it has launched.
        if state['handle']:
            try:
                win32api.TerminateProcess(state['handle'],1)
            except Exception:pass
        status.set('已停止');log('执行已停止')

    def tick():
        process=state['process']
        if process:
            try:
                poll_events()
                if state['pid'] and not state['started'] and not state['stopped']:
                    start.touch();state['started']=True;status.set('运行中')
            except Exception as exc:log(str(exc));stop()
            if process.poll() is not None:
                poll_events()
                if not state['terminal'] and not state['stopped']:status.set('执行器异常退出');log('执行器异常退出')
                state['process']=None;run_button.configure(state='normal');stop_button.configure(state='disabled')
                if state['handle']:state['handle'].Close();state['handle']=None
        root.after(120,tick)

    def close():
        if state['process'] and not messagebox.askyesno('退出工作流','正在运行，是否停止并退出？',parent=root):return
        stop()
        if state['process']:
            try:state['process'].wait(timeout=3)
            except subprocess.TimeoutExpired:state['process'].terminate()
        root.destroy()

    run_button=ttk.Button(bar,text='运行工作流',command=run);run_button.pack(side='left')
    stop_button=ttk.Button(bar,text='停止',command=stop,state='disabled');stop_button.pack(side='left',padx=10)
    root.protocol('WM_DELETE_WINDOW',close);root.after(120,tick)
    try:root.mainloop()
    finally:
        if state['handle']:state['handle'].Close()
        temporary.cleanup()


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    if sys.stdout is None:sys.stdout=open(os.devnull,'w',encoding='utf-8')
    if sys.stderr is None:sys.stderr=open(os.devnull,'w',encoding='utf-8')
    if '--sneerrpa-worker' in sys.argv:
        import argparse
        parser=argparse.ArgumentParser();parser.add_argument('--sneerrpa-worker',action='store_true');parser.add_argument('--events',required=True);parser.add_argument('--start');parser.add_argument('--cancel')
        args=parser.parse_args();sys.exit(run_worker(args.events,args.start,args.cancel))
    main()
