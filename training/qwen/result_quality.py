"""Check temporal consistency of model claims without reference answers.

Missing support means uncertainty, never proof that an action did not occur.
This gate checks the model's own consistency; it is not independent vision.
"""
from copy import deepcopy
import math

VERSION = 'compound-support-v3-fourteen-categories'
REQUIREMENTS = {
    'c01': ('old_cash_at_client_change', 'cash_left_on_counter', 'next_client_started'),
    # Catalog c02 concerns TWO CLIENTS, not merely two parts of one bundle.
    'c02': ('cash_mixed', 'next_client_started'),
    # Absence of a sampled action is not evidence of skipping that action.
    # Only a positive compound observation may support c03/c04.
    'c03': ('cash_receipt_without_visible_count',),
    'c04': ('cash_receipt_without_visible_identity_check',),
    'c05': ('cash_counted_after_client_departure', 'cash_counted', 'client_departed'),
    'c06': ('cash_unattended', 'cash_left_on_counter', 'cashier_left'),
    'c07': ('package_left_unattended', 'cashier_left'),
    'c08': ('safe_open_when_left', 'cashier_left'),
    'c09': ('safe_key_left_in_lock',),
    'c10': ('documents_or_seals_left_unattended', 'cashier_left'),
    'c11': ('screen_unlocked_when_left', 'cashier_left'),
    # An open room door does not require anyone to cross the threshold.
    'c12': ('room_door_left_open',),
    'c13': ('personal_items_in_cash_area',),
    'c14': ('rejected_banknotes_recombined',),
}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def support_for(event, windows):
    required = REQUIREMENTS.get(event.get('category_id'))
    if required is None:
        return False, 'unsupported_category'
    start, end = event.get('start_sec'), event.get('end_sec')
    if not (_finite(start) and _finite(end) and 0 <= start <= end):
        return False, 'invalid_interval'
    # Never assemble a compound event from unrelated parts of the recording.
    nearby = [w for w in windows if _finite(w.get('start_sec')) and _finite(w.get('end_sec'))
              and w['start_sec'] <= end and w['end_sec'] >= start]
    if any(all(w.get('checks', {}).get(key) == 'seen' for key in required) for w in nearby):
        return True, 'same_window_components'
    return False, 'compound_components_not_supported_together'


def apply_quality_gate(result):
    """Preserve doubtful findings for review, without labelling them normal."""
    output = deepcopy(result)
    analysis = output['analysis']
    if analysis.get('complete') is not True or analysis.get('timeline_covered') is not True:
        raise ValueError('Quality gate requires complete analysis')
    accepted, deferred = [], []
    for event in output.get('violations', []):
        supported, reason = support_for(event, analysis.get('windows', []))
        if supported:
            event['consistency_check'] = reason
            accepted.append(event)
        else:
            event['status'] = 'requires_review_inconsistent_support'
            event['quality_reason'] = reason
            deferred.append(event)
    output['violations'] = accepted
    output['verdict'] = 'violation' if accepted else 'no_violation'  # legacy transport enum
    existing = analysis.get('deferred_findings', [])
    analysis['deferred_findings'] = existing + deferred
    analysis['result_status'] = ('possible_sign_requires_review' if accepted else
                                 'review_required' if existing or deferred else 'no_candidate')
    analysis['compliance_established'] = False
    analysis['supported_categories'] = list(REQUIREMENTS)
    analysis['quality_gate'] = {'version': VERSION, 'input_events': len(accepted)+len(deferred),
                                'accepted_events': len(accepted), 'deferred_events': len(deferred),
                                'independent_visual_verification': False}
    questions = analysis.setdefault('review_questions', [])
    for event in deferred:
        questions.append({'type': event.get('type', 'Проверка составного события'),
                          'category_id': event.get('category_id'), 'timecode_sec': event.get('timecode_sec'),
                          'status': 'requires_review', 'reason': 'inconsistent_compound_support',
                          'message': 'Модель предложила событие, но не отметила все необходимые действия в том же фрагменте. '
                                     'Сигнал сохранён для проверки; отсутствие опоры не доказывает правильность операции.'})
    return output
