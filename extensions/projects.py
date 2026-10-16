"""Named local projects. Each project owns its full flow and portable assets."""
import json
from datetime import datetime, timezone
from pathlib import Path
import uuid

from validation import validate_flow, walk_steps


class ProjectStore:
    def __init__(self, directory, legacy=None):
        self.directory=Path(directory)
        self.legacy=Path(legacy) if legacy else None

    def path(self, identifier):
        try:
            if str(uuid.UUID(identifier))!=identifier:raise ValueError()
        except (ValueError,TypeError,AttributeError):
            raise ValueError('项目 ID 无效') from None
        return self.directory/(identifier+'.json')

    @staticmethod
    def name(value):
        if not isinstance(value,str) or not value.strip() or len(value.strip())>80 or any(ord(c)<32 for c in value):
            raise ValueError('请输入 1–80 个字符的项目名称')
        return value.strip()

    def write(self, project):
        self.directory.mkdir(parents=True,exist_ok=True)
        target=self.path(project['id']);temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(target)
        return project

    def create(self, name, flow=None, identifier=None):
        name=self.name(name)
        if flow is None:flow={'schema_version':1,'name':name,'steps':[],'elements':[],'images':[]}
        flow=validate_flow({**flow,'name':name},allow_empty=True,draft=True)
        now=datetime.now(timezone.utc).isoformat()
        return self.write({'id':identifier or str(uuid.uuid4()),'name':name,'created_at':now,'updated_at':now,'flow':flow})

    def load(self, identifier):
        target=self.path(identifier)
        if not target.exists():raise ValueError('项目不存在，可能已被移动或删除')
        project=json.loads(target.read_text(encoding='utf-8'))
        if not isinstance(project,dict) or project.get('id')!=identifier:raise ValueError('项目文件内容无效')
        if any(not isinstance(project.get(key),str) for key in ('created_at','updated_at')):raise ValueError('项目时间信息无效')
        project['name']=self.name(project['name'])
        project['flow']=validate_flow({**project['flow'],'name':project['name']},allow_empty=True,draft=True)
        return project

    def save(self, identifier, flow):
        project=self.load(identifier)
        project['flow']=validate_flow({**flow,'name':project['name']},allow_empty=True,draft=True)
        project['updated_at']=datetime.now(timezone.utc).isoformat()
        return self.write(project)

    def migrate(self):
        if not self.legacy or not self.legacy.exists():return
        marker=self.directory/'.legacy-migrated'
        if marker.exists():return
        # A deterministic ID makes migration repeatable even after interruption.
        identifier=str(uuid.uuid5(uuid.NAMESPACE_URL,str(self.legacy.resolve())+'#sneerrpa-v1'))
        if not self.path(identifier).exists():
            flow=json.loads(self.legacy.read_text(encoding='utf-8'))
            self.create(flow.get('name') or '原有工作流',flow,identifier)
        marker.write_text(identifier,encoding='utf-8')

    def list(self):
        warnings=[]
        try:self.migrate()
        except (ValueError,OSError,KeyError,TypeError):warnings.append('原有流程未能自动迁移，原文件已保留。')
        result=[]
        if self.directory.exists():
            for file in self.directory.glob('*.json'):
                try:
                    p=self.load(file.stem)
                    result.append({key:p[key] for key in ('id','name','created_at','updated_at')}|{'step_count':sum(1 for _ in walk_steps(p['flow']['steps']))})
                except (ValueError,OSError,KeyError,TypeError):warnings.append('有项目无法读取，原文件已保留。')
        return sorted(result,key=lambda p:p['updated_at'],reverse=True),list(dict.fromkeys(warnings))
