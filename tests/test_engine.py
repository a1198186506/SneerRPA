import copy
import json
from pathlib import Path
import sys
import unittest
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'extensions'))
from automation import Context, Ambiguous, find_element, read_info, find_window, capture
from validation import DEFINITIONS, validate_flow, validate_selector
from parameters import effective_params


class WindowsActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.flow = json.loads((ROOT / 'resources/sample-flow.json').read_text(encoding='utf-8'))
        cls.events = []
        cls.context = Context(cls.flow, lambda event, **data: cls.events.append((event, data)))
        cls.run_action('app.launch', cls.flow['steps'][0]['params'])
        cls.run_action('window.get', cls.flow['steps'][1]['params'])

    @classmethod
    def run_action(cls, kind, params):
        cls.context.action(kind, params)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.run_action('window.close', {'window': 'main_window'})
        except Exception:
            pass
        for process in cls.context.launched_processes:
            process.wait(timeout=5)

    def test_ambiguous_element_does_not_click_first_match(self):
        with self.assertRaises(Ambiguous):
            find_element({'criteria': {'control_type': 'Edit'}}, self.context.window('main_window'))

    def test_native_and_real_keyboard_input(self):
        for method in ('native', 'input'):
            text = '中文 + {RPA} ^%~() ' + method
            self.run_action('element.input', {'element': 'sample-input', 'window': 'main_window', 'method': method, 'text': text})
            self.run_action('element.read', {'element': 'sample-input', 'window': 'main_window', 'info': 'value', 'output': 'typed_text'})
            self.assertEqual(self.context.variables['typed_text'], text)
        self.run_action('element.click', {'element': 'sample-confirm', 'window': 'main_window', 'method': 'input'})
        self.run_action('element.read', {'element': 'sample-result', 'window': 'main_window', 'info': 'value', 'output': 'answer'})
        self.assertEqual(self.context.variables['answer'], '已确认：' + text)

    def test_read_properties_and_rectangle(self):
        control = self.context.element({'element': 'sample-input', 'window': 'main_window'})
        self.assertEqual(read_info(control, 'properties')['automation_id'], 'InputText')
        self.assertGreater(read_info(control, 'rectangle')['width'], 0)

    def test_mouse_modes_and_keyboard_literal_unicode(self):
        control = self.context.element({'element': 'sample-input', 'window': 'main_window'})
        for mode in ('element','coordinates'):
            self.run_action('element.input', {'element': 'sample-input', 'text': '', 'window': 'main_window'})
            rect = control.rectangle()
            self.run_action('mouse.click', {'target_mode': mode, 'element': 'sample-input', 'x': rect.left+30, 'y': rect.top+10})
            text = '中文 RPA 😀 +^%~() {ENTER}\n第二行'
            self.run_action('keyboard.input', {'text': text})
            self.run_action('element.read', {'element': 'sample-input', 'window': 'main_window', 'info': 'value', 'output': 'keyboard_text'})
            self.assertEqual(self.context.variables['keyboard_text'].replace('\r\n','\n'), text)
            self.run_action('keyboard.input', {'text': ''})
        with self.assertRaises(ValueError):
            self.run_action('mouse.click', {'target_mode': 'coordinates', 'x': 2147483647, 'y': 2147483647})

    def test_win32_backend_capture_and_relocation(self):
        root = find_window({'backend': 'win32', 'title': 'SneerRPA 节点测试台', 'process_id': self.context.variables['app_process']})
        control = root.children(class_name_re='WindowsForms10.EDIT.*')[0]
        selector = capture(control, 'win32')
        self.assertEqual(find_element(selector, root).handle, control.handle)

    def test_wait_appear_disappear_and_timeout(self):
        self.context.elements['absent'] = {'selector': {'criteria': {'name': 'nonexistent-control'}}}
        params = {'element': 'absent', 'window': 'main_window', 'timeout': 0.1, 'fail_on_timeout': False, 'output': 'wait_result'}
        self.run_action('element.wait', {**params, 'state': 'appear'})
        self.assertIs(self.context.variables['wait_result'], False)
        self.run_action('element.wait', {**params, 'state': 'disappear'})
        self.assertIs(self.context.variables['wait_result'], True)
        with self.assertRaises(TimeoutError):
            self.run_action('element.wait', {**params, 'state': 'appear', 'fail_on_timeout': True})

    def test_window_states(self):
        window = self.context.window('main_window')
        for state in ('maximize', 'minimize', 'restore'):
            self.run_action('window.state', {'window': 'main_window', 'state': state})
            matches=getattr(window, {'maximize': 'is_maximized', 'minimize': 'is_minimized', 'restore': 'is_normal'}[state])
            deadline=time.monotonic()+2
            while not matches() and time.monotonic()<deadline:time.sleep(.05)
            self.assertTrue(matches())
        self.run_action('window.activate', {'window': 'main_window'})

    def test_window_targets_from_element_conditions_and_variable(self):
        original = self.context.window('main_window')
        # A saved child may be gone, but its owner can still be used.
        self.context.elements['missing-child'] = {'selector': {
            'backend': 'uia', 'window': {'backend': 'uia', 'title': original.window_text(), 'process_id': str(original.process_id())},
            'criteria': {'name': 'nonexistent-child'}}}
        for mode, target in [('element', {'element': 'missing-child'}), ('criteria', {'title': original.window_text(), 'process_id': str(original.process_id())}), ('variable', {'window': 'main_window'})]:
            self.run_action('window.get', {'target_mode': mode, **target, 'output': 'resolved'})
            self.assertEqual(self.context.variables['resolved'].handle, original.handle)
            self.run_action('window.activate', {'target_mode': mode, **target})
            self.run_action('window.state', {'target_mode': mode, **target, 'state': 'restore'})
        # An unused field must neither resolve variables nor change the selected target.
        self.run_action('window.get', {'target_mode': 'element', 'element': 'sample-input', 'window': '${undefined}', 'output': 'owner'})
        self.assertEqual(self.context.variables['owner'].handle, original.handle)

    def test_z_close_owner_from_element_library(self):
        self.run_action('window.close', {'target_mode': 'element', 'element': 'sample-confirm'})
        for process in self.context.launched_processes:
            process.wait(timeout=5)
        with self.assertRaises(ValueError):
            self.context.window('main_window')


