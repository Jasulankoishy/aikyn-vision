"""Compact inference protocol. No training labels, filenames or model dependencies."""
import json
import math
from itertools import combinations

ACTION_CODES = {
    1: ('document_checked', 'Документ осматривают'),
    2: ('cash_received', 'Клиент передаёт деньги кассиру'),
    3: ('cash_counted', 'Деньги пересчитывают'),
    4: ('computer_input', 'Кассир работает с клавиатурой или мышью'),
    5: ('cash_stored', 'Деньги помещают в хранилище'),
    6: ('safe_opened', 'Сейф открыт'),
    7: ('safe_closed', 'Сейф закрывают'),
    8: ('client_departed', 'Клиент уходит'),
    9: ('next_client_started', 'Начинают обслуживать следующего клиента'),
    10: ('cash_returned', 'Кассир передаёт деньги клиенту'),
    11: ('cash_mixed', 'Две отдельные пачки денег объединяют'),
    12: ('cashier_left', 'Кассир уходит с рабочего места'),
    13: ('computer_locked', 'Экран компьютера заблокирован'),
    14: ('computer_unlocked', 'На видимом экране открыта рабочая программа'),
    15: ('door_opened', 'Дверь кассового помещения открыта'),
    16: ('door_closed', 'Дверь кассового помещения закрыта'),
    17: ('notes_checked', 'Купюры дополнительно проверяют'),
    18: ('cash_left_on_counter', 'Деньги лежат на рабочем столе'),
}
CODE_DESCRIPTION = (
    '1=examining an identity document; 2=customer hands cash to cashier; '
    '3=counting banknotes by hand or machine; 4=using keyboard/mouse; '
    '5=putting banknotes into cash storage; 6=safe visibly open; 7=closing safe; '
    '8=customer leaves; 9=starts serving a different customer; '
    '10=cashier hands cash back to customer; 11=combines two separate cash stacks; '
    '12=cashier leaves workstation; 13=screen visibly locked; 14=readable working screen; '
    '15=cash-room door visibly open; 16=cash-room door closed; '
    '17=checking banknote authenticity; 18=banknotes visibly on counter'
)


def prompt(frames, previous):
    return (
        'Watch these ordered bank-counter images. List only clearly visible actions in CURRENT images. '
        'No identities, guessed money ownership, hidden database writes or claims that an unseen action never happened. '
        'A document handover alone is not a document check. Ordinary money movement is not necessarily mixing. '
        'Cash counting does not by itself mean receiving cash from a customer. '
        'Allowed actions: ' + ', '.join(name for name, _ in ACTION_CODES.values()) + '. '
        'cash_counted means counting banknotes manually or with a machine. '
        'cash_left_on_counter means visible banknotes resting on the desk. '
        'cash_mixed means visibly combining two previously separate stacks. '
        'Do not carry over actions from other clips. Judge only the current images. '
        'Return ONLY JSON {"actions":[],"uncertain":true}. '
        'actions must be a list of allowed action NAME STRINGS, without duplicates. '
        'At most THREE most clearly visible actions, in the order of the allowed list. '
        'Report each action once if visible anywhere in this short clip. Do not output frame numbers or timestamps. '
        'Only report actions with visible evidence; empty actions allowed. '
        'uncertain=true if the view or action is ambiguous. No explanation. Close JSON.'
    )


class PresenceGrammar:
    """Constrain syntax, not which observations the model chooses from images.

    A trie admits all subsets of up to three action labels and the empty set.
    Uncertainty is always true: model-generated confidence is not calibrated.
    """
    def __init__(self, tokenizer, max_actions=3):
        self.root = {}
        self.eos = tokenizer.eos_token_id
        self.max_tokens = 0
        names = [name for name, _ in ACTION_CODES.values()]
        for count in range(max_actions+1):
            for subset in combinations(names, count):
                suffix = json.dumps(list(subset), separators=(',', ':')) + ',"uncertain":true}'
                ids = tokenizer.encode(suffix, add_special_tokens=False)
                self.max_tokens = max(self.max_tokens, len(ids)+1)
                node = self.root
                for token in ids:
                    node = node.setdefault(token, {})
                node.setdefault(self.eos, {})

    def allowed(self, suffix_ids):
        node = self.root
        for token in suffix_ids:
            if token not in node:
                raise ValueError('Generated tokens left the action grammar')
            node = node[token]
        return list(node) or [self.eos]


