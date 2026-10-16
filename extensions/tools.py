"""Short-lived automation helpers. Isolates UIA and picker from the message loop."""
import json
import os
import sys
import time
import uuid

from automation import Desktop, capture, find_element, read_info, process_name
from validation import validate_selector


def pick_coordinates():
    import tkinter as tk
    import win32api
    import win32con
    import win32gui
    root = tk.Tk()
    root.title('SneerRPA 坐标捕获')
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.geometry('550x66+20+20')
    label = tk.Label(root, bg='#6558e8', fg='white', font=('Microsoft YaHei UI', 12), padx=16, pady=8)
    label.pack(fill='both', expand=True)
    root.update()
    handle = win32gui.GetParent(root.winfo_id()) or root.winfo_id()
    style = win32gui.GetWindowLong(handle, win32con.GWL_EXSTYLE)
    win32gui.SetWindowLong(handle, win32con.GWL_EXSTYLE, style | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_LAYERED)
    win32gui.SetLayeredWindowAttributes(handle, 0, 255, win32con.LWA_ALPHA)
    deadline = time.monotonic() + 60
    result, failure = [], []
    held = bool(win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000)

    def poll():
        nonlocal held
        if win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000:
            failure.append(InterruptedError('已取消坐标捕获'))
        elif time.monotonic() >= deadline:
            failure.append(TimeoutError('坐标捕获超时（60 秒）'))
        if failure:
            root.quit()
            return
        x, y = win32api.GetCursorPos()
        label.config(text=f'当前屏幕坐标：X = {x}   Y = {y}\n移动鼠标到目标位置 · F8 捕获 · Esc 取消')
        pressed = bool(win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000)
        if pressed and not held:
            result.append({'x': x, 'y': y})
            root.quit()
            return
        held = pressed
        root.after(40, poll)

    try:
        root.after(80, poll)
        root.mainloop()
        if failure:
            raise failure[0]
        if not result:
            raise InterruptedError('已取消坐标捕获')
        return result[0]
    finally:
        root.destroy()


