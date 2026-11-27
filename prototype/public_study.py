"""Research and source checks for the public teaching corpus."""
import json

from demo import sample_store
from funnel import FAMILIES, WINDOWS, delta

QUESTION = ("Индекс самостоятельных заказов Kaspersky изменился. "
            "Что проверить первым, чтобы различить неуспешное добавление и успешное добавление без записи события? "
            "Что чинить при каждом наблюдаемом исходе?")
CLAIMS = ("signal", "alternative", "customer", "counterexample", "limit")
BUSINESS_STEPS = ("impact", "effect")
ROLE_NAMES = {
    "signal": "показатель по выбранному продукту",
    "alternative": "альтернативная гипотеза",
    "customer": "свидетельство, поддерживающее вопрос",
    "counterexample": "наблюдение, ограничивающее обобщение",
    "limit": "предел доступных измерений",
}


def record(identifier, kind, title, text, source, roles=(), **fields):
    return dict(id=identifier, kind=kind, title=title, text=text, source=source,
                roles=list(roles), **fields)


def slot(label, choices, accepted):
    return dict(label=label, choices=choices, accepted=list(accepted))


def kes_case():
    sample = sample_store.build()
    rows = []
    for family in ("kes", "astra"):
        change = delta(sample["history"], family, "aug", "oct")
        series = sample["history"]["series"][family]
        before, after = series["aug"], series["oct"]
        rows.append(record("S-" + family, "BI", FAMILIES[family] + " · индекс самостоятельных заказов",
                           f'{WINDOWS["aug"]["label"]} и {WINDOWS["oct"]["label"]}: '
                           f'{change["before"]:.1f} → {change["after"]:.1f} ({change["change"]:+.1f}%). '
                           "Средние недельные индексы за два полных шестинедельных окна.",
                           f'Учебный магазин · продажи · строки {before[0]["row"]}–{before[-1]["row"]}, '
                           f'{after[0]["row"]}–{after[-1]["row"]}',
                           ("signal",) if family == "kes" else ("comparison",)))
    rows.append(record("E-cart", "Аналитика", "Покрытие события корзины",
                       "Для Kaspersky нет ряда регистраций добавления в корзину. "
                       "Учебный набор не связывает визит, действие, самостоятельный заказ и оплату.",
                       "Учебный магазин · Метрики · cfg_add_to_cart_rate", ("limit",)))
    for index, row in enumerate(sample["interviews"], 1):
        rows.append(record(f"I{index}", "Интервью", row["title"], row["text"], row["source"], row.get("study_roles", ())))
    for index, row in enumerate(sample["releases"], 1):
        rows.append(record(f"R{index}", "Релиз", row["title"], row["date"] + " · " + row["text"],
                           row["source"], row.get("study_roles", ())))
    for index, row in enumerate(sample["catalog"]["kes"]["prices"]["matched"], 1):
        rows.append(record(f"P{index}", "Конкурент", row["title"],
                           row["text"] + f' Один ценовой замер. Цена Store {row["store"]} ₽.', row["source"]))
    for row in sample["tasks"]:
        if row.get("product", "kes") != "kes":
            continue
        rows.append(record(row["id"], "Задача", row["title"], row["text"], row["source"],
                           mechanism=row.get("mechanism"), version=row["version"], address=row["record"]))
    return {"question": QUESTION, "rows": rows, "mechanism": "cart_event", "steps": kes_steps()}


def kes_steps():
    return {
        "test": slot("Первая проверка", {
            "replay": "Повторить добавление выбранной лицензии и в одной попытке зафиксировать товар в корзине и запись события.",
            "trend": "Сопоставить индексы вокруг даты релиза.",
            "survey": "Спросить покупателей об удобстве подбора.",
        }, ("replay",)),
        "failed": slot("Фактическое добавление не сработало", {
            "locate": "Воспроизвести и локализовать сбой добавления товара.",
            "events": "Переписать передачу события корзины.",
            "rollback": "Откатить весь релиз.",
        }, ("locate",)),
        "missing": slot("Добавление сработало, событие отсутствует", {
            "events": "Сверить журнал и исправить регистрацию события.",
            "ux": "Переделать интерфейс корзины.",
            "rollback": "Откатить весь релиз.",
        }, ("events",)),
        "passed": slot("Добавление и событие подтверждены", {
            "scope": "Зафиксировать успешную попытку для проверенного устройства и лицензии.",
            "events": "Сразу менять регистрацию события.",
            "rollback": "Откатить весь релиз.",
        }, ("scope",)),
        "impact": slot("Что сверка установит о заказах", {
            "unknown": "Сверка проверяет действие и его регистрацию в конкретной попытке. Изменение числа заказов и причина изменения индекса по ней не устанавливаются.",
            "loss": "Сверка установит, сколько самостоятельных заказов потеряно.",
            "cause": "Подтверждение действия и записи устанавливает влияние релиза на заказы.",
        }, ("unknown",)),
        "technical": slot("Критерий проверки исправления", {
            "paired": "На согласованных устройствах и лицензиях сверить ID попытки. Каждому успешному добавлению соответствует ровно одна запись.",
            "index": "Зафиксировать рост индекса после исправления.",
        }, ("paired",)),
        "effect": slot("Оценка бизнес-эффекта", {
            "bi": "Сравнить независимый индекс BI на сопоставимых полных неделях. Учесть смену входа и параллельные изменения. Без контроля причинный эффект неизвестен.",
            "interviews": "Использовать два интервью как базу сравнения эффекта.",
            "events": "Оценить изменение заказов по полноте записи события корзины.",
        }, ("bi",)),
    }



