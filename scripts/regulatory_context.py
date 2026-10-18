"""Add curated legal context AFTER evidence validation, without changing detections.

No network, model calls, thresholds, candidate removal or generated citations.
The four rule fields survive the current Java DTO. Conditions are also included
in description so the existing frontend displays them without a frontend change.
"""

VERSION = "regulatory-context-v1"
CHECKED_ON = "2026-10-18"
SOURCE = "https://adilet.zan.kz/rus/docs/V1900019680"
DOCUMENT = ("Правила осуществления кассовых операций и операций по инкассации "
            "банкнот, монет и ценностей; постановление Правления НБ РК "
            "от 29.11.2019 № 231")

# Text of paragraph 20 checked in the rendered official Adilet document on
# CHECKED_ON. This checks the citation, not its applicability to any video.
CASH_STORAGE = (
    "Ранее принятые наличные должны храниться в предназначенном для них "
    "устройстве, закрывающемся на ключ: например, сейфе, металлическом шкафу "
    "или ящике стола. Требование не ограничивается только сейфом."
)
CATEGORIES = {
    "c01": {
        "title": "Ранее принятые наличные на столе при смене клиента",
        "public_rule": True,
        "conditions": (
            "Нужно установить, что на столе осталась именно ранее принятая сумма "
            "предыдущего клиента при обслуживании следующего. Наличные текущего "
            "клиента на столе сами по себе не подтверждают нарушение."
        ),
    },
    "c02": {
        "title": "Объединение наличных разных операций",
        "public_rule": True,
        "conditions": (
            "Нужно подтвердить, что объединены ранее принятые деньги с деньгами "
            "другого клиента. Объединение пачек одной операции само по себе "
            "не устанавливает нарушение; пункт 20 не является общим запретом "
            "на объединение любых пачек."
        ),
    },
    "c06": {
        "title": "Наличные на столе при уходе кассира",
        "public_rule": True,
        "conditions": (
            "Для пункта 20 необходимо установить, что это ранее принятые наличные. "
            "Нужно проверить стадию операции и наличие другого ответственного "
            "работника; уход человека или деньги на столе по отдельности "
            "не устанавливают оставление денег без присмотра."
        ),
    },
    "c08": {
        "title": "Открытый сейф при уходе кассира",
        "public_rule": False,
        "conditions": (
            "Нужно установить тип устройства, наличие ценностей, доступ к ним "
            "и состояние дверцы после ухода. Конкретный пункт внутреннего "
            "порядка банка о закрытии этого устройства не предоставлен. "
            "Открытая дверца сама по себе не устанавливает нарушение закона."
        ),
    },
    "c11": {
        "title": "Рабочий экран после ухода кассира",
        "public_rule": False,
        "conditions": (
            "Нужны состояние сеанса после ухода и применимая политика банка "
            "о блокировке рабочего места. Конкретный пункт внутреннего "
            "регламента не предоставлен. Видимое изображение на мониторе "
            "не доказывает, что сеанс разблокирован."
        ),
    },
    "c12": {
        "title": "Дверь помещения остаётся открытой во время работы",
        "public_rule": False,
        "conditions": (
            "Нужно установить назначение помещения, состояние двери "
            "и применимый режим доступа. Конкретный пункт внутреннего "
            "регламента банка не предоставлен. Само открытое положение "
            "двери не устанавливает нарушение закона."
        ),
    },
}

