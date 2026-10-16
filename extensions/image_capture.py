"""Freeze the virtual desktop, then select a region without capturing the overlay."""
import time
import tkinter as tk
import win32api
import win32con
import win32gui
from PIL import ImageGrab, ImageTk
from image_assets import encode_crop


def pick_image():
    origin = (win32api.GetSystemMetrics(76), win32api.GetSystemMetrics(77))
    screenshot = ImageGrab.grab(all_screens=True)
    root = tk.Tk()
    root.title('SneerRPA 图片拾取')
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.geometry(f'{screenshot.width}x{screenshot.height}+0+0')
    canvas = tk.Canvas(root, width=screenshot.width, height=screenshot.height, highlightthickness=0, cursor='crosshair')
    canvas.pack(fill='both', expand=True)
    frozen = ImageTk.PhotoImage(screenshot)
    canvas.create_image(0, 0, image=frozen, anchor='nw')
    # Put help on the primary monitor even if the virtual desktop starts at negative X/Y.
    hx, hy = 20-origin[0], 20-origin[1]
    canvas.create_rectangle(hx,hy,hx+570,hy+60,fill='#6558e8',outline='')
    help_text = canvas.create_text(hx+18,hy+30,text='拖动框选图片 · 松开鼠标确认 · Esc 取消',fill='white',anchor='w',font=('Microsoft YaHei UI',13))
    selection = canvas.create_rectangle(0,0,0,0,outline='#6558e8',width=3)
    root.update()
    handle = win32gui.GetParent(root.winfo_id()) or root.winfo_id()
    # Tk negative geometry means distance from the right edge; Win32 uses absolute coordinates.
    win32gui.SetWindowPos(handle, win32con.HWND_TOPMOST, origin[0], origin[1], screenshot.width, screenshot.height, win32con.SWP_SHOWWINDOW)
    root.update()
    start, result, failure = [], [], []
    deadline = time.monotonic()+60

    def point():
        x,y = win32api.GetCursorPos()
        return (min(screenshot.width,max(0,x-origin[0])), min(screenshot.height,max(0,y-origin[1])))

    def begin(_event):
        start[:] = point()
        canvas.coords(selection,*start,*start)
        canvas.grab_set()

    def drag(_event):
        if not start:
            return
        x,y = point()
        canvas.coords(selection,start[0],start[1],x,y)
        canvas.itemconfig(help_text,text=f'已框选 {abs(x-start[0])} × {abs(y-start[1])} 像素 · 松开确认 · Esc 取消')

    def finish(_event):
        if not start:
            return
        x,y = point()
        canvas.grab_release()
        left,right = sorted((start[0],x))
        top,bottom = sorted((start[1],y))
        try:
            result.append(encode_crop(screenshot,(left,top,right,bottom),origin))
            root.quit()
        except ValueError as exc:
            canvas.itemconfig(help_text,text=str(exc)+' · 重新拖动框选 · Esc 取消')
            start.clear()

    def poll():
        if win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000:
            failure.append(InterruptedError('已取消图片拾取'))
        elif time.monotonic()>=deadline:
            failure.append(TimeoutError('图片拾取超时（60 秒）'))
        if failure:
            root.quit()
        else:
            root.after(50,poll)

    canvas.bind('<ButtonPress-1>',begin)
    canvas.bind('<B1-Motion>',drag)
    canvas.bind('<ButtonRelease-1>',finish)
    try:
        root.after(50,poll)
        root.mainloop()
        if failure:
            raise failure[0]
        if not result:
            raise InterruptedError('已取消图片拾取')
        return result[0]
    finally:
        root.destroy()