def enum(values):
    return {"type": "string", "enum": list(values)}


def schema(fields):
    return {"type": "object", "properties": {k: enum(v) for k, v in fields.items()},
            "required": list(fields), "additionalProperties": False}


def validate(raw, fields):
    if set(raw) != set(fields) or any(raw[key] not in choices for key, choices in fields.items()):
        raise ValueError("Ответ модели не соответствует схеме исследования.")


def select_evidence(call, case, rows):
    groups = {kind: [row["id"] for row in rows if row["kind"] == kind] for kind in {r["kind"] for r in rows}}
    select = {
        "signal": groups.get("BI", []) + groups.get("Аналитика", []) + ["none"],
        "alternative": groups.get("Релиз", []) + groups.get("Конкурент", []) + ["none"],
        "customer": groups.get("Интервью", []) + ["none"],
        "counterexample": groups.get("Интервью", []) + ["none"],
        "limit": groups.get("Аналитика", []) + ["none"],
    }
    catalogue = [{k: row[k] for k in ("id", "kind", "title", "roles")} for row in rows]
    planned = call("Отбор свидетельств",
                   "Выбери записи, которые стоит открыть для диагностики сигнала. "
                   "Укажи разные записи для опыта покупателя и контрпримера. Если записи для роли нет, укажи none. "
                   "Роли источников: " + json.dumps(ROLE_NAMES | case.get("role_names", {}), ensure_ascii=False) +
                   "\nВопрос: " + case["question"] + "\nКаталог: " + json.dumps(catalogue, ensure_ascii=False),
                   schema(select), 224)
    validate(planned, select)
    return planned


def diagnose(call, case, rows, on_open, opened_ids=None):
    by_id = {row["id"]: row for row in rows}
    planned = None
    if opened_ids is None:
        planned = select_evidence(call, case, rows)
        opened_ids = [identifier for identifier in dict.fromkeys(planned.values()) if identifier != "none"]
    if not opened_ids or len(set(opened_ids)) != len(opened_ids) or any(identifier not in by_id for identifier in opened_ids):
        raise ValueError("Нет допустимого набора открытых свидетельств.")
    opened = {identifier: by_id[identifier] for identifier in opened_ids}
    if on_open:
        on_open("Свидетельства для диагностики", list(opened.values()), len(rows))

    claim_fields = {role: case.get("claim_fields", {}).get(role, role) for role in CLAIMS}
    fields = {claim_fields[role]: [identifier for identifier, row in opened.items() if role in row["roles"]] + ["none"]
              for role in CLAIMS}
    roles = ROLE_NAMES | case.get("role_names", {})
    role_labels = {field: roles[role] for role, field in claim_fields.items()}
    grounding = ("В отдельном поле укажи источник факта о способе получения счёта у сопоставимого поставщика. "
                 "Условие получения счёта само по себе не объясняет продажи. "
                 if "invoice" in claim_fields.values() else "Альтернатива — гипотеза. ")
    business_steps = case.get("business_steps", BUSINESS_STEPS)
    steps = {key: item for key, item in case["steps"].items() if key not in business_steps}
    fields.update({key: list(item["choices"]) for key, item in steps.items()})
    options = {key: {"пункт": item["label"], "варианты": item["choices"]} for key, item in steps.items()}
    chosen = call("Диагностика и первая проверка",
                  "Дай план диагностики строго по открытым свидетельствам. "
                  "Для пяти тезисов назови ID открытой записи или none. " + grounding +
                  "Интервью описывает отдельное наблюдение. "
                  "Первой выбери проверку, исходы которой позволят различить причины и выбрать действие. "
                  "Для каждого исхода укажи работу команды по наблюдаемому результату. "
                  "Если покупательское действие не завершилось, отсутствие его записи не устанавливает "
                  "неисправность аналитики. Следуй смыслу каждой развилки. Выбери только варианты из схемы."
                  "\nВопрос: " + case["question"] +
                  ("\nСмысл полей: " + json.dumps(role_labels, ensure_ascii=False) if case.get("role_names") else "") +
                  "\nОткрытые записи: " + json.dumps(list(opened.values()), ensure_ascii=False) +
                  "\nВарианты решения: " + json.dumps(options, ensure_ascii=False),
                  schema(fields), 256)
    validate(chosen, fields)
    issues = []
    claims = {}
    for role in CLAIMS:
        field = claim_fields[role]
        source = opened.get(chosen[field])
        if not source or role not in source["roles"]:
            issues.append(f"Нет достаточного источника для поля «{roles[role]}».")
            continue
        text = source["text"]
        if field == "alternative":
            text += " Это основание для гипотезы. Причинная связь требует проверки."
        claim = {"text": text, "source": source["id"], "quote": source["text"]}
        if field != role:
            claim["label"] = roles[role]
        claims[role] = claim
    if chosen["customer"] == chosen["counterexample"]:
        issues.append("Опыт и контрпример должны ссылаться на разные наблюдения.")
    if not issues and chosen["test"] in steps["test"]["accepted"]:
        claims["next_action"] = steps["test"]["choices"][chosen["test"]]
    for key, item in steps.items():
        if chosen[key] not in item["accepted"]:
            issues.append(f"Пункт «{item['label']}» выходит за доказанный результат или допускает неверное решение.")

    if not issues:
        claims["branches"] = [{"label":steps[key]["label"], "text":steps[key]["choices"][chosen[key]]}
                              for key in ("failed", "missing", "passed")]
        claims["after_release"] = steps["technical"]["choices"][chosen["technical"]]
    return planned, list(opened.values()), chosen, issues, claims


