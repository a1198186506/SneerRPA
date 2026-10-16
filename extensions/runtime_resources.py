"""Explicit built-in resources shared by the editor and frozen workflows."""
from pathlib import Path
import sys

PREFIX='sneerrpa-resource://'
BUILTINS=('tools/test-window.ps1',)
ROOT=Path(__file__).resolve().parent.parent


def resolve_resource(value):
    if not isinstance(value,str) or not value.startswith(PREFIX):return value
    relative=value[len(PREFIX):]
    if relative not in BUILTINS:raise ValueError('未知的内置资源：'+relative)
    root=Path(getattr(sys,'_MEIPASS',ROOT))
    target=root/relative
    if not target.is_file():raise ValueError('内置资源缺失：'+relative+'，请重新导出 EXE')
    return str(target)
