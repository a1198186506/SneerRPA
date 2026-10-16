"""Windows selectors and action execution shared by worker and picker.

Saved selectors contain properties, never runtime HWNDs or Python objects.
"""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlparse

from pywinauto import Desktop
import win32gui
import win32api
from parameters import effective_params
from values import value_type, require_type, compare, REFERENCE
from runtime_resources import resolve_resource


class NotFound(ValueError):
    pass


class Ambiguous(ValueError):
    pass


def type_literal_text(text):
    """Send literal UTF-16 text, including surrogate pairs, without hotkey parsing."""
    class MouseInput(ctypes.Structure):
        _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('data', wintypes.DWORD),
                    ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]

    class KeyboardInput(ctypes.Structure):
        _fields_ = [('vk', wintypes.WORD), ('scan', wintypes.WORD), ('flags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]

    class HardwareInput(ctypes.Structure):
        _fields_ = [('message', wintypes.DWORD), ('low', wintypes.WORD), ('high', wintypes.WORD)]

    class Payload(ctypes.Union):
        _fields_ = [('mouse', MouseInput), ('keyboard', KeyboardInput), ('hardware', HardwareInput)]

    class Input(ctypes.Structure):
        _fields_ = [('type', wintypes.DWORD), ('payload', Payload)]

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    if text and not win32gui.GetForegroundWindow():
        raise ValueError('没有可接收键盘输入的前台窗口')
    inputs = []
    for char in text.replace('\r\n', '\n').replace('\r', '\n'):
        if char in ('\n', '\t'):
            codes, flags, vk = [0], 0, 0x0D if char == '\n' else 0x09
        else:
            encoded = char.encode('utf-16-le')
            codes, flags, vk = [int.from_bytes(encoded[i:i+2], 'little') for i in range(0,len(encoded),2)], 4, 0
        for code in codes:
            inputs.extend([Input(1, Payload(keyboard=KeyboardInput(vk, code, flags, 0, 0))),
                           Input(1, Payload(keyboard=KeyboardInput(vk, code, flags | 2, 0, 0)))])
    if not inputs:
        return
    # Cancel unfinished IME composition so literal text is not prefixed with old pinyin.
    class GuiThreadInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('flags', wintypes.DWORD),
                    *[(name, wintypes.HWND) for name in ('active','focus','capture','menu','move','caret')],
                    ('rect', wintypes.RECT)]
    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GuiThreadInfo)]
    imm32 = ctypes.WinDLL('imm32', use_last_error=True)
    imm32.ImmGetContext.argtypes = [wintypes.HWND]
    imm32.ImmGetContext.restype = wintypes.HANDLE
    imm32.ImmGetOpenStatus.argtypes = [wintypes.HANDLE]
    imm32.ImmSetOpenStatus.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    imm32.ImmNotifyIME.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
    imm32.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
    gui = GuiThreadInfo(size=ctypes.sizeof(GuiThreadInfo))
    context, was_open = None, False
    if user32.GetGUIThreadInfo(0, ctypes.byref(gui)) and gui.focus:
        context = imm32.ImmGetContext(gui.focus)
    try:
        if context:
            was_open = bool(imm32.ImmGetOpenStatus(context))
            imm32.ImmNotifyIME(context, 0x15, 4, 0)
            imm32.ImmSetOpenStatus(context, False)
        # Bounded batches keep long text interruptible and avoid large OS buffers.
        for offset in range(0, len(inputs), 64):
            batch = inputs[offset:offset+64]
            array = (Input * len(batch))(*batch)
            if user32.SendInput(len(batch), array, ctypes.sizeof(Input)) != len(batch):
                raise RuntimeError('键盘输入失败，请确认目标窗口可交互且权限匹配')
            time.sleep(0.01)
    finally:
        if context:
            imm32.ImmSetOpenStatus(context, was_open)
            imm32.ImmReleaseContext(gui.focus, context)


