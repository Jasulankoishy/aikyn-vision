"""Bounded observation and temporal confirmation schemas. No labels or GPU code."""
import json
import math

ROLE_GUIDANCE = ('Determine the employee from use of the fixed workstation and interactions with visitors. '
                 'Gender and a fixed left/right image position do not establish the employee role. '
                 'If the required role cannot be distinguished, mark that observation unclear. ')

FIELDS = {
    'document_checked': 'The cashier visibly examines an identity document, rather than just moving a small object.',
    'cash_received': 'A customer visibly hands banknotes to the cashier.',
    'cash_counted': 'Banknotes are actually counted by hand or a counting machine.',
    'cash_stored': 'Banknotes visibly enter a safe or cash drawer; moving them on the desk does not count.',
    'cash_returned': 'The cashier visibly hands banknotes to the customer.',
    'client_departed': 'The visitor in FRONT of the counter leaves after interacting with the employee; distinguish this from the employee leaving.',
    'safe_closed': 'An identifiable safe or cash-drawer door is visibly shut after use.',
    'next_client_started': 'TWO DISTINCT CUSTOMERS are served in succession by the same employee. The first customer arriving, or the same customer moving, is NOT a customer change.',
    'cash_left_on_counter': 'Banknotes are visibly resting on the counter.',
    'cashier_left': 'The EMPLOYEE BEHIND THE COUNTER walks away from the workstation. A customer leaving, turning towards a computer, reaching down, or a cropped/hidden employee does NOT count.',
    'cash_mixed': 'Two separately visible bundles of BANKNOTES are joined into one. Reordering/counting a single bundle or moving a card does NOT count.',
    'old_cash_at_client_change': 'Cash visibly persists on the counter while the SAME EMPLOYEE begins serving a SECOND DISTINCT CUSTOMER. An initial arrival or the same visitor moving does NOT count. Do not assume ownership.',
    'cash_unattended': 'The EMPLOYEE BEHIND THE COUNTER walks away and leaves the workstation empty with visible banknotes still on its counter. A CUSTOMER leaving or the employee turning/reaching does NOT count.',
    'safe_open_when_left': 'An identifiable safe door is visibly open when the cashier leaves. A room door is not a safe.',
    'screen_unlocked_when_left': 'A readable computer screen shows an active work session when the cashier leaves. An unreadable screen is unclear.',
    'room_door_left_open': 'The identifiable access door to the cashier ROOM remains open during continued activity instead of being closed after passage. An ordinary brief opening followed by closing is not this event. A safe/cabinet door or a counter opening is not a room access door. A person may remain outside the threshold: entry and access rights are NOT required and must not be inferred.',
}
RISK_KEYS = ('cash_mixed', 'old_cash_at_client_change', 'cash_unattended', 'safe_open_when_left', 'screen_unlocked_when_left', 'room_door_left_open')
CHECK_GROUPS = (
    ('document_checked', 'cash_received', 'cash_counted', 'cash_stored', 'cash_returned'),
    ('client_departed', 'safe_closed', 'next_client_started', 'cash_left_on_counter', 'cashier_left'),
    RISK_KEYS,
)
LABELS = {
    'document_checked': 'Осмотр документа', 'cash_received': 'Передача денег кассиру',
    'cash_counted': 'Пересчёт денег', 'cash_stored': 'Размещение денег в хранилище',
    'cash_returned': 'Передача денег клиенту', 'next_client_started': 'Смена клиента',
    'cash_left_on_counter': 'Наличные на столе', 'cashier_left': 'Уход кассира',
    'cash_mixed': 'Объединение пачек наличных',
    'client_departed': 'Уход клиента', 'safe_closed': 'Закрытие сейфа или кассового ящика',
}


class ChoiceGrammar:
    """Finite JSON alternatives. The model chooses; syntax cannot invent an option."""
    def __init__(self, tokenizer, choices):
        self.choices = choices
        self.root = {}
        self.eos = tokenizer.eos_token_id
        self.max_tokens = 0
        texts = [json.dumps(choice, separators=(',', ':'), ensure_ascii=False) for choice in choices]
        sequences = tokenizer(texts, add_special_tokens=False)['input_ids']
        for ids in sequences:
            self.max_tokens = max(self.max_tokens, len(ids)+1)
            node = self.root
            for token in ids: node = node.setdefault(token, {})
            node.setdefault(self.eos, {})

    def allowed(self, suffix):
        node = self.root
        for token in suffix:
            if token not in node: raise ValueError('Invalid constrained decoder state')
            node = node[token]
        return list(node) or [self.eos]


class ChecklistGrammar:
    """Independent ternary fields; no three-action cap or exponential enumeration."""
    def __init__(self, tokenizer, fields=FIELDS):
        names = list(fields)
        self.roots = []
        self.eos = tokenizer.eos_token_id
        self.max_tokens = 1
        for index, name in enumerate(names):
            alternatives = []
            for status in ('seen', 'not_seen', 'unclear'):
                text = ('{' if index == 0 else ',') + json.dumps(name) + ':' + json.dumps(status)
                if index == len(names)-1: text += '}'
                alternatives.append(text)
            root = {}; sequences = tokenizer(alternatives, add_special_tokens=False)['input_ids']
            self.max_tokens += max(map(len, sequences))
            for ids in sequences:
                node = root
                for token in ids: node = node.setdefault(token, {})
                node[None] = index+1
            self.roots.append(root)

    def allowed(self, suffix):
        stage = 0; node = self.roots[0]
        for token in suffix:
            if None in node:
                stage = node[None]
                if stage == len(self.roots):
                    if token == self.eos: return [self.eos]
                    raise ValueError('Extra tokens after checklist')
                node = self.roots[stage]
            if token not in node: raise ValueError('Invalid checklist decoder state')
            node = node[token]
        if None in node:
            stage = node[None]
            return [self.eos] if stage == len(self.roots) else list(self.roots[stage])
        return list(node)