def pick_element(backend='uia'):
    import tkinter as tk
    import win32api
    import win32con
    import win32gui
    root = tk.Tk()
    root.title('SneerRPA 元素拾取')
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.geometry('510x48+20+20')
    tk.Label(root, text='移动鼠标到控件 · F8 捕获 · Esc 取消', bg='#6558e8', fg='white',
             font=('Microsoft YaHei UI', 13), padx=16, pady=12).pack(fill='both', expand=True)
    borders = []
    for _ in range(4):
        bar = tk.Toplevel(root)
        bar.overrideredirect(True)
        bar.attributes('-topmost', True)
        bar.configure(bg='#6558e8')
        bar.withdraw()
        borders.append(bar)
    root.update()
    for widget in [root, *borders]:
        handle = win32gui.GetParent(widget.winfo_id()) or widget.winfo_id()
        style = win32gui.GetWindowLong(handle, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(handle, win32con.GWL_EXSTYLE, style | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_LAYERED)
        win32gui.SetLayeredWindowAttributes(handle, 0, 255, win32con.LWA_ALPHA)
    desktop = Desktop(backend=backend)
    deadline = time.monotonic() + 60
    result, failure = [], []
    last_point = None
    target = None
    # Release a previously held F8 first, then respond to its next press.
    held = bool(win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000)

    def poll():
        nonlocal last_point, target, held
        try:
            if win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000:
                raise InterruptedError('已取消元素拾取')
            if time.monotonic() >= deadline:
                raise TimeoutError('元素拾取超时（60 秒）')
            point = win32api.GetCursorPos()
            pressed = bool(win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000)
            if point != last_point or pressed:
                target = desktop.from_point(*point)
                last_point = point
                if target.process_id() == os.getpid():
                    target = None
                if target:
                    r = target.rectangle()
                    geometries = [(r.left, r.top, r.width(), 3), (r.left, r.bottom-3, r.width(), 3),
                                  (r.left, r.top, 3, r.height()), (r.right-3, r.top, 3, r.height())]
                    for bar, (x, y, w, h) in zip(borders, geometries):
                        bar.geometry(f'{max(1,w)}x{max(1,h)}{x:+d}{y:+d}')
                        bar.deiconify()
            if pressed and not held and target:
                selector = capture(target, backend)
                result.append({'id': str(uuid.uuid4()), 'name': target.window_text() or target.friendly_class_name(), 'selector': selector})
                root.quit()
                return
            held = pressed
        except (InterruptedError, TimeoutError) as exc:
            failure.append(exc)
            root.quit()
            return
        except Exception as exc:
            # A control can disappear under the pointer; keep picking until timeout.
            root.title(str(exc))
            held = bool(win32api.GetAsyncKeyState(win32con.VK_F8) & 0x8000)
            if held:
                failure.append(exc)
                root.quit()
                return
        root.after(80, poll)

    try:
        root.after(100, poll)
        root.mainloop()
        if failure:
            raise failure[0]
        if not result:
            raise InterruptedError('拾取窗口已关闭')
        return result[0]
    finally:
        root.destroy()


def execute(request):
    operation = request['operation']
    if operation=='test_image':
        from automation import Context
        from parameters import effective_params
        from validation import validate_flow,walk_steps
        from vision import find_on_screen
        flow=validate_flow(request['flow'],allow_empty=True,draft=True)
        validate_flow({**flow,'steps':[{'id':'test-image','name':'测试找图','type':'image.find','params':request['params']}]},check_references=False)
        params=effective_params('image.find',request['params'])
        params['timeout']=min(params.get('timeout',3),5)
        context=Context(flow,lambda *args,**kwargs:None)
        if params['scope']=='window':
            name=params['search_window']
            declaration=next((s for s in walk_steps(flow['steps']) if s['type'] in ('window.get','variable.set') and s['params'].get('output')==name),None)
            if not declaration:
                raise ValueError('窗口变量尚不可用于单步测试，请先配置获取窗口或改用全屏/区域测试')
            context.action(declaration['type'],declaration['params'])
        asset=context.images.get(params['image'])
        if not asset:raise ValueError('请先选择目标图片')
        result=find_on_screen(asset,params,context)
        if result['found']:
            import win32gui
            dc=win32gui.GetDC(0)
            rect=(result['x'],result['y'],result['x']+result['width'],result['y']+result['height'])
            try:
                win32gui.DrawFocusRect(dc,rect);time.sleep(.5);win32gui.DrawFocusRect(dc,rect)
            finally:win32gui.ReleaseDC(0,dc)
        return result
    if operation == 'pick_image':
        from image_capture import pick_image
        return pick_image()
    if operation == 'pick_coordinates':
        return pick_coordinates()
    if operation == 'pick_element':
        backend = request.get('backend', 'uia')
        if backend not in ('uia', 'win32'):
            raise ValueError('不支持的拾取后端')
        return pick_element(backend)
    if operation == 'test_element':
        selector = request['selector']
        validate_selector(selector)
        control = find_element(selector)
        info = read_info(control, 'properties')
        control.draw_outline(colour=0xE85865, thickness=3)
        time.sleep(0.5)
        # Invalidate the screen so the outline is repainted away.
        import win32gui
        win32gui.RedrawWindow(0, None, None, 0x0085)
        return info
    if operation == 'list_windows':
        backend = request.get('backend', 'uia')
        result = []
        for window in Desktop(backend=backend).windows():
            try:
                title = window.window_text()
                if title:
                    result.append({'title': title, 'class_name': window.class_name(), 'process_name': process_name(window.process_id()), 'backend': backend})
            except Exception:
                continue
        return result
    raise ValueError('未知工具命令')


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        result = execute(json.loads(sys.stdin.readline()))
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False), flush=True)
    except Exception as exc:
        print(json.dumps({'ok': False, 'message': str(exc)}, ensure_ascii=False), flush=True)
        sys.exit(1)
