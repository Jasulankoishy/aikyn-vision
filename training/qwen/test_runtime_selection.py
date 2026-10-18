"""CPU-only routing checks: no weights, video, GPU or experimental imports."""
import json
import sys
from types import SimpleNamespace

import pytest
import runtime_selection as runtime


def settings(tmp_path, value):
    path = tmp_path / 'selection.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def test_shipped_configuration_selects_native_4b_with_pixel_cap():
    assert runtime.read_selection() == {'engine': 'native', 'model': '4b', 'pixel_cap': 3_145_728}


def test_4b_factory_passes_selected_local_snapshot_and_cap_without_loading_model(monkeypatch, tmp_path):
    calls = []
    marker = object()
    def fake_engine(**kwargs):
        calls.append(kwargs)
        return marker
    monkeypatch.setitem(sys.modules, 'native_engine', SimpleNamespace(NativeQuickEngine=fake_engine))
    result = runtime.create_engine(settings(tmp_path, {'engine': 'native', 'model': '4b', 'pixel_cap': 3_145_728}))
    assert result is marker
    assert calls == [{'model_dir': runtime.HERE / 'base-4b', 'pixel_cap': 3_145_728}]


def test_missing_override_retains_legacy_2b_fallback(tmp_path):
    assert runtime.read_selection(tmp_path / 'missing.json') == {'engine': 'native', 'model': '2b', 'pixel_cap': None}


@pytest.mark.parametrize('value', [
    {'engine': 'focused'}, {'engine': 'observation_native'}, {'model': '../base-4b'},
    {'model': []}, {'model': True}, {'pixel_cap': True}, {'pixel_cap': 0},
    {'pixel_cap': 8_388_609}, {'pixel_cap': float('nan')}, {'auto_crop': True},
])
def test_unpublished_engines_and_invalid_settings_fail_explicitly(tmp_path, value):
    with pytest.raises(ValueError):
        runtime.read_selection(settings(tmp_path, value))


def test_duplicate_keys_do_not_silently_change_selected_model(tmp_path):
    path = tmp_path / 'selection.json'
    path.write_text('{"model":"2b","model":"4b"}', encoding='utf-8')
    with pytest.raises(ValueError):
        runtime.read_selection(path)
