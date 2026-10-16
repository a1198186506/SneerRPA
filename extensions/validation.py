"""Validate persisted flows before any desktop side effect."""
import math
import re
from parameters import CATALOG, DEFINITIONS, effective_params
from image_assets import validate_image, MAX_TOTAL_BYTES
from values import REFERENCE, output_types


def walk_steps(steps,depth=0):
    if depth>16 or not isinstance(steps,list):
        raise ValueError('容器步骤格式无效或嵌套超过 16 层')
    for step in steps:
        if not isinstance(step,dict):
            raise ValueError('步骤格式无效')
        yield step
        for branch in ('then_steps','else_steps','body_steps'):
            if branch in step:
                allowed=('body_steps',) if step.get('type')=='control.loop' else ('then_steps','else_steps') if step.get('type')=='control.if' else ()
                if branch not in allowed:
                    raise ValueError('IF 或循环的子步骤字段无效')
                yield from walk_steps(step[branch],depth+1)


def check_types(steps,known,draft=False,loop_indices=()):
    known=dict(known)
    for step in steps:
        kind=step['type'];p=effective_params(kind,step['params'])
        if not draft:
            for field in DEFINITIONS[kind]['fields']:
                key=field['key']
                if key not in p or field.get('kind')!='reference':continue
                name=p[key]
                if name not in known:
                    raise ValueError(f'{step["name"]}：变量尚未定义或并非所有分支都会赋值：{name}')
                if field.get('types') and known[name] not in field['types']:
                    raise ValueError(f'{step["name"]}：变量 {name} 类型不适用')
        if kind=='variable.set' and not draft:
            expected=p['value_type'];source=p['source']
            if (expected=='window' and source=='literal') or (expected!='window' and source=='window'):
                raise ValueError('窗口变量请选择获取窗口或已有窗口变量')
            if source=='reference' and known.get(p['source_variable'])!=expected:
                raise ValueError('设置变量的来源类型与目标类型不兼容')
        if kind in ('control.break','control.continue') and not loop_indices and not draft:
            raise ValueError('跳出循环和继续循环只能放在循环体内')
        if kind=='control.loop':
            index=p['index_variable']
            if not draft:
                if index in loop_indices:
                    raise ValueError('嵌套循环的序号变量名不能重复')
                if index in known and known[index]!='number':
                    raise ValueError('循环序号变量必须是 number 类型')
                if p['count_source']=='literal' and p['count']>p['max_iterations']:
                    raise ValueError('循环次数超过设置的上限')
            # A loop may run zero times or break before assigning a new variable.
            check_types(step.get('body_steps',[]),{**known,index:'number'},draft,(*loop_indices,index))
        elif kind=='control.if':
            if not draft:
                left=known.get(p['left'])
                right=known.get(p['right_reference']) if p['right_source']=='reference' else p['right_type']
                if left!=right or left not in ('bool','string','number'):
                    raise ValueError('IF 两侧变量类型不兼容')
                if p['operator'] not in ('==','!=') and left!='number':
                    raise ValueError('大小比较只支持数字')
            yes=check_types(step.get('then_steps',[]),known,draft,loop_indices)
            no=check_types(step.get('else_steps',[]),known,draft,loop_indices)
            for name in yes.keys()&no.keys():
                if yes[name]!=no[name] and not draft:
                    raise ValueError(f'两个分支中的同名变量类型不一致：{name}')
            known={name:yes[name] for name in yes.keys()&no.keys() if yes[name]==no[name]}
        else:
            outputs=output_types(kind,p)
            for name,typ in outputs.items():
                if name in known and known[name]!=typ and not draft:
                    raise ValueError(f'同名变量不能改变类型：{name}')
            known.update(outputs)
    return known


def validate_selector(selector):
    if not isinstance(selector, dict) or selector.get('backend', 'uia') not in ('uia', 'win32'):
        raise ValueError('元素选择器后端无效')
    window = selector.get('window')
    if not isinstance(window, dict) or not any(window.get(k) for k in ('title', 'class_name', 'process_name')):
        raise ValueError('元素选择器必须指定窗口')
    if window.get('backend', selector.get('backend', 'uia')) != selector.get('backend', 'uia'):
        raise ValueError('选择器窗口后端与控件后端不一致')
    for key in ('title', 'class_name', 'process_name'):
        if key in window and not isinstance(window[key], str):
            raise ValueError('窗口定位属性必须是文本')
    if window.get('match', 'exact') not in ('exact', 'contains', 'regex'):
        raise ValueError('窗口标题匹配方式无效')
    if window.get('match') == 'regex':
        re.compile(window.get('title', ''))
    allowed = {'name', 'automation_id', 'control_type', 'class_name', 'control_id'}
    if 'path' in selector and (not isinstance(selector['path'], list) or any(not isinstance(p, dict) for p in selector['path'])):
        raise ValueError('元素 path 必须是定位层级数组')
    criteria = [selector['criteria']] if 'criteria' in selector else [p.get('criteria') for p in selector.get('path', [])]
    for item in criteria:
        if not isinstance(item, dict) or not item or set(item) - allowed:
            raise ValueError('元素定位属性无效')
        if any(not isinstance(v, (str, int)) or isinstance(v, bool) for v in item.values()):
            raise ValueError('元素定位属性类型无效')
    if not criteria and selector.get('path') != []:
        raise ValueError('元素选择器需要 criteria 或 path')


