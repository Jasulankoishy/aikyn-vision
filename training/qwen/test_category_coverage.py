"""Schema/candidate coverage only; not evidence of real visual accuracy."""
import json

import pytest

from native_core import (CHECK_GROUPS, FIELDS, RISK_KEYS, ChecklistGrammar,
                         checklist_prompt, parse_checklist, risk_candidates)


EXPECTED = {
    'c01': 'old_cash_at_client_change', 'c02': 'cash_mixed',
    'c03': 'cash_receipt_without_visible_count',
    'c04': 'cash_receipt_without_visible_identity_check',
    'c05': 'cash_counted_after_client_departure', 'c06': 'cash_unattended',
    'c07': 'package_left_unattended', 'c08': 'safe_open_when_left',
    'c09': 'safe_key_left_in_lock', 'c10': 'documents_or_seals_left_unattended',
    'c11': 'screen_unlocked_when_left', 'c12': 'room_door_left_open',
    'c13': 'personal_items_in_cash_area', 'c14': 'rejected_banknotes_recombined',
}


class Characters:
    eos_token_id = 0

    def __call__(self, texts, add_special_tokens=False):
        return {'input_ids': [list(map(ord, text)) for text in texts]}


def assert_grammar_accepts(grammar, value):
    prefix = []
    for token in map(ord, json.dumps(value, separators=(',', ':'))):
        assert token in grammar.allowed(prefix)
        prefix.append(token)
    assert grammar.allowed(prefix) == [0]


def test_all_fourteen_categories_have_real_questions_and_existing_order_is_stable():
    assert set(EXPECTED) == {f'c{i:02}' for i in range(1, 15)}
    assert len(RISK_KEYS) == 14 and set(RISK_KEYS) == set(EXPECTED.values())
    assert RISK_KEYS[:6] == ('cash_mixed', 'old_cash_at_client_change', 'cash_unattended',
                            'safe_open_when_left', 'screen_unlocked_when_left', 'room_door_left_open')
    grouped = [name for group in CHECK_GROUPS for name in group]
    assert len(grouped) == len(set(grouped)) and set(grouped) == set(FIELDS)
    assert CHECK_GROUPS[-1] == RISK_KEYS
    prompt = checklist_prompt(0, 20, [])
    for name in EXPECTED.values():
        assert '"' + name + '"' in prompt
        assert json.dumps(FIELDS[name]) in prompt


@pytest.mark.parametrize('category_id,key', sorted(EXPECTED.items()))
def test_each_category_can_be_asked_decoded_and_proposed_independently(category_id, key):
    checks = dict.fromkeys(FIELDS, 'not_seen')
    checks[key] = 'seen'
    assert_grammar_accepts(ChecklistGrammar(Characters()), checks)
    parsed = parse_checklist(json.dumps(checks))
    row = {'index': 0, 'start_sec': 0., 'end_sec': 20., 'checks': parsed}
    found = risk_candidates([row])
    assert len(found) == 1 and found[0]['kind'] == key
    assert found[0]['supporting_windows'] == [0]
    for nonpositive in ('not_seen', 'unclear'):
        row['checks'][key] = nonpositive
        assert not risk_candidates([row])


@pytest.mark.parametrize('group', CHECK_GROUPS)
def test_grouped_schema_really_includes_every_question_in_that_group(group):
    prompt = checklist_prompt(0, 20, [], fields=group)
    checks = {key: ('seen', 'not_seen', 'unclear')[i % 3] for i, key in enumerate(group)}
    assert_grammar_accepts(ChecklistGrammar(Characters(), group), checks)
    assert parse_checklist(json.dumps(checks), group) == checks
    assert all(json.dumps(FIELDS[key]) in prompt for key in group)


@pytest.mark.parametrize('key', RISK_KEYS[6:])
def test_new_risk_answer_cannot_be_omitted_or_silently_defaulted_negative(key):
    checks = dict.fromkeys(FIELDS, 'not_seen')
    del checks[key]
    with pytest.raises(ValueError, match='Invalid checklist'):
        parse_checklist(json.dumps(checks))


def test_new_criteria_distinguish_ambiguous_and_normal_visual_alternatives():
    count = FIELDS[EXPECTED['c03']]
    identity = FIELDS[EXPECTED['c04']]
    assert 'complete, continuously observable' in count and 'sampling gaps' in count
    assert 'cash_counted=not_seen is NOT evidence' in count
    assert 'document_checked=not_seen is NOT evidence' in identity
    assert 'digital identification means unclear' in identity
    assert 'FIRST' in FIELDS[EXPECTED['c05']] and 'additional recount' in FIELDS[EXPECTED['c05']]
    assert 'unknown contents' in FIELDS[EXPECTED['c07']]
    assert 'safe handle' in FIELDS[EXPECTED['c09']]
    assert 'Ordinary blank paper' in FIELDS[EXPECTED['c10']]
    personal = FIELDS[EXPECTED['c13']]
    assert 'personal bag, coat' in personal and 'office object' in personal
    assert 'public side' in personal and 'medical' in personal
    rejected = FIELDS[EXPECTED['c14']]
    assert 'normal output tray' in rejected and 'do NOT call the notes counterfeit' in rejected