def parse_checklist(text, fields=FIELDS):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != set(fields) or any(not isinstance(v,str) or v not in {'seen','not_seen','unclear'} for v in value.values()):
        raise ValueError('Invalid checklist; no conclusion may be issued')
    return value


def checklist_prompt(start, end, memory, overview=None, fields=FIELDS):
    return (
        f'Observe the CURRENT bank-workplace video interval {start:.2f} to {end:.2f} seconds, including the room entrance and access door. '
        + ROLE_GUIDANCE +
        'Answer each check independently. seen = clearly supported by current video; not_seen = not observed in this interval; unclear = ambiguous or hidden. '
        'not_seen never means the action did not happen. Do not read personal data or identify people. '
        'Objects on a desk are not automatically cash; handing a card over is not automatically examining it. '
        'Previous observations are UNVERIFIED context only, never evidence for a current action: '
        + json.dumps(memory, ensure_ascii=False, separators=(',', ':')) + '. '
        + ('Whole-video observations, also unverified: '+json.dumps(overview, separators=(',', ':'))+'. ' if overview else '')
        + 'Checks: '+json.dumps({key:FIELDS[key] for key in fields}, separators=(',', ':'))+'. '
        'Return a JSON OBJECT with these '+str(len(fields))+' keys in the same order. Each value must be seen, not_seen or unclear. '
        'Do not mark a check seen just because it appears in the checklist. No explanation.'
    )


def bounded_memory(windows, max_windows=4):
    # Omit negatives: absence in sparse samples cannot become an enduring state.
    return [{'start_sec': w['start_sec'], 'end_sec': w['end_sec'],
             'observed': [k for k,v in w['checks'].items() if v == 'seen']}
            for w in windows[-max_windows:]]


def risk_candidates(outcomes):
    """Keep each positive window as a proposal, including overlapping windows.

    A connected run of positive windows can contain several distinct episodes.
    Collapsing that run before localization silently loses all but one episode.
    The caller may deduplicate confirmed intervals after independent refinement.
    """
    result, seen = [], set()
    for kind in RISK_KEYS:
        for outcome in outcomes:
            if outcome['checks'][kind] != 'seen':
                continue
            key = (kind, outcome['index'], outcome['start_sec'], outcome['end_sec'])
            if key in seen:
                continue
            seen.add(key)
            result.append({'kind': kind, 'start_sec': outcome['start_sec'], 'end_sec': outcome['end_sec'],
                           'supporting_windows': [outcome['index']]})
    return sorted(result, key=lambda row:(row['start_sec'], RISK_KEYS.index(row['kind'])))


def source_bins(frames):
    """Native Qwen compresses two consecutive frames into each temporal patch."""
    if len(frames)<2: raise ValueError('Insufficient refinement frames')
    return [{'start_sec': frames[i]['time_sec'], 'end_sec': frames[min(i+1,len(frames)-1)]['time_sec']}
            for i in range(0,len(frames),2)]


def localization_choices(frames):
    bins=source_bins(frames)
    result=[{'status':'not_observed'},{'status':'unclear'}]
    for i,a in enumerate(bins):
        for b in bins[i:]:
            result.append({'status':'observed','start_sec':a['start_sec'],'end_sec':b['end_sec']})
    return result


def validate_localization(value, frames):
    if not isinstance(value,dict) or any(type(value.get(k)) not in (int,float) or not math.isfinite(value[k])
                                         for k in ('start_sec','end_sec') if k in value):
        raise ValueError('Invalid localized interval')
    if value not in localization_choices(frames):
        raise ValueError('Localization is not anchored to actual source frame pairs')
    return value


def action_observations(outcomes, frames):
    """Attach only actual source frames that were supplied to this model call."""
    result=[]
    source_times = {f['time_sec'] for f in frames
                    if type(f.get('time_sec')) in (int, float)
                    and math.isfinite(f['time_sec']) and f['time_sec'] >= 0}
    for w in outcomes:
        supplied = w.get('sampled_timestamps')
        if not isinstance(supplied, list):
            raise ValueError('Model input sampled_timestamps are required for observation evidence')
        times = sorted({t for t in supplied if type(t) in (int, float) and math.isfinite(t)
                        and t in source_times and w['start_sec'] <= t <= w['end_sec']})
        if not times and any(w['checks'].get(name) == 'seen' for name in LABELS):
            raise ValueError('Observed action has no actual model input source frames')
        for name,label in LABELS.items():
            if w['checks'][name]=='seen' and times:
                result.append({'action':name,'label':label,'start_sec':times[0],'end_sec':times[-1],
                               'evidence':label,'evidence_kind':'sampled_window_context',
                               'evidence_timestamps':times,'supporting_windows':[w['index']],
                               'human_verified':False,'uncertain':True,'status':'model_observation'})
    return result