# Additional categories in the team catalogue. Registering a category here does
# not claim the active model can detect it and never creates a new candidate.
CATEGORIES.update({
    "c03": {
        "title": "Приём наличных без видимого пересчёта", "public_rule": True,
        "section": "п. 19, подп. 2); п. 20, абзац 1", "rule_id": "NB231-P19-2-P20-1",
        "summary": "При обычном приёме наличные пересчитываются и проверяются в присутствии клиента.",
        "conditions": "Отсутствие пересчёта в выбранных кадрах не доказывает его отсутствие. Проверить всю операцию, ручной или машинный пересчёт. Приём инкассаторских сумок имеет отдельный порядок и не требует автоматически немедленного вскрытия каждой сумки.",
    },
    "c04": {
        "title": "Приём без видимой идентификации клиента", "public_rule": True,
        "section": "п. 19, подп. 1)", "rule_id": "NB231-P19-1",
        "summary": "При внесении наличных проводится визуальная идентификация по документу либо данным сервиса цифровых документов.",
        "conditions": "Нужно установить обычный приём наличных от клиента и проверить начало операции. Проверка могла быть ранее или через цифровые документы. Отсутствие физического удостоверения в кадре не доказывает отсутствие идентификации; для инкассации предусмотрен отдельный порядок.",
    },
    "c05": {
        "title": "Пересчёт принимаемых денег после ухода клиента", "public_rule": True,
        "section": "п. 20, абзац 1; п. 19, подп. 2)", "rule_id": "NB231-P20-1",
        "summary": "Обычный приём и пересчёт наличных выполняются в присутствии клиента.",
        "conditions": "Нужно связать сумму с конкретным приёмом и установить фактический уход клиента. Повторный внутренний пересчёт после завершённого обслуживания или пересчёт инкассации не равнозначны первичному приёму без клиента.",
    },
    "c07": {
        "title": "Непрозрачный пакет оставлен без присмотра", "public_rule": False,
        "conditions": "Содержимое непрозрачного пакета неизвестно. Сначала установить, содержит ли он наличные или ценности, и наличие ответственного работника. Пункт 20 Правил № 231 относится к ранее принятым наличным, пункт 80 — к порядку обращения с ценностями; автоматически считать пакет деньгами нельзя.",
        "related_source": SOURCE,
    },
    "c09": {
        "title": "Ключ оставлен в замке сейфа", "public_rule": True,
        "section": "п. 80", "rule_id": "NB231-P80-KEYS",
        "summary": "Порядок обращения с ключами устанавливается внутренними документами банка и должен исключать их несанкционированное использование.",
        "conditions": "Нужно проверить тип замка, доступность ключа посторонним и конкретный порядок банка. Пункт 80 не устанавливает универсальный запрет оставлять любой ключ в любом замке. Пункт 76 относится именно к ключам двери кладовой или сейфовой комнаты, а не любого отдельного сейфа.",
    },
    "c10": {
        "title": "Документы или печати оставлены после ухода", "public_rule": True,
        "section": "п. 80 — для печатей и перечисленных ценностей", "rule_id": "NB231-P80-SEALS",
        "summary": "Банк определяет порядок хранения и передачи печатей и перечисленных ценностей, исключающий несанкционированное использование.",
        "conditions": "Нужно установить вид предмета и доступ других лиц. Пункт 80 не требует хранить любую бумагу в сейфе. Для документов с защищаемой информацией связанным основанием служит п. 76, подп. 1) Требований АРРФР от 03.04.2026 № 53: нужны содержание документов и ограничения банка.",
        "related_source": "https://adilet.zan.kz/rus/docs/V2600038336",
    },
    "c13": {
        "title": "Личные вещи в кассовом узле", "public_rule": True,
        "section": "п. 12", "rule_id": "NB231-P12",
        "summary": "Личные вещи, деньги и ценности работников хранятся вне кассового узла. Предусмотрены исключения для лекарств, медицинских изделий и средств связи без фото- и видеофиксации.",
        "conditions": "Нужно подтвердить границы кассового узла, личное назначение предмета и дату события. Для телефона требуется установить его функции. Отдельный запрет напитков этим пунктом автоматически не устанавливается; проверьте внутренний порядок.",
    },
    "c14": {
        "title": "Повторное объединение отделённых аппаратом купюр", "public_rule": True,
        "section": "п. 19, подп. 2); пп. 57–58", "rule_id": "NB231-P19-2-57-58",
        "summary": "При приёме наличных проверяются подлинность и платежность; порядок проверки зависит в том числе от валюты.",
        "conditions": "Отделение купюр аппаратом может иметь техническую причину. Нужны сообщение аппарата, причина отделения и выполненные проверки. Отсутствие видимой УФ-проверки не означает отсутствие проверки; разделение пачки не доказывает подделку. Специальные процедуры сомнительных банкнот применяются после установления соответствующих признаков.",
    },
})
CATEGORIES["c08"]["conditions"] += (" Связанный пункт 20, абзац 2 Правил № 231 касается "
    "ранее принятых наличных и не является общим запретом открывать сейф во время операции.")
