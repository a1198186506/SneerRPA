"""One isolated run. stdout is newline-delimited JSON; stderr is diagnostics."""
import json
import math
import sys
import time
import traceback
from automation import Context
from validation import validate_flow, DEFINITIONS
from parameters import effective_params


def emit(event, **data):
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def execute(flow):
    validate_flow(flow)
    context = Context(flow, emit)
    execute_steps(flow['steps'],context)


def skip_steps(steps):
    for step in steps:
        emit('node_skipped',node_id=step['id'],message='分支未执行')
        for branch in ('then_steps','else_steps','body_steps'):
            skip_steps(step.get(branch,[]))


class LoopSignal(Exception):
    def __init__(self,kind):
        self.kind=kind


def execute_loop(step,params,context):
    count=context.reference(params['count_variable']) if params['count_source']=='reference' else params['count']
    if type(count) not in (int,float) or not math.isfinite(count) or count<0 or count!=int(count):
        raise ValueError('循环次数必须是非负整数的 number，不能使用布尔值或小数')
    if count>params['max_iterations']:
        raise ValueError(f'循环次数 {count:g} 超过设置的上限 {params["max_iterations"]}')
    body=step.get('body_steps',[])
    if not count:
        skip_steps(body)
    # Resolve count once. Updates to the source variable affect later entries only.
    for index in range(1,int(count)+1):
        context.store(params['index_variable'],index)
        emit('loop_iteration',node_id=step['id'],iteration=index,total=int(count),message=f'循环第 {index}/{int(count)} 次')
        try:
            execute_steps(body,context)
        except LoopSignal as signal:
            if signal.kind=='control.break':
                break


def execute_steps(steps,context):
    for position,step in enumerate(steps):
        node_id = step["id"]
        emit("node_started", node_id=node_id, message=step.get("name", step["type"]))
        try:
            kind = step['type']
            params = effective_params(kind, step.get('params', {}))
            if kind=='control.loop':
                execute_loop(step,params,context)
            elif kind in ('control.break','control.continue'):
                raise LoopSignal(kind)
            elif kind=='control.if':
                result=context.condition(params)
                emit('branch_taken',node_id=node_id,branch='then' if result else 'else',message='条件为真' if result else '条件为假')
                skip_steps(step.get('else_steps' if result else 'then_steps',[]))
                execute_steps(step.get('then_steps' if result else 'else_steps',[]),context)
            elif kind == "log":
                emit("log", node_id=node_id, message=context.interpolate(str(params.get("message", ""))))
            elif kind == "wait":
                seconds = float(params.get("seconds", 1))
                if not 0 <= seconds <= 3600:
                    raise ValueError("等待时间必须在 0–3600 秒之间")
                time.sleep(seconds)
            elif kind == "demo_window":
                demo_window(str(params.get("text", "Hello from SneerRPA")), node_id)
            else:
                context.action(kind, params)
            emit("node_finished", node_id=node_id, message="步骤完成")
        except LoopSignal:
            emit('node_finished',node_id=node_id,message='已跳出循环' if kind=='control.break' else '已进入下一轮' if kind=='control.continue' else '分支结束')
            skip_steps(steps[position+1:])
            raise
        except Exception as exc:
            emit("node_failed", node_id=node_id, message=str(exc))
            raise


def demo_window(text, node_id):
    # Own the test window: never type into an unrelated foreground application.
    import tkinter as tk
    import queue
    import threading
    root = tk.Tk()
    root.title("SneerRPA 自动化测试窗口")
    root.geometry("560x230")
    root.attributes("-topmost", True)
    tk.Label(root, text="SneerRPA · Python 自动化测试", font=("Microsoft YaHei UI", 16)).pack(pady=20)
    entry = tk.Entry(root, font=("Microsoft YaHei UI", 12))
    entry.pack(fill="x", padx=24)
    label = tk.Label(root, text="等待执行器输入并点击按钮…")
    label.pack(pady=12)
    tk.Button(root, text="确认", command=lambda: label.config(text="已确认：" + entry.get())).pack()
    root.update()
    result = queue.Queue()
    entry_point = (entry.winfo_rootx() + 20, entry.winfo_rooty() + 10)
    button = root.winfo_children()[-1]
    button_point = (button.winfo_rootx() + button.winfo_width() // 2, button.winfo_rooty() + button.winfo_height() // 2)

    def automate():
        try:
            from pywinauto import mouse, keyboard
            mouse.click(coords=entry_point)
            time.sleep(0.15)
            escaped = ''.join('{' + c + '}' if c in '{}+^%~()' else c for c in text)
            keyboard.send_keys(escaped, with_spaces=True, vk_packet=True, pause=0.03)
            time.sleep(0.15)
            mouse.click(coords=button_point)
            time.sleep(0.3)
            result.put(None)
        except Exception as exc:
            result.put(exc)

    outcome = []

    def poll():
        try:
            outcome.append(result.get_nowait())
            root.quit()
        except queue.Empty:
            root.after(50, poll)

    try:
        # Keep Tk's event loop live while a separate thread injects real input.
        root.after(250, lambda: threading.Thread(target=automate, daemon=True).start())
        root.after(300, poll)
        root.mainloop()
        if not outcome:
            raise RuntimeError("测试窗口提前关闭")
        if outcome[0]:
            raise outcome[0]
        if entry.get() != text or label.cget("text") != "已确认：" + text:
            raise RuntimeError(f"测试窗口验证失败：输入={entry.get()!r}，确认={label.cget('text')!r}")
        emit("log", node_id=node_id, message="真实窗口验证成功：输入文本并点击确认")
    finally:
        root.destroy()


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        execute(json.loads(sys.stdin.readline()))
        emit("run_finished", status="completed", message="流程执行完成")
    except Exception as exc:
        emit("run_finished", status="failed", message=str(exc))
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