def assess_business(call, case, opened):
    steps = {key: case["steps"][key] for key in case.get("business_steps", BUSINESS_STEPS)}
    source_roles = set(case.get("business_source_roles", ("signal", "limit")))
    options = {key: {"пункт": item["label"], "варианты": item["choices"]} for key, item in steps.items()}
    sources = [{k: row[k] for k in ("id", "title", "text")} for row in opened
               if source_roles & set(row["roles"])]
    fields = {key: list(item["choices"]) for key, item in steps.items()}
    chosen = call("Границы бизнес-вывода",
                  "Оцени отдельно, что результат диагностической сверки позволяет сказать о бизнес-показателе, "
                  "и каким способом затем измерить изменение этого показателя. "
                  "Учитывай доступные ряды и ограничения. Результат единичного воспроизведения относится к попытке. "
                  "Используй варианты только в пределах наблюдений источников."
                  "\nКонтекст: " + case.get("business_question", case["question"]) +
                  "\nИзмерения и ограничения: " + json.dumps(sources, ensure_ascii=False) +
                  "\nВарианты: " + json.dumps(options, ensure_ascii=False),
                  schema(fields), 224)
    validate(chosen, fields)
    issues = [f"Пункт «{item['label']}» не подтверждён измерениями."
              for key, item in steps.items() if chosen[key] not in item["accepted"]]
    if not sources:
        issues.append("Нет источников для оценки бизнес-результата.")
    return chosen, issues


def match_task(call, case, tasks, first_check, on_open):
    if not tasks:
        return "none", "none", "В учебном бэклоге нет записей.", []
    by_id = {row["id"]: row for row in tasks}
    candidates = [{"id": row["id"], "title": row["title"], "description": row["text"]} for row in tasks]
    for item, row in zip(candidates, tasks):
        if "status" in row:
            item["status"] = row["status"]
    if on_open:
        on_open("Бэклог по описаниям", tasks, len(tasks))
    fields = {"task": list(by_id) + ["none"]}
    reply = call("Сопоставление задачи",
                 "Сопоставь задачу только с уже выбранной первой проверкой. "
                 "Сверяй описание, наблюдаемый механизм и участок покупки. "
                 "Задача о выпуске функции или навигации сама по себе не подтверждает неисправность. "
                 "Если подходящего описания нет, укажи none."
                 "\nТема: " + case["question"] + "\nПервая проверка: " + first_check +
                 "\nБэклог: " + json.dumps(candidates, ensure_ascii=False),
                 schema(fields), 224)
    validate(reply, fields)
    raw = reply["task"]
    if raw == "none":
        return raw, raw, "В открытых описаниях подходящая задача не выбрана.", []
    source = by_id[raw]
    if source.get("mechanism") != case["mechanism"]:
        problem = "Описание задачи не подтверждает связь с проверяемым механизмом."
        return raw, "none", problem, [problem]
    return raw, raw, source["text"], []


def research(call, on_open=None, *, case=None, opened_ids=None):
    case = case or kes_case()
    rows = case["rows"]
    witnesses = [row for row in rows if row["kind"] != "Задача"]
    tasks = [row for row in rows if row["kind"] == "Задача"]
    plan, opened, diagnostic, issues, result = diagnose(call, case, witnesses, on_open, opened_ids)
    business, business_issues = assess_business(call, case, opened)
    issues.extend(business_issues)
    if not business_issues:
        impact = case["steps"]["impact"]
        result["business_conclusion"] = {"label": impact["label"], "text": impact["choices"][business["impact"]]}
        if "after_release" in result:
            methods = (case["steps"][key]["choices"][business[key]]
                       for key in case.get("business_steps", BUSINESS_STEPS) if key != "impact")
            result["after_release"] += " " + " ".join(methods)
    first_check = case["steps"]["test"]["choices"][diagnostic["test"]]
    raw_task, task, reason, task_issues = match_task(call, case, tasks, first_check, on_open)
    result.update(task=task, model_task=raw_task, task_reason=reason)
    return {"question": case["question"], "plan": plan, "opened": opened + tasks,
            "model_answer": {**diagnostic, **business, "task": raw_task}, "issues": issues,
            "task_issues": task_issues, "result": result}