def validate_flow(flow, allow_empty=False, draft=False, check_references=True):
    if not isinstance(flow, dict) or flow.get('schema_version') != 1 or not isinstance(flow.get('steps'), list):
        raise ValueError('无效流程格式')
    if not flow['steps'] and not allow_empty:
        raise ValueError('流程至少需要一个步骤')
    flattened=list(walk_steps(flow['steps']))
    if len(flattened) > 1000:
        raise ValueError('流程步骤不能超过 1000 个')
    elements = flow.get('elements', [])
    if not isinstance(elements, list):
        raise ValueError('元素库格式无效')
    element_ids = set()
    for element in elements:
        if not isinstance(element, dict) or not isinstance(element.get('id'), str) or not element['id'] or element['id'] in element_ids:
            raise ValueError('元素 ID 为空或重复')
        if not isinstance(element.get('name'), str):
            raise ValueError('元素名称无效')
        element_ids.add(element['id'])
        validate_selector(element.get('selector'))
    images = flow.get('images', [])
    if not isinstance(images, list):
        raise ValueError('图片素材库格式无效')
    image_ids, total = set(), 0
    for asset in images:
        total += validate_image(asset)
        if asset['id'] in image_ids or asset['id'] in element_ids:
            raise ValueError('图片 ID 与已有素材重复')
        image_ids.add(asset['id'])
        if total > MAX_TOTAL_BYTES:
            raise ValueError('图片素材总大小超过 16 MB，请移除不用的图片')
    ids = set()
    for step in flattened:
        if not isinstance(step, dict) or not isinstance(step.get('id'), str) or not step['id'] or step['id'] in ids:
            raise ValueError('步骤 ID 为空或重复')
        ids.add(step['id'])
        if step.get('type') not in DEFINITIONS or not isinstance(step.get('params'), dict) or not isinstance(step.get('name'), str):
            raise ValueError('步骤动作或参数格式无效')
        active = effective_params(step['type'], step['params'])
        for field in DEFINITIONS[step['type']]['fields']:
            key, kind = field['key'], field.get('kind', 'text')
            if key not in active:
                continue
            value = active[key]
            if field.get('required') and not value and not draft:
                raise ValueError(f'{step["name"]}：{field["label"]}不能为空')
            if kind == 'number':
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (not draft and not field.get('min', 0) <= value <= field.get('max', 120)):
                    raise ValueError(f'{step["name"]}：{field["label"]}必须在 {field.get("min", 0)}–{field.get("max", 120)} 之间')
                if field.get('integer') and value != int(value):
                    raise ValueError(f'{step["name"]}：{field["label"]}必须是整数')
            elif kind == 'boolean' and not isinstance(value, bool):
                raise ValueError('布尔参数无效')
            elif kind == 'json':
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise ValueError('程序参数必须是字符串 JSON 数组')
            elif kind == 'select' and value not in [o[0] for o in field['options']]:
                raise ValueError('选项参数无效')
            elif kind == 'element' and value not in element_ids and not (draft and value == ''):
                raise ValueError(f'{step["name"]}：请指定元素库中的目标元素')
            elif kind == 'image' and value not in image_ids and not (draft and value==''):
                raise ValueError(f'{step["name"]}：请选择图片素材库中的目标图片')
            elif kind not in ('number', 'boolean', 'json') and not isinstance(value, str):
                raise ValueError(f'{field["label"]}必须是文本')
            if kind == 'variable' and value and not re.fullmatch(r'[A-Za-z_]\w*', value):
                raise ValueError('变量名需以英文字母或下划线开头，仅含字母、数字和下划线')
            if kind=='reference' and value and not REFERENCE.fullmatch(value):
                raise ValueError('变量引用格式无效')
        if (step['type'].startswith('window.') or step['type']=='variable.set' and active.get('source')=='window') and active.get('target_mode') == 'criteria' and not draft:
            if not any(active.get(k) for k in ('title', 'class_name', 'process_name', 'process_id')):
                raise ValueError(f'{step["name"]}：请填写至少一个窗口条件')
    if check_references:
        check_types(flow['steps'],{},draft)
    return flow
