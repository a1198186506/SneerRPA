"""Shared defaults, conditional fields, and schema-v1 compatibility."""
import json
import sys
from pathlib import Path

RESOURCE_ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
CATALOG = json.loads((RESOURCE_ROOT / 'resources/actions.json').read_text(encoding='utf-8'))
DEFINITIONS = {item['type']: item for item in CATALOG}


def visible(field, params):
    return all(params.get(key) in values for key, values in field.get('show_if', {}).items())


def effective_params(kind, original):
    params = {f['key']: f.get('default') for f in DEFINITIONS[kind]['fields']}
    params.update(original)
    if kind.startswith('window.') and 'target_mode' not in original:
        params['target_mode'] = 'criteria' if kind == 'window.get' else 'variable'
    if kind.startswith('element.') and 'window' not in original:
        params['window'] = 'main_window'  # Default used by the first schema-v1 release.
    return {f['key']: params[f['key']] for f in DEFINITIONS[kind]['fields'] if visible(f, params)}
