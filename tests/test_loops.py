import copy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_logic import node,flow,number
from automation import Context
from validation import validate_flow
import worker


def loop(identifier,count=3,body=None,**params):
    result=node(identifier,'control.loop',**{'count':count,'index_variable':identifier+'_index',**params})
    result['body_steps']=body or []
    return result


def run(f,validate=True):
    if validate:validate_flow(f)
    events=[]
    emit=lambda event,**data:events.append((event,data))
    context=Context(f,emit)
    with patch.object(worker,'emit',side_effect=emit):
        worker.execute_steps(f['steps'],context)
    return context,events


def messages(events):return [d['message'] for e,d in events if e=='log']


class Loops(unittest.TestCase):
    def test_literal_zero_and_integer_float_counts(self):
        for count in (0,3,3.0):
            with self.subTest(count=count):
                f=flow(loop('repeat',count,[node('log','log',message='${repeat_index}')]),node('after','log',message='after'))
                c,events=run(f)
                self.assertEqual(messages(events),[str(i) for i in range(1,int(count)+1)]+['after'])
                if not count:
                    self.assertNotIn('repeat_index',c.variables)
                    self.assertIn(('node_skipped',{'node_id':'log','message':'分支未执行'}),events)

    def test_variable_snapshot_does_not_change_mid_loop(self):
        f=flow(number('count',3),loop('repeat',body=[node('log','log',message='${repeat_index}'),{**number('count',0),'id':'update'}],count_source='reference',count_variable='count'))
        c,events=run(f)
        self.assertEqual(messages(events),['1','2','3']);self.assertEqual(c.variables['count'],0)

    def test_number_only_references_and_invalid_values(self):
        for typ,key,value in [('string','value_text','3'),('bool','value_boolean',True)]:
            f=flow(node('set','variable.set',output='n',value_type=typ,**{key:value}),loop('repeat',count_source='reference',count_variable='n'))
            with self.assertRaisesRegex(ValueError,'类型不适用'):validate_flow(f)
        for value in (-1,1.5,1001):
            f=flow(number('n',value),loop('repeat',body=[node('unreached','log',message='wrong')],count_source='reference',count_variable='n'))
            validate_flow(f)
            with self.assertRaises(ValueError):run(f)
        for value in (True,float('inf'),float('nan')):
            c=Context(flow(),lambda *args,**kwargs:None);c.variables['n']=value
            with self.assertRaises(ValueError):worker.execute_loop(loop('repeat'),{'count_source':'reference','count_variable':'n','max_iterations':1000,'index_variable':'i'},c)

    def test_literal_preflight_and_inactive_fields(self):
        for count in (-1,1.1,True,10001):
            with self.assertRaises(ValueError):validate_flow(flow(loop('repeat',count)))
        with self.assertRaisesRegex(ValueError,'上限'):validate_flow(flow(loop('repeat',4,max_iterations=3)))
        validate_flow(flow(loop('repeat',10000,max_iterations=10000)))
        validate_flow(flow(number('count',2),loop('repeat',-3,count_source='reference',count_variable='count')))

    def test_break_inside_if_skips_body_tail_and_runs_after_loop(self):
        condition=node('if','control.if',left='repeat_index',operator='>=',right_type='number',right_number=2)
        condition['then_steps']=[node('break','control.break'),node('if-tail','log',message='wrong')]
        f=flow(loop('repeat',5,[node('start','log',message='${repeat_index}'),condition,node('tail','log',message='tail')]),node('after','log',message='after'))
        _,events=run(f)
        self.assertEqual(messages(events),['1','tail','2','after'])
        self.assertFalse(any(e=='node_failed' for e,d in events))

    def test_continue_inside_if_skips_tail_but_repeats(self):
        condition=node('if','control.if',left='repeat_index',operator='<=',right_type='number',right_number=2)
        condition['then_steps']=[node('continue','control.continue')]
        _,events=run(flow(loop('repeat',3,[node('start','log',message='${repeat_index}'),condition,node('tail','log',message='tail')])) )
        self.assertEqual(messages(events),['1','2','3','tail'])
        self.assertFalse(any(e=='node_failed' for e,d in events))

    def test_nested_break_and_continue_target_innermost_loop(self):
        inner=loop('inner',3,[node('inner-log','log',message='inner ${outer_index}/${inner_index}'),node('break','control.break'),node('dead','log',message='wrong')])
        _,events=run(flow(loop('outer',2,[inner,node('outer-log','log',message='outer ${outer_index}')])) )
        self.assertEqual(messages(events),['inner 1/1','outer 1','inner 2/1','outer 2'])
        inner['body_steps'][1]['type']='control.continue'
        _,events=run(flow(loop('outer',2,[inner,node('outer-log','log',message='outer')])) )
        self.assertEqual(messages(events).count('outer'),2)
        self.assertEqual(len(messages(events)),8)

    def test_loop_only_variables_and_index_do_not_escape(self):
        for name in ('created','repeat_index'):
            f=flow(loop('repeat',body=[number('created',7)]),node('copy','variable.set',output='copy',value_type='number',source='reference',source_variable=name))
            with self.assertRaisesRegex(ValueError,'尚未定义'):validate_flow(f)
        f=flow(number('created',0),loop('repeat',body=[{**number('created',7),'id':'update'}]),node('copy','variable.set',output='copy',value_type='number',source='reference',source_variable='created'))
        c,_=run(f);self.assertEqual(c.variables['copy'],7)

    def test_controls_outside_loop_and_duplicate_nested_index(self):
        for kind in ('control.break','control.continue'):
            f=flow(node('invalid',kind))
            validate_flow(f,draft=True)
            with self.assertRaisesRegex(ValueError,'只能放在循环体'):validate_flow(f)
        inner=loop('inner',index_variable='same')
        with self.assertRaisesRegex(ValueError,'不能重复'):validate_flow(flow(loop('outer',body=[inner],index_variable='same')))

    def test_nested_schema_and_duplicate_ids_are_validated(self):
        f=flow(loop('repeat',body=[node('same','log',message='a')]),node('same','log',message='b'))
        with self.assertRaisesRegex(ValueError,'重复'):validate_flow(f)
        bad=loop('repeat');bad['then_steps']=[]
        with self.assertRaises(ValueError):validate_flow(flow(bad))


if __name__=='__main__':unittest.main()
