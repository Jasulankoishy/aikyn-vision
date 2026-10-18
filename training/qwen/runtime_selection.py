"""Published runtime: native Qwen3-VL-2B only; experiments are not registered."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS_FILE = HERE / 'runtime_selection.json'


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate runtime setting')
        result[key] = value
    return result


def read_selection(path=None):
    source = Path(path) if path is not None else SETTINGS_FILE
    try:
        data = source.read_bytes()
    except FileNotFoundError:
        raw = {}
    else:
        if len(data) > 8192:
            raise ValueError('Runtime settings file is too large')
        raw = json.loads(data.decode('utf-8'), object_pairs_hook=_unique)
    if type(raw) is not dict or set(raw) - {'engine', 'model', 'pixel_cap'}:
        raise ValueError('Unsupported runtime settings')
    if raw.get('engine', 'native') != 'native' or raw.get('model', '2b') != '2b':
        raise ValueError('This published build enables only the native 2B engine')
    cap = raw.get('pixel_cap')
    if cap is not None and (type(cap) is not int or not 0 < cap <= 8_388_608):
        raise ValueError('pixel_cap must be null or an integer in (0, 8388608]')
    return {'engine': 'native', 'model': '2b', 'pixel_cap': cap}


def create_engine(settings_path=None):
    selection = read_selection(settings_path)
    from native_engine import NativeQuickEngine
    return NativeQuickEngine(model_dir=HERE / 'base', pixel_cap=selection['pixel_cap'])
