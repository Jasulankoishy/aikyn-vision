"""Conservative review candidates from sampled observations, without model imports.

An event here is a possible sign to inspect, never a confirmed violation. A
missing sampled action is a question, not proof that the action did not occur.
"""
import math


PUBLIC_CASH_RULE = {
    'id': 'NB231-P20',
    'document': 'Постановление Правления НБ РК от 29.11.2019 № 231',
    'section': 'п. 20, абзац 2',
    'source_url': 'https://adilet.zan.kz/rus/docs/V1900019680',
    'status': 'public_reference_conditional',
    'conditions': 'Применяется к ранее принятым наличным; нужно установить принадлежность суммы и стадию обслуживания.',
}
# Public paragraph text checked on 2026-10-18 against the official source:
# https://old.adilet.zan.kz/rus/docs/V1900019680/compare
# This verifies the reference, not cash ownership or a violation in any video.

QUESTIONS = {
    'identity_not_observed': ('Проверка документа', 'До приёма денег осмотр документа не замечен. Это не доказывает отсутствие идентификации: проверьте начало операции и возможный цифровой способ.', 'c04'),
    'count_not_observed': ('Пересчёт денег', 'Перед размещением денег пересчёт не замечен. Это не доказывает его отсутствие: проверьте всю операцию, ручной пересчёт и видимость аппарата.', 'c03'),
    'return_amount_unknown': ('Возврат денег', 'Замечен возврат денег. Кадры не устанавливают всю сумму, частичный возврат или основание операции; сам возврат не является нарушением.', None),
    'return_branch_needs_review': ('Возврат и уход клиента', 'После возврата клиент уходит. Полнота и основание возврата требуют проверки; полный возврат может быть допустимой веткой операции.', None),
    'departure_before_observed_completion': ('Завершение обслуживания', 'Клиент ушёл; завершение всех этапов по наблюдениям не установлено. Пропуск наблюдения не доказывает пропуск действия.', None),
    'next_client_before_observed_completion': ('Смена клиента', 'Начато обслуживание следующего клиента. Завершение предыдущей операции не установлено по наблюдениям; нужны видимые деньги и их связь с операцией.', None),
    'screen_lock_unverified': ('Состояние компьютера', 'После ухода кассира блокировка не подтверждена. Ранее видимый рабочий экран не устанавливает состояние экрана после ухода; нужен применимый порядок защиты.', 'c11'),
    'safe_open_at_count': ('Сейф при пересчёте', 'После открытия сейфа замечен пересчёт. Отсутствие замеченного закрытия не доказывает, что дверца оставалась открытой; нужен видимый одновременный кадр и применимый порядок.', 'c08'),
    'safe_close_unverified': ('Сейф после ухода', 'Кассир ушёл после открытия сейфа. Закрытие могло не попасть в выборку: проверьте состояние дверцы в момент ухода и применимый порядок.', 'c08'),
    'door_close_unverified': ('Дверь после ухода', 'Кассир ушёл после открытия двери. Закрытие могло не попасть в выборку: проверьте состояние двери и режим доступа.', 'c12'),
}

