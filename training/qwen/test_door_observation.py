import json
import pytest
from door_observation import parse_door_observation


@pytest.mark.parametrize('sequence',list('ABCD'))
def test_preserves_actual_door_decision(sequence):
    value={'before':'Visible panel state','after':'Visible panel state','sequence':sequence}
    assert parse_door_observation(json.dumps(value))==value


@pytest.mark.parametrize('text',[
    '{}','not JSON',
    '{"before":"x","after":"y","sequence":"A","sequence":"C"}',
    '{"before":"","after":"y","sequence":"C"}',
    '{"before":"x","after":"y","sequence":"observed"}',
])
def test_invalid_generation_never_becomes_a_negative(text):
    with pytest.raises(ValueError):
        parse_door_observation(text)
