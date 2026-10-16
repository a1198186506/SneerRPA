from pathlib import Path
import sys
import tempfile
import unittest
import json
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'extensions'))
from exe_export import export_target,publish_exe,prepare_flow,ROOT
from runtime_resources import resolve_resource,PREFIX
from automation import Context
from types import SimpleNamespace


class ExeExport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_names_and_optional_extension(self):
        self.assertEqual(export_target(str(self.root),'中文 工作流'),self.root/'中文 工作流.exe')
        self.assertEqual(export_target(str(self.root),'workflow.EXE'),self.root/'workflow.exe')
        for name in ('','../escape','bad/name','bad\\name','CON','NUL.exe','COM1.txt','bad:name','bad?name','trailing.',' leading','trailing '):
            with self.subTest(name=name),self.assertRaises(ValueError):export_target(str(self.root),name)
        with self.assertRaises(ValueError):export_target('relative','name')
        with self.assertRaises(ValueError):export_target(str(self.root/'missing'),'name')

    def test_publish_does_not_overwrite_or_leave_partial_files(self):
        source=self.root/'source';source.write_bytes(b'MZ'+b'X'*1000)
        target=export_target(str(self.root),'result')
        self.assertEqual(publish_exe(source,target),1002);self.assertEqual(target.read_bytes(),source.read_bytes())
        with self.assertRaises(ValueError):publish_exe(source,target)
        with self.assertRaises(ValueError):export_target(str(self.root),'result.exe')
        with self.assertRaises(FileNotFoundError):publish_exe(self.root/'missing',self.root/'another.exe')
        self.assertEqual(list(self.root.glob('.sneerrpa-*')),[])

    def test_builtin_sample_script_is_bundled_without_changing_source_flow(self):
        source=json.loads((ROOT/'resources/sample-flow.json').read_text(encoding='utf-8'))
        prepared,resources=prepare_flow(source)
        self.assertEqual(resources,['tools/test-window.ps1'])
        self.assertEqual(prepared['steps'][0]['params']['args'][-1],PREFIX+'tools/test-window.ps1')
        self.assertEqual(source['steps'][0]['params']['args'][-1],'tools/test-window.ps1')
        source['steps'][0]['params']['args'][-1]=str(ROOT/'tools/test-window.ps1')
        self.assertEqual(prepare_flow(source)[1],['tools/test-window.ps1'])
        source['steps'][0]['params']['args'][-1]='external/script.ps1'
        self.assertEqual(prepare_flow(source)[1],[])

    def test_builtin_resource_uses_extracted_folder_and_rejects_traversal(self):
        tools=self.root/'tools';tools.mkdir();script=tools/'test-window.ps1';script.write_text('test')
        with patch.object(sys,'_MEIPASS',str(self.root),create=True):
            self.assertEqual(resolve_resource(PREFIX+'tools/test-window.ps1'),str(script))
            with self.assertRaises(ValueError):resolve_resource(PREFIX+'../tools/test-window.ps1')
            script.unlink()
            with self.assertRaisesRegex(ValueError,'重新导出'):resolve_resource(PREFIX+'tools/test-window.ps1')
        self.assertEqual(resolve_resource('external/script.ps1'),'external/script.ps1')

    def test_failed_launched_process_reports_the_startup_problem(self):
        context=Context({'schema_version':1,'steps':[]},lambda *args,**kwargs:None)
        context.launched_processes=[SimpleNamespace(pid=123,poll=lambda:64)]
        with self.assertRaisesRegex(ValueError,'提前退出.*64'):
            context.target_window({'target_mode':'criteria','title':'SneerRPA 节点测试台','process_id':'123'})


if __name__=='__main__':unittest.main()