COARSE_MESSAGES = {
    'identity_not_observed': 'В анализируемых фрагментах приём денег отмечен, а проверка документа не зафиксирована. Это не доказывает её отсутствие: проверьте всю операцию и возможный цифровой способ.',
    'count_not_observed': 'В анализируемых фрагментах размещение денег отмечено, а пересчёт не зафиксирован. Это не доказывает его отсутствие; проверьте ручной пересчёт, аппарат и весь ход операции.',
    'return_amount_unknown': 'В фрагменте отмечен возврат денег; точный момент, полнота и основание возврата не установлены. Сам возврат не является нарушением.',
    'return_branch_needs_review': 'В наблюдениях есть возврат денег и уход клиента. Порядок внутри фрагмента, полнота и основание возврата не установлены; полный возврат может быть допустим.',
    'departure_before_observed_completion': 'В фрагменте отмечен уход клиента. Завершение операции и порядок действий внутри фрагмента не установлены; пропуск наблюдения не доказывает пропуск действия.',
    'next_client_before_observed_completion': 'В фрагменте отмечено обслуживание следующего клиента. Завершение предыдущей операции и связь денег с ней требуют проверки; порядок внутри фрагмента не установлен.',
    'screen_lock_unverified': 'В наблюдениях отмечены рабочий экран и уход кассира. Состояние экрана непосредственно при уходе не установлено; проверьте блокировку и применимый порядок защиты.',
    'safe_open_at_count': 'В наблюдениях отмечены открытый сейф и пересчёт. Порядок и одновременность не установлены; проверьте дверцу и применимый порядок работы.',
    'safe_close_unverified': 'В наблюдениях отмечены открытый сейф и уход кассира. Порядок и состояние дверцы непосредственно при уходе не установлены; требуется проверка.',
    'door_close_unverified': 'В наблюдениях отмечены открытая дверь и уход кассира. Порядок и состояние двери непосредственно при уходе не установлены; проверьте закрытие и режим доступа.',
}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def coarse(action):
    return action.get('evidence_kind') == 'sampled_window_context'


def common_windows(first, second):
    def ids(action):
        values = action.get('supporting_windows', [])
        return {v for v in values if type(v) is int and v >= 0} if isinstance(values, list) else set()
    return ids(first) & ids(second)


