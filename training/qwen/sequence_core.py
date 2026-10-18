"""Grounded action timeline and provisional workflow checks, without model imports."""
import json

VERSION = 'sequence-v1'
ACTIONS = {
    'document_checked': 'Осмотр документа',
    'cash_received': 'Приём денег от клиента',
    'machine_count': 'Пересчёт через аппарат',
    'computer_input': 'Ввод на компьютере',
    'cash_stored': 'Деньги помещены в сейф',
    'safe_opened': 'Сейф открыт',
    'safe_closed': 'Сейф закрыт',
    'client_departed': 'Клиент ушёл',
    'next_client_started': 'Начато обслуживание следующего клиента',
    'cash_returned': 'Деньги возвращены клиенту',
    'cash_mixed': 'Пачки денег объединены',
    'cashier_left': 'Кассир ушёл',
    'computer_locked': 'Компьютер заблокирован',
    'computer_unlocked': 'На компьютере открыта рабочая программа',
    'door_opened': 'Дверь открыта',
    'door_closed': 'Дверь закрыта',
    'notes_checked': 'Дополнительная проверка купюр',
}


def parse_actions(text, frames, window):
    try:
        value = json.loads(text[text.index('{'):text.rindex('}') + 1])
    except (ValueError, TypeError) as error:
        raise ValueError('Response is not complete action JSON') from error
    if not isinstance(value, dict):
        raise ValueError('Action response must be an object')
    # Small models may omit this optional flag. That never implies confidence:
    # preserve otherwise valid frame-grounded actions as uncertain observations.
    uncertain = value.get('uncertain', True)
    if type(uncertain) is not bool:
        raise ValueError('Uncertainty must be boolean')
    actions = value.get('actions')
    if not isinstance(actions, list) or len(actions) > 6:
        raise ValueError('Invalid actions list')
    result = []
    for action in actions:
        if not isinstance(action, dict) or action.get('action') not in ACTIONS:
            raise ValueError('Unknown action')
        a, b = action.get('first_frame'), action.get('last_frame')
        evidence = action.get('evidence', ACTIONS[action['action']])
        if type(a) is not int or type(b) is not int or not 1 <= a <= b <= len(frames):
            raise ValueError('Action frame index outside window')
        if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 350:
            raise ValueError('Missing or excessive action evidence')
        result.append({
            'action': action['action'], 'label': ACTIONS[action['action']],
            'start_sec': frames[a - 1]['time_sec'], 'end_sec': frames[b - 1]['time_sec'],
            'evidence': evidence.strip(), 'supporting_windows': [window['index']],
            'evidence_kind': 'model_description' if 'evidence' in action else 'action_label_with_frame_support',
            'evidence_timestamps': [f['time_sec'] for f in frames[a - 1:b]],
            'status': 'model_observation', 'human_verified': False,
        })
    return uncertain, result


def merge_actions(actions):
    """Merge only same-action overlapping sampled supports, not adjacent events."""
    merged = []
    for action in sorted(actions, key=lambda a: (a['action'], a['start_sec'], a['end_sec'])):
        prev = merged[-1] if merged else None
        if prev and prev['action'] == action['action'] and action['start_sec'] <= prev['end_sec']:
            prev['end_sec'] = max(prev['end_sec'], action['end_sec'])
            prev['supporting_windows'] = sorted(set(prev['supporting_windows'] + action['supporting_windows']))
            prev['evidence_timestamps'] = sorted(set(prev['evidence_timestamps'] + action['evidence_timestamps']))
        else:
            merged.append({**action, 'supporting_windows': list(action['supporting_windows']),
                           'evidence_timestamps': list(action['evidence_timestamps'])})
    merged.sort(key=lambda a: (a['start_sec'], a['end_sec'], a['action']))
    for i, action in enumerate(merged, 1):
        action['id'] = f'a{i:04}'
    return merged


