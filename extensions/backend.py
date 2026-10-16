"""Neutralino extension bridge; long running actions live in a worker process."""
import asyncio
import json
import os
import shutil
from pathlib import Path
import sys
import uuid
from urllib.parse import urlencode

from websockets.asyncio.client import connect
from validation import validate_flow, validate_selector
from projects import ProjectStore
from exe_export import export_target,publish_exe
from app_paths import DATA, BUILD_JOBS

ROOT = Path(__file__).resolve().parent.parent


class Backend:
    def __init__(self, socket, token):
        self.socket, self.token = socket, token
        self.process = None
        self.task = None
        self.run_id = None
        self.lock = asyncio.Lock()
        self.helper_process = None
        self.helper_task = None
        self.stop_requested = False
        self.projects=ProjectStore(os.environ.get('SNEERRPA_PROJECTS_DIR',DATA/'projects'),DATA/'current-flow.json')
        self.export_process=None
        self.export_task=None
        self.export_job=None
        self.export_cancelled=False

    def stop_export(self):
        self.export_cancelled=True
        if self.export_job:
            self.export_job.Close();self.export_job=None
        elif self.export_process and self.export_process.returncode is None:self.export_process.kill()

    async def export_flow(self,flow,target,export_id):
        job=BUILD_JOBS/export_id
        process=None;completed=False
        try:
            if self.export_cancelled:
                await self.emit('export_finished',export_id=export_id,status='cancelled',message='已取消 EXE 导出');return
            import win32api,win32con,win32job
            job.mkdir(parents=True)
            (job/'workflow.json').write_text(json.dumps(flow,ensure_ascii=False),encoding='utf-8')
            process=await asyncio.create_subprocess_exec(sys.executable,'-u',str(ROOT/'extensions/exe_export.py'),str(job),
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT,cwd=ROOT)
            self.export_process=process
            handle=win32job.CreateJobObject(None,'')
            self.export_job=handle
            limits=win32job.QueryInformationJobObject(handle,win32job.JobObjectExtendedLimitInformation)
            limits['BasicLimitInformation']['LimitFlags']=win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(handle,win32job.JobObjectExtendedLimitInformation,limits)
            native=win32api.OpenProcess(win32con.PROCESS_SET_QUOTA|win32con.PROCESS_TERMINATE,False,process.pid)
            try:win32job.AssignProcessToJobObject(handle,native)
            finally:native.Close()
            if self.export_cancelled:self.stop_export()
            failure='打包进程异常退出'
            async for raw in process.stdout:
                try:item=json.loads(raw.decode('utf-8'))
                except (ValueError,UnicodeError):item={'event':'export_progress','message':raw.decode('utf-8','replace').strip()}
                if item['event']=='export_failed':failure=item.get('message',failure)
                else:await self.emit('export_progress',export_id=export_id,message=item.get('message',''))
            code=await process.wait()
            if self.export_cancelled:
                await self.emit('export_finished',export_id=export_id,status='cancelled',message='已取消 EXE 导出');return
            if code:raise RuntimeError(failure)
            size=publish_exe(job/'dist/workflow.exe',target);completed=True
            await self.emit('export_finished',export_id=export_id,status='completed',path=str(target),size=size,message='EXE 导出完成')
        except asyncio.CancelledError:raise
        except Exception as exc:
            await self.emit('export_finished',export_id=export_id,status='failed',message=str(exc))
        finally:
            if self.export_job:self.export_job.Close();self.export_job=None
            if process and process.returncode is None:process.kill();await process.wait()
            self.export_process=None
            if completed and job.resolve().parent==BUILD_JOBS.resolve():shutil.rmtree(job,ignore_errors=True)

    async def tool(self, request, request_id):
        process = None
        try:
            process = await asyncio.create_subprocess_exec(sys.executable, '-u', str(ROOT / 'extensions/tools.py'),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=sys.stderr, cwd=str(ROOT))
            self.helper_process = process
            output, _ = await asyncio.wait_for(process.communicate((json.dumps(request, ensure_ascii=False) + '\n').encode('utf-8')), timeout=75)
            result = json.loads(output.decode('utf-8').strip())
            if not result.get('ok'):
                raise ValueError(result.get('message', '工具执行失败'))
            await self.emit('tool_result', request_id=request_id, operation=request['operation'], result=result['result'])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.emit('error', request_id=request_id, message=str(exc) or '工具执行超时')
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            self.helper_process = None

    async def emit(self, event, **data):
        await self.socket.send(json.dumps({"id": str(uuid.uuid4()), "method": "app.broadcast",
            "accessToken": self.token, "data": {"event": "rpa", "data": {"event": event, **data}}}, ensure_ascii=False))

    async def monitor(self, process, run_id):
        terminal = None
        try:
            async for line in process.stdout:
                try:
                    item = json.loads(line)
                    if item.get("event") == "run_finished":
                        terminal = item
                        continue
                    await self.emit(**item, run_id=run_id)
                except (ValueError, TypeError):
                    await self.emit("log", run_id=run_id, message=line.decode("utf-8", "replace"))
            code = await process.wait()
            if self.process is process:
                self.process = None
            if terminal:
                await self.emit(**terminal, run_id=run_id)
            else:
                await self.emit("run_finished", run_id=run_id, status="stopped" if self.stop_requested else "failed",
                                message="任务已停止" if self.stop_requested else f"执行器异常退出（{code}）")
        finally:
            if self.process is process:
                self.process = None

    async def handle(self, data):
        command, request_id = data.get("command"), data.get("request_id")
        async with self.lock:
            try:
                if command == "ping":
                    await self.emit("ready", request_id=request_id, message="Python 执行引擎已连接")
                elif command=='list_projects':
                    projects,warnings=self.projects.list()
                    await self.emit('projects_listed',request_id=request_id,projects=projects,warnings=warnings)
                elif command=='create_project':
                    project=self.projects.create(data.get('name'),data.get('flow'))
                    await self.emit('project_created',request_id=request_id,project=project)
                elif command=='load_project':
                    await self.emit('project_loaded',request_id=request_id,project=self.projects.load(data.get('project_id')))
                elif command=='save_project':
                    project=self.projects.save(data.get('project_id'),data['flow'])
                    await self.emit('project_saved',request_id=request_id,project_id=project['id'],updated_at=project['updated_at'])
                elif command=='export_exe':
                    import importlib.util
                    if self.process or self.helper_process:raise ValueError('请先停止工作流及定位工具再导出')
                    if self.export_task and not self.export_task.done():raise ValueError('已有 EXE 正在导出')
                    if importlib.util.find_spec('PyInstaller') is None:raise ValueError('缺少 EXE 打包依赖，请运行 start.ps1 安装后重启项目')
                    flow=validate_flow(data['flow'])
                    target=export_target(data.get('directory'),data.get('filename'))
                    export_id=str(uuid.uuid4());self.export_cancelled=False
                    self.export_task=asyncio.create_task(self.export_flow(flow,target,export_id))
                    await self.emit('export_started',request_id=request_id,export_id=export_id,message='开始导出 EXE')
                elif command=='cancel_export':
                    self.stop_export();await self.emit('export_cancel_requested',request_id=request_id)
                elif command == 'load_flow':
                    saved = DATA / 'current-flow.json'
                    source = saved if saved.exists() else ROOT / 'resources/sample-flow.json'
                    flow = validate_flow(json.loads(source.read_text(encoding='utf-8')), allow_empty=True, draft=True)
                    await self.emit('flow_loaded', request_id=request_id, flow=flow)
                elif command == 'save_flow':
                    flow = validate_flow(data['flow'], allow_empty=True, draft=True)
                    destination = DATA / 'current-flow.json'
                    destination.parent.mkdir(exist_ok=True)
                    temp = destination.with_suffix('.tmp')
                    temp.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding='utf-8')
                    temp.replace(destination)
                    await self.emit('flow_saved', request_id=request_id)
                elif command == 'validate_selector':
                    validate_selector(data['selector'])
                    await self.emit('selector_valid', request_id=request_id)
                elif command in ('pick_element', 'pick_coordinates', 'pick_image', 'test_element', 'list_windows', 'test_image'):
                    if self.export_task and not self.export_task.done():raise ValueError('请先完成 EXE 导出')
                    if self.process is not None:
                        raise ValueError('请先停止当前流程再使用定位工具')
                    if self.helper_task and not self.helper_task.done():
                        raise ValueError('已有定位工具正在运行')
                    self.helper_task = asyncio.create_task(self.tool({'operation': command, **{k: v for k, v in data.items() if k not in ('command', 'request_id')}}, request_id))
                elif command == 'cancel_tool':
                    if self.helper_task and not self.helper_task.done():
                        self.helper_task.cancel()
                        await asyncio.gather(self.helper_task, return_exceptions=True)
                    await self.emit('tool_cancelled', request_id=request_id)
                elif command == "run_flow":
                    if self.export_task and not self.export_task.done():raise ValueError('请先完成 EXE 导出')
                    if self.process is not None:
                        raise ValueError("已有任务正在运行")
                    if self.helper_task and not self.helper_task.done():
                        raise ValueError('请先完成或取消元素定位工具')
                    flow = validate_flow(data["flow"])
                    self.stop_requested = False
                    run_id = str(uuid.uuid4())
                    process = await asyncio.create_subprocess_exec(sys.executable, "-u", str(ROOT / "extensions/worker.py"),
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=sys.stderr, cwd=str(ROOT))
                    self.process, self.run_id = process, run_id
                    await self.emit("run_started", run_id=run_id, request_id=request_id, message="开始执行流程")
                    process.stdin.write((json.dumps(flow, ensure_ascii=False) + "\n").encode("utf-8"))
                    await process.stdin.drain()
                    process.stdin.close()
                    self.task = asyncio.create_task(self.monitor(process, run_id))
                elif command == "stop_run":
                    if self.process and self.process.returncode is None:
                        self.stop_requested = True
                        self.process.terminate()
                        await self.process.wait()
                    await self.emit('stop_requested', request_id=request_id)
                else:
                    raise ValueError(f"未知命令：{command}")
            except Exception as exc:
                await self.emit("error", request_id=request_id, message=str(exc))

    async def close(self):
        if self.export_task and not self.export_task.done():
            self.stop_export();self.export_task.cancel();await asyncio.gather(self.export_task,return_exceptions=True)
        if self.helper_task:
            self.helper_task.cancel()
            await asyncio.gather(self.helper_task, return_exceptions=True)
        if self.process and self.process.returncode is None:
            self.process.kill()
            await self.process.wait()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


async def main():
    config = json.loads(sys.stdin.read())
    query = urlencode({"extensionId": config["nlExtensionId"], "connectToken": config["nlConnectToken"]})
    async with connect(f"ws://127.0.0.1:{config['nlPort']}?{query}", max_size=32*1024*1024) as socket:
        backend = Backend(socket, config["nlToken"])
        try:
            async for raw in socket:
                message = json.loads(raw)
                if message.get("event") == "command":
                    await backend.handle(message.get("data", {}))
        finally:
            await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