def build_findings(actions, sequence, duration):
    if not finite(duration) or duration <= 0:
        raise ValueError('A finite positive video duration is required')
    sequence = sequence if isinstance(sequence, dict) else {}
    observed, discarded = [], 0
    for action in actions:
        if not isinstance(action, dict):
            discarded += 1
            continue
        start, end = action.get('start_sec'), action.get('end_sec')
        supplied = action.get('evidence_timestamps', [])
        if (not all(finite(v) for v in (start, end)) or not 0 <= start <= end <= duration
                or not isinstance(supplied, list)):
            discarded += 1
            continue
        times = sorted({t for t in supplied if finite(t) and start <= t <= end})
        if not times:
            discarded += 1
            continue
        observed.append({**action, '_times': times})
    observed.sort(key=lambda a: (a['start_sec'], a['end_sec'], str(a.get('action', ''))))
    by_id = {a['id']: a for a in observed if isinstance(a.get('id'), str)}
    by_kind = {}
    for action in observed:
        by_kind.setdefault(action.get('action'), []).append(action)
    events, questions, event_keys, question_keys = [], [], set(), set()
    direct_pairs = set()

    def event(category, title, description, evidence, *, rule=None, timecode=None, approximate=False):
        times = sorted(set(evidence))
        if not times:
            return
        timecode = timecode if timecode in times else times[len(times)//2] if approximate else times[0]
        key = (category, title, timecode, tuple(times))
        if key in event_keys:
            return
        event_keys.add(key)
        result = {'type': title, 'category_id': category, 'timecode_sec': timecode,
                       'start_sec': times[0], 'end_sec': times[-1],
                       'description': description, 'evidence_timestamps': times,
                       'rule': dict(rule) if rule else None,
                       'rule_status': rule['status'] if rule else 'internal_rule_required',
                       'status': 'possible_sign_requires_review'}
        if approximate:
            result.update(localization='approximate_window',
                          interval={'start_sec': times[0], 'end_sec': times[-1]})
        events.append(result)

    def question(reason, action, category=None, message=None, title=None, operation=None):
        if action is None:
            return
        default = QUESTIONS.get(reason)
        if default:
            title, message, category = default
        if coarse(action):
            message = COARSE_MESSAGES.get(reason, message)
        if not title or not message:
            return
        # One question of each kind per provisional operation, or per actual frame.
        key = (reason, operation if operation is not None else action['_times'][0])
        if key in question_keys:
            return
        question_keys.add(key)
        result = {'type': title, 'timecode_sec': action['_times'][len(action['_times'])//2] if coarse(action) else action['_times'][0],
                          'message': message, 'category_id': category,
                          'status': 'requires_review', 'reason': reason,
                          'evidence_timestamps': action['_times']}
        if coarse(action):
            result.update(localization='approximate_window',
                          interval={'start_sec': action['_times'][0], 'end_sec': action['_times'][-1]})
        questions.append(result)

    # Combining two piles is directly observable. Ownership remains conditional.
    for action in by_kind.get('cash_mixed', []):
        text = ('Модель отметила объединение пачек наличных. Принадлежность разным клиентам не установлена: пачки могут относиться к одной операции. '
                'Пункт 20 применим, если объединены ранее принятые деньги с деньгами другого клиента; требуется проверка.')
        if coarse(action):
            text = ('В одном фрагменте модель отметила объединение пачек наличных. Точный момент и границы действия не установлены; '
                    'кадры показывают контекст фрагмента. Принадлежность разным клиентам не установлена: пачки могут относиться к одной операции. '
                    'Пункт 20 применим только при подтверждении ранее принятых денег другого клиента.')
        event('c02', 'Объединение пачек наличных — проверить принадлежность',
              text, action['_times'], rule=PUBLIC_CASH_RULE, approximate=coarse(action))

    # Shared real supporting frames are essential: an earlier opening plus a
    # missing closing observation is not evidence of an open object at departure.
    for kind, category, title, description in (
        ('safe_opened', 'c08', 'Открытие сейфа одновременно с уходом кассира',
         'Модель отметила открытие сейфа и уход кассира на общих кадрах. Проверьте, остаётся ли дверца открытой после ухода и находятся ли внутри ценности. '
         'Применимое правило немедленного закрытия не подтверждено; нужен порядок работы банка.'),
        ('door_opened', 'c12', 'Открытие двери одновременно с уходом кассира',
         'Модель отметила открытие двери и уход кассира на общих кадрах. Это может быть обычный выход. '
         'Проверьте последующее закрытие и режим доступа; нарушенный норматив по этим наблюдениям не установлен.'),
    ):
        for left in by_kind.get('cashier_left', []):
            for opened in by_kind.get(kind, []):
                if coarse(left) or coarse(opened):
                    if common_windows(left, opened):
                        subject = 'открытый сейф' if category == 'c08' else 'открытая дверь'
                        context = left if coarse(left) else opened
                        question('coarse_'+category+'_departure', context, category=category,
                                 title='Сейф и уход кассира' if category == 'c08' else 'Дверь и уход кассира',
                                 message=f'В одном фрагменте отмечены {subject} и уход кассира. Одновременность и порядок не установлены. '
                                         'Проверьте состояние в момент ухода и применимый порядок; нарушение по этим наблюдениям не установлено.')
                        direct_pairs.add((category, left.get('id')))
                    continue
                shared = sorted(set(left['_times']) & set(opened['_times']))
                if shared:
                    event(category, title, description, shared)
                    direct_pairs.add((category, left.get('id')))

    # Optional quick-inference action: directly visible cash remaining on the
    # counter. Merely not seeing cash_stored must never manufacture this state.
    for cash in by_kind.get('cash_left_on_counter', []):
        for kind, category, title, text in (
            ('next_client_started', 'c01', 'Наличные на столе при начале обслуживания следующего клиента',
             'Модель отметила наличные на столе и начало обслуживания следующего клиента на общих кадрах. '
             'Нужно установить, относятся ли деньги к предыдущему клиенту: наличные текущего клиента на столе допустимы. '
             'Пункт 20 применим к ранее принятым наличным.'),
            ('cashier_left', 'c06', 'Наличные на столе в момент ухода кассира',
             'Модель отметила наличные на столе в момент ухода кассира. Проверьте принадлежность денег, стадию операции и наличие другого ответственного работника. '
             'Пункт 20 применим к ранее принятым наличным; по этим кадрам нарушение окончательно не установлено.'),
        ):
            for trigger in by_kind.get(kind, []):
                approximate = coarse(cash) or coarse(trigger)
                if approximate and not common_windows(cash, trigger):
                    continue
                shared = sorted(set(cash['_times']) & set(trigger['_times']))
                if approximate and coarse(cash) != coarse(trigger):
                    # Mixed protocols still have only window-level localization;
                    # do not relabel one exact point as the whole coarse context.
                    shared = (cash if coarse(cash) else trigger)['_times']
                if shared:
                    description = text
                    event_title = title
                    if approximate:
                        other = 'начало обслуживания следующего клиента' if category == 'c01' else 'уход кассира'
                        event_title = 'Наличные на столе и '+other+' — проверить фрагмент'
                        description = (f'В одном фрагменте модель отметила наличные на столе и {other}. '
                                       'Одновременность и принадлежность денег не установлены. Кадры показывают контекст, а не точные границы события. '
                                       'Наличные текущего клиента на столе допустимы; пункт 20 применим только к ранее принятым деньгам. '
                                       'Проверьте последовательность, принадлежность суммы и наличие другого ответственного работника.')
                    event(category, event_title, description, shared, rule=PUBLIC_CASH_RULE, approximate=approximate)

    for check in sequence.get('checks', []):
        if not isinstance(check, dict):
            continue
        reason = check.get('rule')
        if reason not in QUESTIONS:
            # Database writes cannot be verified from keyboard motion. This is
            # explained once in limitations, not converted into repeated alerts.
            continue
        trigger = by_id.get(check.get('trigger_action_id'))
        if reason == 'identity_not_observed' and trigger and coarse(trigger):
            if any(common_windows(trigger, document) for document in by_kind.get('document_checked', [])):
                # Both are present somewhere in the window; sorting action IDs
                # cannot establish receipt before checking the document.
                continue
        if reason in {'safe_close_unverified', 'door_close_unverified'}:
            category = 'c08' if reason == 'safe_close_unverified' else 'c12'
            if (category, check.get('trigger_action_id')) in direct_pairs:
                continue
        if reason == 'count_not_observed' and trigger:
            if coarse(trigger) and any(common_windows(trigger, counted)
                                      for counted in by_kind.get('cash_counted', [])+by_kind.get('machine_count', [])):
                continue
            operation = next((t for t in sequence.get('transactions', [])
                              if t.get('id') == check.get('operation_id')), None)
            # A quick runner may provide the generic hand-or-machine count.
            # Suppress the question only when its support is wholly before
            # storage and inside this provisional operation.
            if operation and finite(operation.get('start_sec')):
                if any(operation['start_sec'] <= c['start_sec'] <= c['end_sec'] < trigger['start_sec']
                       for c in by_kind.get('cash_counted', [])):
                    continue
        question(reason, trigger, operation=check.get('operation_id'))

    events.sort(key=lambda x: (x['timecode_sec'], x['type']))
    questions.sort(key=lambda x: (x['timecode_sec'], x['type']))
    limitations = [
        'Результаты основаны на наблюдениях локальной модели и требуют проверки человеком; юридическое нарушение не подтверждается автоматически.',
        'Выборка кадров может пропустить короткое действие; отсутствие наблюдения не доказывает отсутствие действия.',
        'Ввод на компьютере не доказывает запись в банковской базе. Принадлежность денег и полномочия людей не определяются по внешности.',
        'Нормативная ссылка указывает проверяемое условие применения; дата видео и соответствующая редакция документа требуют сопоставления.',
    ]
    if sequence.get('coverage_gaps'):
        limitations.append('Есть необработанные окна: отсутствие событий не означает отсутствие нарушений на всей записи.')
    if any(coarse(a) for a in observed):
        limitations.append('Распознавание присутствия действий во фрагменте не устанавливает их порядок, одновременность или точные границы. Таймкод указывает реальный кадр контекста.')
    if discarded:
        limitations.append(f'Наблюдений без допустимых исходных временных опор исключено: {discarded}.')
    if len(events) > 20:
        limitations.append('Показаны первые 20 кандидатов; полный список превышает лимит результата.')
    if len(questions) > 40:
        limitations.append('Показаны первые 40 вопросов для проверки.')
    return {'events': events[:20], 'review_questions': questions[:40], 'limitations': limitations}
