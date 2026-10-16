"""Drive only our named test window, to exercise the actual F8 picker in smoke tests."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'extensions'))
from automation import capture, find_window, find_element
from pywinauto import mouse, keyboard

operation = sys.argv[1]
if operation in ('point','image-region'):
    import win32gui
    titles=('SneerRPA 图片拾取',) if operation=='image-region' else ('SneerRPA 元素拾取','SneerRPA 坐标捕获')
    deadline=time.monotonic()+12
    while not any(win32gui.IsWindowVisible(win32gui.FindWindow(None,title)) for title in titles):
        if time.monotonic()>deadline:
            raise TimeoutError('Picker window did not become ready')
        time.sleep(.1)
    time.sleep(.2)
window = find_window({'title': 'SneerRPA 节点测试台', 'backend': 'uia'})
selector = {'backend': 'uia', 'window': {'title': 'SneerRPA 节点测试台', 'backend': 'uia'},
            'criteria': {'name': '输入内容', 'control_type': 'Edit'}}
if operation == 'point':
    window.set_focus()
    element = find_element(selector)
    rect = element.rectangle()
    mouse.move(coords=(rect.left + rect.width() // 2, rect.top + rect.height() // 2))
    time.sleep(0.3)
    import win32api
    actual_point=win32api.GetCursorPos()
    keyboard.send_keys('{F8 down}')
    time.sleep(0.4)
    keyboard.send_keys('{F8 up}')
    print(json.dumps({'x': actual_point[0], 'y': actual_point[1]}))
elif operation == 'close':
    window.close()
elif operation == 'capture':
    print(json.dumps(capture(find_element(selector)), ensure_ascii=True))
elif operation == 'image-region':
    selector['criteria']={'name':'确认','control_type':'Button'}
    rect=find_element(selector).rectangle()
    first,last=(rect.left-4,rect.top-4),(rect.right+4,rect.bottom+4)
    if len(sys.argv)>2 and sys.argv[2]=='reverse':
        first,last=last,first
    mouse.move(coords=first)
    mouse.press(coords=first)
    time.sleep(.15)
    mouse.move(coords=((first[0]+last[0])//2,(first[1]+last[1])//2))
    time.sleep(.15)
    mouse.move(coords=last)
    time.sleep(.15)
    mouse.release(coords=last)
    print(json.dumps({'x':rect.left-4,'y':rect.top-4,'width':rect.width()+8,'height':rect.height()+8}))
elif operation == 'cancel-image':
    keyboard.send_keys('{ESC down}')
    time.sleep(.25)
    keyboard.send_keys('{ESC up}')
else:
    raise ValueError(operation)
