"""OpenCV template matching with screen-coordinate results and explicit ambiguity."""
import base64
import io
import math
import time
import cv2
import numpy as np
from PIL import Image, ImageGrab
import win32api


def template_image(asset):
    raw=base64.b64decode(asset['data_url'].split(',',1)[1])
    with Image.open(io.BytesIO(raw)) as image:
        return image.convert('RGB')


def match_image(source, template, origin=(0,0), threshold=.9, grayscale=False, multiscale=False, ambiguity='error'):
    from automation import Ambiguous
    source=np.asarray(source.convert('RGB'))
    template=np.asarray(template.convert('RGB'))
    if grayscale:
        source=cv2.cvtColor(source,cv2.COLOR_RGB2GRAY)
        template=cv2.cvtColor(template,cv2.COLOR_RGB2GRAY)
    if float(np.var(template.astype(np.float32),axis=(0,1)).sum())<1:
        raise ValueError('目标图片缺少可区分的纹理，请重新框选包含文字或图案的区域')
    candidates=[]
    for scale in ([.8,.9,1,1.1,1.25] if multiscale else [1]):
        w,h=round(template.shape[1]*scale),round(template.shape[0]*scale)
        if min(w,h)<2 or w>source.shape[1] or h>source.shape[0]:
            continue
        scaled=cv2.resize(template,(w,h),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
        scores=cv2.matchTemplate(source,scaled,cv2.TM_CCOEFF_NORMED)
        scores=np.nan_to_num(scores,nan=-1,posinf=-1,neginf=-1)
        for _ in range(2):
            _,score,_,location=cv2.minMaxLoc(scores)
            x,y=location
            candidates.append((float(score),x,y,w,h))
            scores[max(0,y-h+1):y+h,max(0,x-w+1):x+w]=-1
    candidates.sort(reverse=True)
    if not candidates:
        return {'found':False,'score':0.,'x':None,'y':None,'width':None,'height':None,'center':None}
    score,x,y,w,h=candidates[0]
    found=score>=threshold
    if found and ambiguity=='error':
        for other,ox,oy,ow,oh in candidates[1:]:
            overlap=max(0,min(x+w,ox+ow)-max(x,ox))*max(0,min(y+h,oy+oh)-max(y,oy))
            union=w*h+ow*oh-overlap
            if other>=threshold and overlap/union<.3:
                raise Ambiguous('找到多个高分图片目标，请缩小搜索范围或选择最高分匹配')
    x,y=x+origin[0],y+origin[1]
    return {'found':bool(found),'score':max(-1.,min(1.,score)), 'x':x if found else None,'y':y if found else None,
        'width':w if found else None,'height':h if found else None,'center':{'x':x+w//2,'y':y+h//2} if found else None}


def screenshot_region(params,context):
    origin=(win32api.GetSystemMetrics(76),win32api.GetSystemMetrics(77))
    screenshot=ImageGrab.grab(all_screens=True)
    if params['scope']=='screen':
        return screenshot,origin
    if params['scope']=='window':
        window=context.window(params['search_window'])
        if window.is_minimized() or not window.is_visible():
            raise ValueError('搜索窗口不可见或已最小化，请先还原并激活')
        rect=window.rectangle();x,y,w,h=rect.left,rect.top,rect.width(),rect.height()
    else:
        x,y,w,h=[params[k] for k in ('region_x','region_y','region_width','region_height')]
    left,top=max(origin[0],int(x)),max(origin[1],int(y))
    right,bottom=min(origin[0]+screenshot.width,int(x+w)),min(origin[1]+screenshot.height,int(y+h))
    if right<=left or bottom<=top:
        raise ValueError('搜索区域不在当前桌面范围内')
    return screenshot.crop((left-origin[0],top-origin[1],right-origin[0],bottom-origin[1])),(left,top)


def find_on_screen(asset,params,context):
    template=template_image(asset)
    deadline=time.monotonic()+params.get('timeout',3)
    while True:
        screenshot,origin=screenshot_region(params,context)
        result=match_image(screenshot,template,origin,params.get('threshold',.9),params.get('grayscale',False),
                           params.get('multiscale',False),params.get('ambiguity','error'))
        if result['found'] or time.monotonic()>=deadline:
            return result
        time.sleep(min(.2,max(0,deadline-time.monotonic())))