def process_name(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ''
    try:
        buffer, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name
        return ''
    finally:
        kernel.CloseHandle(handle)


def properties(control):
    info = control.element_info
    result = {'name': info.name or '', 'class_name': info.class_name or ''}
    for key in ('automation_id', 'control_type', 'control_id'):
        value = getattr(info, key, None)
        if value not in (None, '', 0):
            result[key] = value
    return result


def matches(control, criteria):
    props = properties(control)
    return all(props.get(key) == value for key, value in criteria.items())


def unique(items, label):
    if not items:
        raise NotFound(f'未找到{label}')
    if len(items) != 1:
        raise Ambiguous(f'{label}匹配到 {len(items)} 个对象，请补充定位属性')
    return items[0]


def find_window(selector):
    backend = selector.get('backend', 'uia')
    if backend not in ('uia', 'win32'):
        raise ValueError('不支持的自动化后端')
    title, match = selector.get('title', ''), selector.get('match', 'exact')
    if not any(selector.get(k) for k in ('title', 'class_name', 'process_name', 'process_id')):
        raise ValueError('至少填写窗口标题、类名或进程名之一')
    if match not in ('exact', 'contains', 'regex'):
        raise ValueError('无效的标题匹配方式')
    regex = re.compile(title) if match == 'regex' else None
    candidates = []
    criteria = {'visible_only': False}
    if selector.get('process_id'):
        criteria['process'] = int(selector['process_id'])
    for control in Desktop(backend=backend).windows(**criteria):
        try:
            name = control.window_text()
            if title and not (name == title if match == 'exact' else title in name if match == 'contains' else regex.search(name)):
                continue
            if selector.get('class_name') and control.class_name() != selector['class_name']:
                continue
            if selector.get('process_name') and process_name(control.process_id()).lower() != selector['process_name'].lower():
                continue
            candidates.append(control)
        except (NotFound, Ambiguous):
            raise
        except Exception:
            continue  # Window may have disappeared during enumeration.
    return unique(candidates, '窗口')


def find_element(selector, window=None):
    root = window if window is not None else find_window(selector['window'])
    if selector.get('criteria'):
        return unique([c for c in root.descendants() if matches(c, selector['criteria'])], '元素')
    current = root
    for level in selector.get('path', []):
        candidates = [c for c in current.children() if matches(c, level['criteria'])]
        # Do not silently choose an ordinal among identical siblings.
        current = unique(candidates, '元素层级')
    return current


def capture(control, backend='uia'):
    root = control.top_level_parent()
    if not root.handle:
        raise ValueError('无法获取所属窗口，请选择普通桌面软件控件')
    path = []
    current = control
    for _ in range(40):
        if current == root:
            break
        props = properties(current)
        if backend == 'uia':
            props.pop('control_id', None)  # UIA control_id can be a runtime HWND/hash.
        # AutomationId is usually more stable than the input's current text.
        if props.get('automation_id'):
            props.pop('name', None)
        if props.get('control_type'):
            props.pop('class_name', None)
        if not any(props.values()):
            raise ValueError('元素缺少可用定位属性')
        parent = current.parent()
        unique([c for c in parent.children() if matches(c, props)], '捕获元素（同级）')
        path.insert(0, {'criteria': props})
        current = parent
    else:
        raise ValueError('元素层级过深')
    root_class = root.class_name()
    if root_class.startswith('WindowsForms10.'):
        root_class = ''  # WinForms app-domain suffix changes on every launch.
    return {'backend': backend, 'window': {'backend': backend, 'title': root.window_text(),
        'match': 'exact', 'class_name': root_class, 'process_name': process_name(root.process_id())},
        'path': path}


def retry(find, timeout):
    deadline = time.monotonic() + float(timeout)
    while True:
        try:
            return find()
        except NotFound:
            if time.monotonic() >= deadline:
                raise
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))


def value_of(control):
    if hasattr(control, 'get_value'):
        return control.get_value()
    if hasattr(control, 'iface_value'):
        return control.iface_value.CurrentValue
    raise ValueError('此控件未提供可读的 Value 接口，请改用文本或属性')


def read_info(control, kind):
    if kind == 'text':
        return control.window_text()
    if kind == 'value':
        return value_of(control)
    rect = control.rectangle()
    rectangle = {'left': rect.left, 'top': rect.top, 'width': rect.width(), 'height': rect.height()}
    if kind == 'rectangle':
        return rectangle
    if kind == 'properties':
        return {**properties(control), 'rectangle': rectangle, 'visible': control.is_visible(), 'enabled': control.is_enabled()}
    raise ValueError('无效的读取内容')