CATEGORIES["c08"]["related_source"] = SOURCE
CATEGORIES["c11"]["conditions"] += (" Справочно: п. 71, подп. 9) Требований АРРФР от "
    "03.04.2026 № 53 предусматривает автоматическое завершение сеанса или блокировку "
    "при неактивности более 30 минут; исключения — п. 72. Короткое видео само по себе "
    "не подтверждает превышение этого срока.")
CATEGORIES["c11"]["related_source"] = "https://adilet.zan.kz/rus/docs/V2600038336"
CATEGORIES["c12"]["conditions"] += (" Справочно: п. 8 и п. 16, подп. 1) Правил "
    "НБ РК от 24.02.2020 № 14 устанавливают требования к изоляции входа "
    "и оборудованию двери замком. Это требования к устройству помещений; "
    "они не доказывают запрет любого открытого положения двери. "
    "Для пункта 16 нужно учитывать временную редакцию до 01.01.2027.")
CATEGORIES["c12"]["related_source"] = "https://adilet.zan.kz/rus/docs/V2000020075"
CATEGORIES["c06"]["conditions"] += (" Пункт 22 Правил № 231 отдельно запрещает "
    "уход кассира до завершения обслуживания клиента; он применим только "
    "при подтверждении незавершённого обслуживания.")


def enrich_regulatory_context(result):
    """Return a new result with conditional references for existing candidates.

    Input must already have passed the evidence contract. This helper does not
    certify perception, create events, or treat legal context as evidence.
    Uncatalogued citations are not trusted, including citations from a model.
    """
    enriched = []
    for source_event in result["violations"]:
        event = dict(source_event)
        category = CATEGORIES.get(event.get("category_id"))
        description = event.get("description", "")
        previous = event.get("regulatory_context")
        if isinstance(previous, dict) and previous.get("version") == VERSION:
            suffix = previous.get("display_text")
            if isinstance(suffix, str) and suffix and description.endswith(suffix):
                description = description[:-len(suffix)]
        if category and category["public_rule"]:
            section = category.get("section", "п. 20, абзац 2")
            rule = {
                "id": category.get("rule_id", "NB231-P20"),
                "document": DOCUMENT,
                "section": section + " — возможное основание; применимость не установлена",
                "source_url": SOURCE,
            }
            explanation = ("Возможное основание: " + section + " Правил № 231. "
                           + category.get("summary", CASH_STORAGE) + " " + category["conditions"])
            status = "public_reference_conditional"
        else:
            rule = None
            status = ("content_unverified" if event.get("category_id") == "c07" else
                      "internal_rule_required" if category else "unmapped")
            explanation = (category["conditions"] if category else
                           "Для этой категории в проверенном каталоге нет "
                           "нормативного основания. Статья или пункт не назначены.")
        display_text = ("\n\nНормативный контекст: " + explanation
                        + " Юридическое нарушение автоматически не установлено.")
        related_source = category.get("related_source") if category else None
        if related_source:
            display_text += " Связанный официальный источник (справочно): " + related_source
        if rule or related_source:
            display_text += " Необходимо сопоставить дату события и действовавшую редакцию правил."
        event.update(
            description=description + display_text,
            rule=rule,
            rule_status=status,
            regulatory_context={
                "version": VERSION,
                "category_title": category["title"] if category else None,
                "status": status,
                "source_checked_on": CHECKED_ON if rule or related_source else None,
                "related_source_url": related_source,
                "applicability_established": False,
                "legal_violation_established": False,
                "display_text": display_text,
            },
        )
        enriched.append(event)
    analysis = dict(result["analysis"])
    analysis["regulatory_context"] = {
        "version": VERSION,
        "scope": "catalog_information_only",
        "source_checked_on": CHECKED_ON,
        "legal_violation_established": False,
    }
    return {**result, "violations": enriched, "analysis": analysis}
