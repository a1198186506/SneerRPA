import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'extensions'))
from automation import Context, Ambiguous, NotFound
from validation import validate_flow
from values import compare
from vision import match_image, find_on_screen
from image_assets import encode_crop
import worker


def node(identifier, kind, **params):
    return {'id': identifier, 'name': identifier, 'type': kind, 'params': params}


def flow(*steps):
    return {'schema_version': 1, 'name': 'logic test', 'steps': list(steps), 'elements': [], 'images': []}


def number(name, value):
    return node(name, 'variable.set', output=name, value_type='number', source='literal', value_number=value)


class Logic(unittest.TestCase):
    def test_nested_branches_execute_and_report_skipped(self):
        inner=node('inner','control.if',left='count',operator='>=',right_source='reference',right_reference='limit')
        inner['then_steps']=[node('hit','log',message='count=${count}')]
        inner['else_steps']=[node('miss','log',message='wrong')]
        outer=node('outer','control.if',left='enabled',right_type='bool',right_boolean=True)
        outer['then_steps']=[inner]
        outer['else_steps']=[node('skip','variable.set',output='untouched',value_type='string',value_text='no')]
        f=flow(number('count',5),number('limit',3),node('enabled','variable.set',output='enabled',value_type='bool',value_boolean=True),outer)
        validate_flow(f)
        events=[]
        with patch.object(worker,'emit',side_effect=lambda event,**data:events.append((event,data))):
            context=Context(f,lambda *args,**kwargs:None)
            worker.execute_steps(f['steps'],context)
        self.assertNotIn('untouched',context.variables)
        self.assertEqual({d['node_id'] for e,d in events if e=='node_skipped'},{'skip','miss'})
        self.assertIn(('log',{'node_id':'hit','message':'count=5'}),events)
        context.variables['enabled']=False
        with patch.object(worker,'emit'):
            worker.execute_steps([outer],context)
        self.assertEqual(context.variables['untouched'],'no')

    def test_boolean_number_and_ordering_are_strict(self):
        for left,op,right in [(True,'==',1),('3','>=','2'),(True,'<=',False)]:
            with self.assertRaises(ValueError):compare(left,op,right)
        self.assertTrue(compare(3,'>=',3.0))
        self.assertFalse(compare('hello','!=','hello'))

    def test_definite_assignment_and_same_name_types(self):
        condition=node('if','control.if',left='count',right_type='number',right_number=1)
        condition['then_steps']=[number('branch_value',2)]
        condition['else_steps']=[]
        read=node('copy','variable.set',output='copy',value_type='number',source='reference',source_variable='branch_value')
        f=flow(number('count',1),condition,read)
        with self.assertRaisesRegex(ValueError,'所有分支'):validate_flow(f)
        condition['else_steps']=[{**number('branch_value',4),'id':'else_value'}]
        validate_flow(f)
        f['steps'].append(node('change','variable.set',output='count',value_type='string',value_text='oops'))
        with self.assertRaisesRegex(ValueError,'改变类型'):validate_flow(f)

    def test_reference_and_literal_keep_types_and_text(self):
        f=flow();c=Context(f,lambda *args,**kwargs:None)
        c.action('variable.set',{'output':'text','value_type':'string','value_text':'${literal} 中文'})
        c.action('variable.set',{'output':'copy','value_type':'string','source':'reference','source_variable':'text'})
        self.assertEqual(c.variables['copy'],'${literal} 中文')
        c.store('match',{'found':False,'center':None},'match')
        self.assertEqual(c.interpolate('${match.found}'),'false')
        with self.assertRaises(ValueError):c.reference('match.center.x')
        with self.assertRaises(ValueError):c.action('mouse.click',{'target_mode':'position','position':'match.center'})
        with self.assertRaises(ValueError):c.action('variable.set',{'output':'copy','value_type':'bool','value_boolean':False})

    def test_window_exists_distinguishes_absence_from_errors(self):
        c=Context(flow(),lambda *args,**kwargs:None)
        params={'target_mode':'criteria','title':'absent','timeout':0,'output':'present'}
        with patch.object(c,'target_window',side_effect=NotFound('missing')):
            c.action('window.exists',params)
            self.assertIs(c.variables['present'],False)
        with patch.object(c,'target_window',return_value=object()):
            c.action('window.exists',params)
            self.assertIs(c.variables['present'],True)
        with patch.object(c,'target_window',side_effect=Ambiguous('multiple')):
            with self.assertRaises(Ambiguous):c.action('window.exists',params)

    def test_duplicate_nested_ids_and_invalid_reference_rejected(self):
        f=flow(number('n',1),node('if','control.if',left='n',right_type='number'))
        f['steps'][1]['then_steps']=[number('n',2)]
        with self.assertRaisesRegex(ValueError,'重复'):validate_flow(f)
        f['steps'][1]['then_steps']=[]
        f['steps'][1]['params']['left']='n.__class__'
        with self.assertRaisesRegex(ValueError,'尚未定义'):validate_flow(f)


class Vision(unittest.TestCase):
    def setUp(self):
        self.pixels=np.random.default_rng(42).integers(0,256,(24,30,3),dtype=np.uint8)
        self.template=Image.fromarray(self.pixels)
        self.source=Image.new('RGB',(200,120),'white');self.source.paste(self.template,(42,31))

    def test_exact_match_and_negative_desktop_origin(self):
        r=match_image(self.source,self.template,(-100,-80),.99)
        self.assertTrue(r['found']);self.assertGreater(r['score'],.999)
        self.assertEqual((r['x'],r['y']),(-58,-49))
        self.assertEqual(r['center'],{'x':-43,'y':-37})

    def test_multiple_matches_and_best_override(self):
        self.source.paste(self.template,(140,70))
        with self.assertRaises(Ambiguous):match_image(self.source,self.template)
        self.assertTrue(match_image(self.source,self.template,ambiguity='best')['found'])

    def test_no_match_and_template_larger_than_region(self):
        for source in (Image.new('RGB',(200,120),'white'),Image.new('RGB',(5,5),'white')):
            result=match_image(source,self.template)
            self.assertIs(result['found'],False);self.assertIsNone(result['center'])
        with self.assertRaisesRegex(ValueError,'纹理'):match_image(self.source,Image.new('RGB',(20,20),'red'))

    def test_multiscale_and_grayscale(self):
        source=Image.new('RGB',(200,120),'white')
        scaled=Image.fromarray(cv2.resize(self.pixels,(round(30*1.25),round(24*1.25)),interpolation=cv2.INTER_LINEAR))
        source.paste(scaled,(80,60))
        self.assertFalse(match_image(source,self.template,threshold=.99)['found'])
        result=match_image(source,self.template,threshold=.99,multiscale=True,grayscale=True)
        self.assertEqual(result['center'],{'x':99,'y':75})

    def test_retry_can_succeed_and_timeout_returns_false(self):
        asset=encode_crop(self.template,(0,0,30,24))
        empty=Image.new('RGB',(200,120),'white')
        with patch('vision.screenshot_region',side_effect=[(empty,(0,0)),(self.source,(0,0))]):
            self.assertTrue(find_on_screen(asset,{'timeout':1},None)['found'])
        with patch('vision.screenshot_region',return_value=(empty,(0,0))):
            self.assertFalse(find_on_screen(asset,{'timeout':0},None)['found'])


if __name__=='__main__':unittest.main()