class Context:
    def __init__(self, flow, emit):
        self.elements = {e['id']: e for e in flow.get('elements', [])}
        self.variables = {}
        self.variable_types = {}
        self.images = {image['id']:image for image in flow.get('images',[])}
        self.launched_processes = []
        self.emit = emit

    def interpolate(self, value):
        if not isinstance(value, str):
            return value
        def replace(match):
            name = match.group(1)
            v = self.reference(name)
            if hasattr(v, 'element_info'):
                return f'<窗口 {v.window_text()}>'
            return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list, bool)) else str(v)
        return re.sub(r'\$\{([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\}', replace, value)

    def reference(self,name):
        if not isinstance(name,str) or not REFERENCE.fullmatch(name):
            raise ValueError('变量引用格式无效')
        parts=name.split('.')
        if parts[0] not in self.variables:
            raise ValueError(f'变量尚未定义或所在分支未执行：{name}')
        result=self.variables[parts[0]]
        for key in parts[1:]:
            if not isinstance(result,dict) or key not in result:
                raise ValueError(f'变量字段不存在或找图未成功：{name}')
            result=result[key]
        return result

    def store(self, name, value, type_hint=None):
        if name:
            kind=type_hint or value_type(value)
            if name in self.variable_types and self.variable_types[name]!=kind:
                raise ValueError(f'同名变量不能改变类型：{name}（{self.variable_types[name]} → {kind}）')
            self.variable_types[name]=kind
            self.variables[name] = value
            display = f'<窗口 {value.window_text()}>' if hasattr(value, 'element_info') else value
            self.emit('variable', name=name, value=display, value_type=kind)

    def window(self, name):
        window=self.reference(name)
        if not hasattr(window, 'element_info'):
            raise ValueError(f'窗口变量不存在：{name}，请先获取窗口对象')
        if not win32gui.IsWindow(window.handle):
            raise NotFound('窗口已关闭或失效，请重新获取窗口对象')
        return window

    def element(self, params):
        entry = self.elements.get(params.get('element'))
        if not entry:
            raise ValueError('目标元素未配置或不在元素库中')
        selector = entry['selector']
        window = self.window(params['window']) if params.get('window') else None
        if window is not None and window.backend.name != selector.get('backend', 'uia'):
            raise ValueError('窗口变量后端与元素后端不一致')
        return find_element(selector, window)

    def target_window(self, params):
        mode = params['target_mode']
        if mode == 'variable':
            return self.window(params['window'])
        if mode == 'element':
            entry = self.elements.get(params.get('element'))
            if not entry:
                raise ValueError('请从元素库选择用于定位所属窗口的元素')
            # The child itself may have disappeared. Only its owning window matters.
            return find_window(entry['selector']['window'])
        if mode == 'criteria':
            for process in self.launched_processes:
                if str(process.pid)==str(params.get('process_id')):
                    code=process.poll()
                    if code not in (None,0):raise ValueError(f'启动的程序已提前退出（退出码 {code}），请检查程序路径、脚本路径和启动参数')
            return find_window(params)
        raise ValueError('无效的窗口目标获取方式')

    def action(self, kind, params):
        raw=effective_params(kind,params)
        p = raw if kind in ('variable.set','control.if') else {k: self.interpolate(v) for k, v in raw.items()}
        timeout = float(p.get('timeout', 10))
        if kind=='variable.set':
            expected=p['value_type']
            if p['source']=='reference':
                value=self.reference(p['source_variable'])
            elif p['source']=='window':
                value=retry(lambda:self.target_window({k:self.interpolate(v) for k,v in p.items()}),timeout)
            else:
                value=p[{'bool':'value_boolean','string':'value_text','number':'value_number'}[expected]]
            self.store(p['output'],require_type(value,expected),expected)
        elif kind=='window.exists':
            deadline=time.monotonic()+timeout
            while True:
                try:
                    self.target_window(p);exists=True
                except NotFound:
                    exists=False
                if exists or time.monotonic()>=deadline:
                    break
                time.sleep(.15)
            self.store(p['output'],exists)
        elif kind=='image.find':
            from vision import find_on_screen
            asset=self.images.get(p['image'])
            if not asset:
                raise ValueError('请从图片素材库选择目标图片')
            result=find_on_screen(asset,p,self)
            self.store(p['output'],result,'match')
        elif kind == 'keyboard.input':
            type_literal_text(p['text'])
        elif kind == 'mouse.click':
            button = p['button']
            if p['target_mode'] == 'element':
                control = retry(lambda: self.element(p), timeout)
                if not control.is_visible() or not control.is_enabled():
                    raise ValueError('元素不可见或不可用')
                control.top_level_parent().set_focus()
                control.click_input(button='right' if button == 'right' else 'left', double=button == 'double')
            else:
                position=self.reference(p['position']) if p['target_mode']=='position' else {'x':p['x'],'y':p['y']}
                if not isinstance(position,dict) or any(type(position.get(key)) not in (int,float) for key in ('x','y')):
                    raise ValueError('点击位置无效，目标图片可能未找到')
                point = (int(position['x']), int(position['y']))
                if any(position[key] != int(position[key]) for key in ('x','y')):
                    raise ValueError('屏幕坐标必须是整数')
                if not any(r[0] <= point[0] < r[2] and r[1] <= point[1] < r[3] for _, _, r in win32api.EnumDisplayMonitors()):
                    raise ValueError('点击坐标不在当前显示器范围内，请重新捕获')
                from pywinauto import mouse
                if button == 'double':
                    mouse.double_click(coords=point)
                else:
                    mouse.click(button=button, coords=point)
        elif kind == 'app.launch':
            args = p.get('args', [])
            if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
                raise ValueError('程序参数必须是字符串 JSON 数组')
            args = [resolve_resource(self.interpolate(x)) for x in args]
            p['path']=resolve_resource(p['path'])
            target = Path(p['path'])
            if urlparse(p['path']).scheme in ('http', 'https') or (target.is_file() and target.suffix.lower() not in ('.exe', '.com')):
                from win32com.shell import shell, shellcon
                import win32process
                result = shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_NOCLOSEPROCESS, lpVerb='open', lpFile=p['path'],
                    lpParameters=subprocess.list2cmdline(args), nShow=1)
                handle = result.get('hProcess')
                try:
                    pid = win32process.GetProcessId(handle) if handle else None
                finally:
                    if handle:
                        handle.Close()
                self.store(p.get('output'), pid)
            else:
                process = subprocess.Popen([p['path'], *args],
                    cwd=str(Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent), creationflags=subprocess.CREATE_NO_WINDOW,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.launched_processes.append(process)
                self.store(p.get('output'), process.pid)
        elif kind == 'window.get':
            self.store(p['output'], retry(lambda: self.target_window(p), timeout))
        elif kind == 'window.activate':
            window = retry(lambda: self.target_window(p), timeout)
            if window.is_minimized():
                window.restore()
            window.set_focus()
        elif kind == 'window.state':
            window = retry(lambda: self.target_window(p), timeout)
            getattr(window, {'restore': 'restore', 'maximize': 'maximize', 'minimize': 'minimize'}[p['state']])()
        elif kind == 'window.close':
            retry(lambda: self.target_window(p), timeout).close()
        elif kind == 'element.wait':
            deadline = time.monotonic() + timeout
            while True:
                try:
                    visible = self.element(p).is_visible()
                except NotFound:
                    visible = False
                success = visible if p['state'] == 'appear' else not visible
                if success or time.monotonic() >= deadline:
                    break
                time.sleep(0.15)
            self.store(p.get('output'), success)
            if not success and p.get('fail_on_timeout', True):
                raise TimeoutError(f'等待元素{p["state"]}超时（{timeout:g} 秒）')
        elif kind in ('element.click', 'element.input', 'element.read'):
            control = retry(lambda: self.element(p), timeout)
            if kind == 'element.read':
                self.store(p['output'], read_info(control, p['info']))
            elif kind == 'element.click':
                if not control.is_visible() or not control.is_enabled():
                    raise ValueError('元素不可见或不可用')
                button = p.get('button', 'left')
                if p.get('method') == 'input' or button != 'left':
                    control.top_level_parent().set_focus()
                    control.click_input(button='right' if button == 'right' else 'left', double=button == 'double')
                elif hasattr(control, 'invoke') and control.backend.name == 'uia':
                    control.invoke()
                elif hasattr(control, 'click'):
                    control.click()
                else:
                    raise ValueError('控件没有点击接口，请选择真实鼠标方式')
            else:
                text = str(p.get('text', ''))
                if p.get('method') == 'input':
                    control.top_level_parent().set_focus()
                    control.set_focus()
                    if p.get('clear', True):
                        control.type_keys('^a{BACKSPACE}')
                    escaped = ''.join('{' + c + '}' if c in '{}+^%~()' else '{ENTER}' if c == '\n' else c for c in text)
                    control.type_keys(escaped, with_spaces=True, with_tabs=True, vk_packet=True)
                else:
                    if not p.get('clear', True):
                        text = str(value_of(control)) + text
                    if hasattr(control, 'set_edit_text'):
                        control.set_edit_text(text)
                    elif hasattr(control, 'set_text'):
                        control.set_text(text)
                    else:
                        raise ValueError('控件没有文本写入接口，请选择真实键盘方式')
        else:
            raise ValueError(f'不支持的动作：{kind}')

    def condition(self,params):
        p=effective_params('control.if',params)
        left=self.reference(p['left'])
        right=self.reference(p['right_reference']) if p['right_source']=='reference' else p[{'bool':'right_boolean','string':'right_text','number':'right_number'}[p['right_type']]]
        return compare(left,p['operator'],right)