def summarize(actions, gaps=()):
    """Rebuild on each window: overlap updates cannot execute transitions twice.

    Sessions are provisional, without biometric identity or proven cash ownership.
    Missing observations are review questions, never confirmed omitted actions.
    """
    transactions, checks = [], []
    current = None
    safe, screen, door = 'unknown', 'unknown', 'unknown'
    pending_document = None

    def new_transaction(action):
        return {'id': f'op{len(transactions)+1:03}', 'start_sec': action['start_sec'],
                'association': 'provisional_visual_sequence', 'steps': {},
                'record_transaction': 'unknown_requires_local_database_evidence',
                'closed': False, 'return_amount': 'unknown'}

    def check(rule, action, text, category=None):
        checks.append({'id': f'q{len(checks)+1:03}', 'rule': rule,
                       'category_id': category, 'trigger_action_id': action['id'],
                       'start_sec': action['start_sec'], 'end_sec': action['end_sec'],
                       'message': text, 'status': 'requires_review',
                       'violation_confirmed': False,
                       'operation_id': current['id'] if current else None})

    for action in actions:
        kind = action['action']
        if kind == 'document_checked':
            pending_document = action['id']
            if current and not current['closed']:
                current['steps']['document_checked'] = action['id']
        if kind == 'cash_received':
            if current is None or current['closed']:
                current = new_transaction(action)
                transactions.append(current)
                if pending_document:
                    current['steps']['document_checked'] = pending_document
                pending_document = None
            current['steps'].setdefault(kind, action['id'])
            if 'document_checked' not in current['steps']:
                check('identity_not_observed', action,
                      'До приёма денег осмотр документа не замечен; проверить начало операции.', 'c04')
        if kind == 'next_client_started':
            if current and not current['closed']:
                check('next_client_before_observed_completion', action,
                      'Начато обслуживание следующего клиента; завершение предыдущей операции не подтверждено.')
                current['closed'] = True
                current['end_reason'] = 'client_switch_not_verified_completion'
            # Never attach previous client's steps to the next operation.
            current = new_transaction(action)
            transactions.append(current)
            pending_document = None
        if kind == 'safe_opened': safe = 'open_observed'
        if kind == 'safe_closed': safe = 'closed_observed'
        if kind == 'computer_locked': screen = 'locked_observed'
        if kind == 'computer_unlocked': screen = 'working_screen_observed'
        if kind == 'door_opened': door = 'open_observed'
        if kind == 'door_closed': door = 'closed_observed'
        if kind == 'machine_count' and safe == 'open_observed':
            check('safe_open_at_count', action,
                  'После открытия сейфа замечен пересчёт; закрытие между действиями не подтверждено.', 'c08')
        if current and not current['closed']:
            if kind in {'machine_count', 'computer_input', 'cash_stored', 'cash_returned'}:
                current['steps'][kind] = action['id']
            if kind == 'safe_closed' and 'cash_stored' in current['steps']:
                current['steps']['safe_closed'] = action['id']
            if kind == 'cash_stored':
                current['steps'].pop('safe_closed', None)
            if kind == 'cash_stored':
                if 'machine_count' not in current['steps']:
                    check('count_not_observed', action,
                          'Перед помещением денег в сейф пересчёт аппаратом не замечен.', 'c03')
                check('database_write_unverified', action,
                      'Сохранение операции в базе требует подтверждения из локального журнала; видео этого не доказывает.')
            if kind == 'cash_returned':
                check('return_amount_unknown', action,
                      'Замечен возврат денег. По кадрам не установлено, возвращена вся сумма или часть.')
            if kind == 'client_departed':
                steps = current['steps']
                if 'cash_returned' in steps:
                    check('return_branch_needs_review', action,
                          'Клиент ушёл после возврата; полнота возврата требует проверки.')
                elif not ('cash_stored' in steps and 'safe_closed' in steps and safe == 'closed_observed'):
                    check('departure_before_observed_completion', action,
                          'Клиент ушёл; размещение денег и закрытие сейфа до ухода не подтверждены.')
                current['closed'] = True
                current['end_reason'] = 'client_departed_not_verified_completion'
                pending_document = None
        if kind == 'cashier_left':
            if screen == 'working_screen_observed':
                check('screen_lock_unverified', action,
                      'Кассир ушёл после наблюдения открытой программы; блокировка не подтверждена.', 'c11')
            if safe == 'open_observed':
                check('safe_close_unverified', action,
                      'Кассир ушёл; закрытие ранее открытого сейфа не подтверждено.', 'c08')
            if door == 'open_observed':
                check('door_close_unverified', action,
                      'Кассир ушёл; закрытие ранее открытой двери не подтверждено.', 'c12')
        if kind == 'client_departed': pending_document = None
    return {'version': VERSION, 'transactions': transactions, 'checks': checks,
            'latest_state': {'safe': safe, 'screen': screen, 'door': door},
            'coverage_gaps': list(gaps), 'all_findings_require_review': True,
            'workflow_source': 'user_described_cash_deposit',
            'scope': 'deposit hypotheses only; internal recounts without receipt have no deposit-step checks'}


def memory(actions, summary):
    """Bounded context of observations only; never consumes human video labels."""
    operations = summary['transactions']
    return {'previous_observations_unverified': True,
            'last_actions': [{'action': a['action'], 'start_sec': a['start_sec'],
                              'end_sec': a['end_sec']} for a in actions[-12:]],
            'latest_state': summary['latest_state'],
            'current_operation': operations[-1] if operations else None,
            'unread_window_count': len(summary['coverage_gaps'])}


def action_prompt(frames, context):
    numbered = ' '.join(f'{i+1}={f["time_sec"]:.3f}s' for i, f in enumerate(frames))
    return (
        'Observe this bank-counter clip, with ordered sampled frames. Extract up to SIX clearly VISIBLE actions. '
        'Previous context is uncertain model observation, not ground truth: ' + json.dumps(context, ensure_ascii=False) + '. '
        'Use context to follow the operation, but report ONLY actions supported by current images. '
        'Do not repeat previous actions absent from current frames. No identities, face recognition or guessed object contents. '
        'document_checked requires visible examination of a document, not just client arrival. '
        'cash_received requires visible handover from a client; internal counting alone is not receipt. '
        'computer_input means visible keyboard/mouse use, NEVER confirmed database saving. '
        'client_departed requires visible departure, not merely being outside the camera view. '
        'next_client_started requires actual service of another client, not a person waiting. '
        'cash_returned does not establish the returned amount. computer_unlocked requires a readable working screen. '
        'Allowed action IDs: ' + ', '.join(ACTIONS) + '. '
        'Frame numbers: ' + numbered + '. '
        'Return JSON only: {"actions":[],"uncertain":true}. Each action: '
        '{"action":"allowed ID","first_frame":1,"last_frame":1}. '
        'Use exactly these three fields per action. Do not write descriptions. '
        'Use 1-based frame indices, not seconds; first_frame <= last_frame. '
        'Set uncertain=true if visibility, operation type or continuity is unclear. Empty actions allowed. '
        'Missing sampled actions cannot be declared omitted. No Markdown. Close JSON completely.'
    )
