"""Keep installed user projects and build jobs outside the application files."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get('SNEERRPA_DATA_DIR'):
    DATA = Path(os.environ['SNEERRPA_DATA_DIR'])
elif (ROOT / 'installed.json').is_file():
    DATA = Path(os.environ['LOCALAPPDATA']) / 'SneerRPA'
else:
    DATA = ROOT / 'projectdata'
BUILD_JOBS = DATA / 'cache/exe-build' if (ROOT / 'installed.json').is_file() else ROOT / '.tmp/exe-build'
