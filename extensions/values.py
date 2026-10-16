"""Strict value types and safe variable paths; no Python expression evaluation."""
import math
import operator
import re

NAME = re.compile(r'[A-Za-z_]\w*\Z')
REFERENCE = re.compile(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\Z')
COMPARISONS = {'==': operator.eq, '!=': operator.ne, '>': operator.gt, '>=': operator.ge, '<': operator.lt, '<=': operator.le}


def value_type(value):
    if type(value) is bool:
        return 'bool'
    if isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value):
        return 'number'
    if isinstance(value,str):
        return 'string'
    if hasattr(value,'element_info'):
        return 'window'
    if isinstance(value,dict):
        return 'object'
    if value is None:
        return 'null'
    raise ValueError('不支持的变量值类型')


def require_type(value, expected):
    if value_type(value) != expected:
        raise ValueError(f'变量类型不兼容：需要 {expected}，实际为 {value_type(value)}')
    return value


def compare(left, symbol, right):
    left_type, right_type = value_type(left), value_type(right)
    if left_type != right_type:
        raise ValueError(f'比较类型不兼容：{left_type} 与 {right_type}')
    if symbol not in COMPARISONS:
        raise ValueError('不支持的比较运算符')
    if left_type not in ('number','string','bool') or symbol not in ('==','!=') and left_type != 'number':
        raise ValueError('大小比较只支持数字；文本和布尔值使用相等或不等')
    return bool(COMPARISONS[symbol](left,right))


def output_types(kind,p):
    name=p.get('output')
    if not name:
        return {}
    result={name: {'variable.set':p.get('value_type'),'window.get':'window','window.exists':'bool',
        'app.launch':'number','element.wait':'bool','image.find':'match'}.get(kind,
        'string' if kind=='element.read' and p.get('info') in ('text','value') else 'object')}
    if kind=='image.find':
        result.update({f'{name}.{field}':typ for field,typ in {'found':'bool','score':'number','x':'number','y':'number',
            'width':'number','height':'number','center':'point','center.x':'number','center.y':'number'}.items()})
    return result