class Validation(unittest.TestCase):
    def test_mouse_coordinates_and_keyboard_fields(self):
        self.assertEqual([f['key'] for f in DEFINITIONS['keyboard.input']['fields']], ['text'])
        flow = {'schema_version': 1, 'steps': [{'id':'one','name':'点击','type':'mouse.click','params':{'target_mode':'coordinates','x':-50,'y':10}}]}
        validate_flow(flow)  # Negative coordinates are valid on multi-monitor desktops.
        flow['steps'][0]['params']['x']=1.5
        with self.assertRaises(ValueError):
            validate_flow(flow)
        flow['steps'][0]['params']={'target_mode':'element','element':'missing','x':-50,'y':10}
        with self.assertRaises(ValueError):
            validate_flow(flow)
    def test_legacy_window_modes_and_new_element_defaults(self):
        self.assertEqual(effective_params('window.get', {'title': 'existing'})['target_mode'], 'criteria')
        self.assertEqual(effective_params('window.close', {'window': 'old_window'})['target_mode'], 'variable')
        self.assertEqual(effective_params('element.click', {})['window'], 'main_window')
        self.assertEqual(effective_params('element.click', {'window': ''})['window'], '')
        self.assertEqual(next(f for f in DEFINITIONS['element.click']['fields'] if f['key']=='window')['default'], '')

    def test_inactive_window_fields_are_ignored(self):
        flow = {'schema_version': 1, 'steps': [{'id': 'one', 'name': '激活', 'type': 'window.activate', 'params': {'target_mode': 'variable', 'window': 'main_window', 'element': 'deleted-entry'}}]}
        validate_flow(flow)
        flow['steps'][0]['params']['target_mode'] = 'element'
        with self.assertRaises(ValueError):
            validate_flow(flow)
        flow['steps'][0]['params'] = {'target_mode': 'criteria'}
        with self.assertRaises(ValueError):
            validate_flow(flow)

    def test_draft_is_saved_but_cannot_execute(self):
        flow = {'schema_version': 1, 'elements': [], 'steps': [{'id': 'one', 'name': '点击', 'type': 'element.click', 'params': {}}]}
        validate_flow(flow, draft=True)
        with self.assertRaises(ValueError):
            validate_flow(flow)

    def test_duplicate_ids_and_invalid_selectors(self):
        step = {'id': 'one', 'name': '日志', 'type': 'log', 'params': {'message': ''}}
        with self.assertRaises(ValueError):
            validate_flow({'schema_version': 1, 'steps': [step, copy.deepcopy(step)]})
        with self.assertRaises(ValueError):
            validate_selector({'backend': 'uia', 'window': {'title': 'test'}, 'path': 'bad'})

    def test_launch_arguments_are_not_shell_commands(self):
        flow = {'schema_version': 1, 'steps': [{'id': 'one', 'name': '启动', 'type': 'app.launch', 'params': {'path': 'test.exe', 'args': '&& command'}}]}
        with self.assertRaises(ValueError):
            validate_flow(flow)


if __name__ == '__main__':
    unittest.main(verbosity=2)
