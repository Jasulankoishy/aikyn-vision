from result_quality import apply_quality_gate, support_for


def event(category='c01'):
    return {'category_id': category, 'start_sec': 10., 'end_sec': 11., 'timecode_sec': 10.}


def window(start, end, **checks):
    return {'start_sec': start, 'end_sec': end, 'checks': checks}


def test_compound_support_must_be_in_the_same_overlapping_window():
    rows = [window(0, 20, old_cash_at_client_change='seen', cash_left_on_counter='seen'),
            window(30, 50, next_client_started='seen')]
    assert support_for(event(), rows)[0] is False
    rows[0]['checks']['next_client_started'] = 'seen'
    assert support_for(event(), rows)[0] is True


def test_visitor_departure_cannot_replace_employee_departure():
    row = window(0, 20, cash_unattended='seen', cash_left_on_counter='seen', client_departed='seen')
    assert support_for(event('c06'), [row])[0] is False
    row['checks']['cashier_left'] = 'seen'
    assert support_for(event('c06'), [row])[0] is True


def test_uncertain_event_is_retained_and_no_compliance_is_claimed():
    original = {'verdict': 'violation', 'violations': [event()],
                'analysis': {'complete': True, 'timeline_covered': True, 'windows': []}}
    result = apply_quality_gate(original)
    assert result['violations'] == []
    assert len(result['analysis']['deferred_findings']) == 1
    assert result['analysis']['result_status'] == 'review_required'
    assert result['analysis']['compliance_established'] is False
    assert original['violations'] == [event()]
    assert len(result['analysis']['review_questions']) == 1


def test_unrelated_event_does_not_get_lost_when_another_is_deferred():
    original = {'verdict': 'violation', 'violations': [event(), event('c02')],
                'analysis': {'complete': True, 'timeline_covered': True,
                             'windows': [window(0, 20, cash_mixed='seen', next_client_started='seen')]}}
    result = apply_quality_gate(original)
    assert [e['category_id'] for e in result['violations']] == ['c02']
    assert [e['category_id'] for e in result['analysis']['deferred_findings']] == ['c01']


def test_future_window_and_invalid_time_are_not_support():
    rows = [window(30, 40, cash_mixed='seen', next_client_started='seen')]
    assert support_for(event('c02'), rows)[0] is False
    assert support_for({**event('c02'), 'start_sec': float('nan')}, rows)[0] is False


def test_two_bundles_alone_do_not_establish_money_from_two_clients():
    rows = [window(0, 20, cash_mixed='seen', cash_counted='seen')]
    assert support_for(event('c02'), rows)[0] is False


def test_room_door_does_not_require_employee_departure_or_visitor_entry():
    rows=[window(0,20,room_door_left_open='seen',cashier_left='not_seen')]
    assert support_for(event('c12'),rows)[0] is True
    assert support_for(event('c08'),rows)[0] is False
    rows[0]['checks']['room_door_left_open']='unclear'
    assert support_for(event('c12'),rows)[0] is False
