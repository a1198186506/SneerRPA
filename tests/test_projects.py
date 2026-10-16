import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'extensions'))
from projects import ProjectStore


class Projects(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=ProjectStore(self.root/'projects',self.root/'current-flow.json')

    def test_create_and_save_independent_named_projects(self):
        a=self.store.create(' 第一个项目 ');b=self.store.create('第二个项目')
        self.assertNotEqual(a['id'],b['id']);self.assertEqual(a['name'],'第一个项目')
        a['flow']['steps']=[{'id':'step','type':'log','name':'记录','params':{'message':'你好'}}]
        self.store.save(a['id'],a['flow'])
        self.assertEqual(self.store.load(a['id'])['flow']['steps'][0]['params']['message'],'你好')
        self.assertEqual(self.store.load(b['id'])['flow']['steps'],[])
        history,_=self.store.list();self.assertEqual(history[0]['id'],a['id']);self.assertEqual(history[0]['step_count'],1)

    def test_invalid_names_ids_and_malformed_flow_do_not_create_files(self):
        for name in ('','  ','a'*81,'bad\nname',None):
            with self.assertRaises(ValueError):self.store.create(name)
        for identifier in ('../current-flow','C:/elsewhere','not-an-id',None):
            with self.assertRaises(ValueError):self.store.load(identifier)
        with self.assertRaises(ValueError):self.store.create('bad',{'schema_version':1,'steps':'bad'})
        self.assertFalse(self.store.directory.exists())

    def test_legacy_flow_migrates_once_and_preserves_original(self):
        flow={'schema_version':1,'name':'原来的项目','steps':[],'elements':[]}
        self.store.legacy.write_text(json.dumps(flow),encoding='utf-8')
        first,_=self.store.list();second,_=self.store.list()
        self.assertEqual(len(first),1);self.assertEqual(first,second)
        self.assertEqual(json.loads(self.store.legacy.read_text()),flow)
        flow['name']='changed';self.store.legacy.write_text(json.dumps(flow),encoding='utf-8')
        self.assertEqual(self.store.list()[0][0]['name'],'原来的项目')

    def test_corrupt_file_is_reported_without_destroying_other_projects(self):
        p=self.store.create('good');bad=self.store.path('00000000-0000-0000-0000-000000000000');bad.write_text('not json')
        rows,warnings=self.store.list();self.assertEqual([x['id'] for x in rows],[p['id']]);self.assertTrue(warnings)
        self.assertEqual(bad.read_text(),'not json')

    def test_atomic_save_preserves_previous_file_on_replace_failure(self):
        p=self.store.create('safe');before=self.store.path(p['id']).read_bytes()
        with patch.object(Path,'replace',side_effect=OSError('locked')):
            with self.assertRaises(OSError):self.store.save(p['id'],p['flow'])
        self.assertEqual(self.store.path(p['id']).read_bytes(),before)

    def test_invalid_draft_and_duplicate_names_are_allowed(self):
        p=self.store.create('same');self.store.create('same')
        p['flow']['steps']=[{'id':'waiting','name':'待配置','type':'image.find','params':{}}]
        self.store.save(p['id'],p['flow']);self.assertEqual(len(self.store.list()[0]),2)


if __name__=='__main__':unittest.main()
