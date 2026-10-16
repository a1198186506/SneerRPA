"""Prepare a controlled desktop target and portable image for a frozen runner."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'extensions'))
from automation import find_window,find_element,NotFound
from PIL import ImageGrab
from image_assets import encode_crop


def main():
    subprocess.Popen(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'tools/test-window.ps1')],creationflags=subprocess.CREATE_NO_WINDOW)
    deadline=time.monotonic()+12
    while True:
        try:window=find_window({'backend':'uia','title':'SneerRPA 节点测试台'});break
        except NotFound:
            if time.monotonic()>deadline:raise
            time.sleep(.2)
    window.set_focus();time.sleep(.4)
    owner={'backend':'uia','title':'SneerRPA 节点测试台'}
    button=find_element({'backend':'uia','window':owner,'criteria':{'automation_id':'ConfirmButton','control_type':'Button'}},window)
    rect=button.rectangle();image=ImageGrab.grab(bbox=(rect.left-3,rect.top-3,rect.right+3,rect.bottom+3))
    asset=encode_crop(image,(0,0,image.width,image.height),(rect.left-3,rect.top-3))
    node=lambda id,kind,**params:{'id':id,'name':id,'type':kind,'params':params}
    loop=node('loop','control.loop',count_source='reference',count_variable='n',index_variable='i');loop['body_steps']=[node('loop-log','log',message='FROZEN_LOOP_${i}')]
    condition=node('image-if','control.if',left='match.found',right_type='bool',right_boolean=True)
    condition['then_steps']=[node('click','mouse.click',target_mode='position',position='match.center')];condition['else_steps']=[node('missing','log',message='FROZEN_IMAGE_MISSING')]
    flow={'schema_version':1,'name':'独立 EXE 验证','images':[asset],'elements':[
        {'id':'input','name':'输入','selector':{'backend':'uia','window':owner,'criteria':{'automation_id':'InputText','control_type':'Edit'}}},
        {'id':'result','name':'结果','selector':{'backend':'uia','window':owner,'criteria':{'automation_id':'ResultText','control_type':'Edit'}}}],
        'steps':[node('n','variable.set',output='n',value_type='number',value_number=3),loop,
            node('window','window.get',target_mode='criteria',title='SneerRPA 节点测试台',output='main_window'),
            node('activate','window.activate',target_mode='variable',window='main_window'),
            node('input','element.input',element='input',window='main_window',text='Frozen RPA 中文'),
            node('read-input','element.read',element='input',window='main_window',info='value',output='typed_value'),
            node('image','image.find',image=asset['id'],scope='window',search_window='main_window',threshold=.8,timeout=1,ambiguity='best',output='match'),condition,
            node('read','element.read',element='result',window='main_window',info='value',output='answer'),
            node('log','log',message='FROZEN_DONE ${answer}') ]}
    print(json.dumps(flow,ensure_ascii=True))


if __name__=='__main__':main()