def parse_presence(text, frames, window):
    """The model classifies a window; source times are context, not boundaries."""
    clean = text.strip()
    if clean.startswith('```json'):
        clean = clean[7:].strip()
    elif clean.startswith('```'):
        clean = clean[3:].strip()
    value, end = json.JSONDecoder().raw_decode(clean)
    # Accept a complete object followed only by a common model delimiter.
    # Never salvage truncated JSON, arbitrary prose, or another object.
    if clean[end:].strip() not in {'', '"', '```'}:
        raise ValueError('Unexpected text after action JSON')
    if not isinstance(value, dict) or set(value) - {'actions', 'uncertain'}:
        raise ValueError('Expected action presence object')
    uncertain = value.get('uncertain', True)
    if type(uncertain) is not bool:
        raise ValueError('Uncertainty must be boolean')
    names = value.get('actions')
    labels = dict(ACTION_CODES.values())
    if not isinstance(names, list) or len(names) > 36 or any(not isinstance(n, str) or n not in labels for n in names):
        raise ValueError('Unknown action presence labels')
    times = [f['time_sec'] for f in frames]
    if not times or times != sorted(set(times)) or any(not math.isfinite(t) or not window['start_sec'] <= t <= window['end_sec'] for t in times):
        raise ValueError('Invalid source window support')
    return uncertain, [
        {'action': name, 'label': labels[name], 'start_sec': times[0], 'end_sec': times[-1],
         'evidence': labels[name], 'evidence_timestamps': list(times),
         'evidence_kind': 'sampled_window_context', 'supporting_windows': [window['index']],
         'status': 'model_observation', 'human_verified': False, 'uncertain': uncertain,
         'localization': 'approximate_window'}
        for name in dict.fromkeys(names)
    ]


def parse_named(text, frames, window):
    value = json.loads(text)
    if not isinstance(value, dict) or not isinstance(value.get('actions'), list):
        raise ValueError('Expected named action object')
    codes = {name: code for code, (name, _) in ACTION_CODES.items()}
    if len(value['actions']) > 64:
        raise ValueError('Excessive action list')
    triples = []
    for item in value['actions']:
        if not isinstance(item, dict) or set(item) != {'action', 'first_frame', 'last_frame'} or item['action'] not in codes:
            raise ValueError('Unknown action name or fields')
        triples.append([codes[item['action']], item['first_frame'], item['last_frame']])
    # Some small models describe one continuous action once per sampled frame.
    # Validate every row, then coalesce only touching image-index intervals of
    # the same action. No observation is invented or dropped to meet a count cap.
    grouped = []
    for triple in sorted(triples):
        parse_compact(json.dumps({'actions': [triple], 'uncertain': value.get('uncertain', True)}), frames, window)
        if grouped and grouped[-1][0] == triple[0] and triple[1] <= grouped[-1][2] + 1:
            grouped[-1][2] = max(grouped[-1][2], triple[2])
        else:
            grouped.append(list(triple))
    return parse_compact(json.dumps({'actions': grouped, 'uncertain': value.get('uncertain', True)}), frames, window, max_actions=64)


def parse_compact(text, frames, window, max_actions=6):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) - {'actions', 'uncertain'}:
        raise ValueError('Expected compact action object')
    uncertainty = value.get('uncertain', True)
    if type(uncertainty) is not bool:
        raise ValueError('Uncertainty must be boolean')
    triples = value.get('actions')
    if not isinstance(triples, list) or len(triples) > max_actions:
        raise ValueError('Invalid action list')
    result, seen = [], set()
    for triple in triples:
        if not isinstance(triple, list) or len(triple) != 3 or any(type(v) is not int for v in triple):
            raise ValueError('Actions require three integer values')
        code, first, last = triple
        if code not in ACTION_CODES or not 1 <= first <= last <= len(frames):
            raise ValueError('Action or frame outside allowed range')
        if tuple(triple) in seen:
            continue
        seen.add(tuple(triple))
        action, label = ACTION_CODES[code]
        times = [f['time_sec'] for f in frames[first-1:last]]
        if any(not math.isfinite(t) or not window['start_sec'] <= t <= window['end_sec'] for t in times):
            raise ValueError('Support outside selected window')
        result.append({'action': action, 'label': label, 'start_sec': times[0], 'end_sec': times[-1],
                       'evidence': label, 'evidence_timestamps': times, 'supporting_windows': [window['index']],
                       'status': 'model_observation', 'human_verified': False, 'uncertain': uncertainty})
    return uncertainty, result


def sequence_view(actions):
    # Existing workflow treats this as its count stage; the new prompt permits both methods.
    return [{**a, 'action': 'machine_count' if a['action'] == 'cash_counted' else a['action']} for a in actions]


def merge_observations(actions):
    from sequence_core import merge_actions
    merged = merge_actions(actions)
    for row in merged:
        row['uncertain'] = any(a.get('uncertain', True) for a in actions
                               if a['action'] == row['action'] and
                               a['start_sec'] <= row['end_sec'] and a['end_sec'] >= row['start_sec'])
    return merged
