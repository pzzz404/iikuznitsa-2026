"""Run source-led research over the protected store projection."""
import json
from datetime import date, timedelta

import funnel
from growth_research import respond, schema, search, string, plain, words
from store_history import sales_basis
from workflow import digest, now

QUESTIONS = {
    "kes": "Что проверить первым, чтобы различить сбой подбора Kaspersky, потерю события корзины и переход к менеджеру?",
    "office": "Какое решение принять по предложению Office Home and Business 2024: проверить цену, выставление счёта или сначала собрать экономику?",
}
MATCH_FORMAT = 6
TASK_FOCUS = "Сбой выбора или добавления в корзину либо ошибка передачи событий электронной торговли."
GROUPS = {
    "kes": {"customers": ("interview", "Опыт покупателей и контрпример"), "price": ("competitor", "Проверка цены"),
            "events": ("release", "События и их охват"), "data": ("metrics", "Покрытие чисел"),
            "tasks": ("backlog", "Существующие задачи")},
    "office": {"prices": ("competitor", "Сопоставимые предложения"), "exceptions": ("exclusion", "Исключения из ценового сравнения"),
               "constraints": ("metrics", "Ограничения и экономика"),
               "invoice": ("service", "Путь самостоятельного счёта")},
}
CHECKS = {
    "kes": {
        "path": ("Воспроизвести путь до корзины",
                 "Для Standard, Advanced и Cloud на компьютере и телефоне записать выбранную лицензию и содержимое корзины. "
                 "Сохранить шаг, на котором повторяется отказ, и соответствующее событие."),
        "event": ("Сверить действие и событие",
                  "Для Standard, Advanced и Cloud на компьютере и телефоне сверить идентификатор выбранной лицензии, "
                  "содержимое корзины и запись события. Для каждого успешного пополнения корзины должна быть ровно одна запись."),
        "channel": ("Сверить самостоятельный и менеджерский каналы",
                    "Запросить недельные числа заказов KES по обоим каналам за согласованные окна. "
                    "Проверить полноту и правила отнесения, затем сопоставить самостоятельный, менеджерский и общий ряды."),
    },
    "office": {
        "price": ("Перепроверить сопоставимое предложение Office",
                  "Обновить цены EP2-06605 для бессрочной лицензии на один ПК. До пилота согласовать минимальную маржу, "
                  "долю оплат на подходящие заказы, окно измерения и условие остановки."),
        "invoice": ("Проверить путь от счёта до оплаты Office",
                    "Связать артикул, выставленный счёт и оплату по идентификатору. Зафиксировать покрытие, долю оплат "
                    "и количество заказов с участием менеджера до изменения предложения."),
        "data": ("Собрать экономику предложения Office",
                 "Запросить закупочную цену, текущую сопоставимую цену, минимальную маржу и ряд оплат по артикулу. "
                 "Согласовать предел изменения цены до пилота."),
    },
}
FOLLOWUP = {
    "kes": "После исправления сверить действие и событие. После дозревания четырёх недель сравнить скользящий индекс KES с выбранной дорелизной базой, рядом проверить Astra и каналы, если BI предоставит связку.",
    "office": "После согласованного пилота сравнить долю оплат и маржу с зафиксированным базовым уровнем. При недоступных исходах сохранить статус «Ждём данные».",
}


def corpus(store, key, params):
    item = store["catalog"][key]
    prices = item["prices"]
    if key == "office":
        records = ([*prices["matched"], *({**row,"kind":"exclusion"} for row in prices["partial"]),
                    {**item["invoice"], "kind":"service"},
                    {**store["initiatives"]["office"], "kind":"metrics"},
                    {**store["definitions"]["family_orders_idx"], "text":
                     "Продажи v17 содержат индексы самостоятельных заказов Kaspersky и Astra. "
                     "Оплаты, закупочная цена и маржа по артикулу Office недоступны.", "kind":"metrics"}])
    else:
        tally = funnel.report(store["history"], params)
        windows = [funnel.WINDOWS[params[k]] for k in ("before","after")]
        records = [*store["interviews"], *prices["matched"], *prices["partial"]]
        records += [event for event in store["releases"] if any(word in (event["metrics"] or "")
                    for word in ("cfg", "lk_home_views"))]
        records += [{**task, "task_id": task["id"]} for task in store["tasks"]]
        for family, change in tally["orders"].items():
            basis = sales_basis(store, family, windows)
            if change:
                basis["text"] = (f"{funnel.FAMILIES[family]}: {change['before']:.2f} → {change['after']:.2f} "
                                 f"({change['change']:+.2f}%). " + basis["text"])
            records.append({**basis, "kind":"metrics"})
        definitions = store["definitions"]
        reach = tally["pairs"]["after"].get("cfg_reach_rate")
        if reach and not store.get("demo"):
            end = (date.fromisoformat(windows[1]["start"]) + timedelta(weeks=windows[1]["weeks"])).isoformat()
            days = [row for day,entries in store["reach_rows"].items() if windows[1]["start"] <= day < end
                    for row in entries]
            records.append({**definitions["cfg_reach_rate"], "title":"Выбрали хотя бы одну опцию Kaspersky",
                            "source":f'{store["book"]} · Метрики_данные · cfg_reach_rate · строки {min(days)}–{max(days)}',
                            "text":f'{reach["n"]} визитов с выбранной опцией из {reach["d"]} визитов страниц. '
                                   f'{reach["rows"]} из {reach["expected_rows"]} сочетаний день × устройство.'})
        records += [{**definitions["cfg_add_to_cart_rate"],
                     "text":funnel.MISSING_CART + " " + (definitions["cfg_add_to_cart_rate"]["note"] or "")}]
        records += [{**definitions["family_orders_idx"], "text":
                     "BI содержит только самостоятельные заказы. Ряда менеджерского канала и общего ключа визита и заказа нет."}]
    return [{**record, "id": f"C{i:02}"} for i, record in enumerate(records,1)]


def make_case(store, key, params, base=None):
    rows = corpus(store, key, params)
    return {**(base or {}), "finding": key, "format": MATCH_FORMAT if key == "kes" else 1, "corpus_version": digest(rows),
            "question": QUESTIONS[key], "filter": params, "stage": "order" if key == "kes" else "offer",
            "scope": base["scope"] if base else {"этап":"Выбор предложения", "семейство":store["catalog"][key]["title"]}}


def enum(values):
    return {"type": "string", "enum": values}


def task_evidence(task):
    body = task["text"].lower()
    return {
        "telemetry": "событи" in body and any(stem in body for stem in ("переда", "метрик", "запис", "аналитик")),
        "purchase": "корзин" in body and any(stem in body for stem in (
            "не добав", "не попада", "сбой добавл", "ошибка добавл", "не помещ")),
    }


def task_signals(task, family):
    """Find explicit terms for scope, a defect and the affected action in the source."""
    description = (task["title"] + " " + task["text"]).lower()
    scope = words(family) & words(description)
    defect = any(stem in description for stem in ("ошиб", "недоч", "сбой", "потер", "пропада",
                                                "не доход", "не переда", "не добав", "не работа"))
    return bool(scope), defect, any(task_evidence(task).values())


def task_fit(task, family):
    return all(task_signals(task, family))


def support_type(row, connect, daily_limit, run_id, scenario):
    return respond(connect, daily_limit, run_id, "Проверка основания",
                   "В записи описана неисправность. Какой тип проверки поддерживает именно эта запись? "
                   "telemetry — передача или учёт событий. purchase — фактический сбой выбора и добавления товара. "
                   "none — данных в записи недостаточно. Выбери один тип по тексту.\n"
                   f'{row["title"]}\n{row["text"]}\n'
                   "Определи предмет описанного дефекта, без оценки причины падения заказов.",
                   schema({"basis": enum(["telemetry", "purchase", "none"])}),
                   lambda reply: plain(reply["basis"], 15), 35, scenario)


def match_task(opened, case, connect, daily_limit, run_id, scenario):
    tasks = {row["task_id"]: row for row in opened.values() if row["kind"] == "backlog"}
    if not tasks:
        return {"status": "none", "reason": "По этому запросу нет доступной записи бэклога."}
    family = case["scope"]["семейство"]
    keys = [*tasks, "none"]
    entries = []
    for row in tasks.values():
        scope, defect, signals = ("да" if flag else "нет" for flag in task_signals(row, family))
        entries.append(f'{row["task_id"]} | {row["title"]}\n{row["text"]}\n'
                       f'Совпадения терминов: семейство — {scope}, дефект — {defect}, действие или запись — {signals}.')

    def validate(reply):
        selected = reply["task"]
        reason = plain(reply["reason"], 330)
        if selected not in keys:
            raise ValueError("Модель указала непрочитанную задачу.")
        if selected == "none":
            return {"status": "none", "model_task": "none", "reason": reason}
        row = tasks[selected]
        model = {"model_task": selected, "model_record": row["id"], "model_reason": reason}
        if not task_fit(row, family):
            return {**model, "status": "none",
                    "reason": "В открытом описании нет прямого основания связать проверку с этой задачей."}
        return {**model, "status": "selected", "record_id": row["id"],
                "task_id": row["task_id"], "source": row["source"], "address": row["record"],
                "version": row["version"], "quote": row["text"]}

    prompt = (f"Найди задачу для проверки отклонения заказов {family}. Ищем {TASK_FOCUS}\n"
              + "\n\n".join(entries) +
              f"\nСначала reason: по-русски объясни, описана ли ошибка именно в {family} и в чём она. "
              "Слова о магазине, меню или штатной работе сами по себе не подходят. "
              "Затем task: номер описанной задачи. Если ни одна строка не описывает эту ошибку, task=none. "
              "Признаки терминов помогают найти выдержку. Смысл оцени по полному описанию.")
    selected = respond(connect, daily_limit, run_id, "Сопоставление задачи", prompt,
                       schema({"reason": string(), "task": enum(keys)}), validate, 160, scenario)
    if selected["status"] != "selected":
        return selected
    row = tasks[selected["task_id"]]
    basis = support_type(row, connect, daily_limit, run_id, scenario)
    reasons = {
        "telemetry": "В описании указана ошибка передачи событий. Задача подходит для сверки события с действием.",
        "purchase": "В описании указан дефект покупательского действия. Задача подходит для воспроизведения сбоя.",
    }
    if not task_evidence(row).get(basis):
        return {"status": "none", "model_task": selected["model_task"], "model_reason": selected["model_reason"],
                "model_basis": basis, "reason": "Qwen не подтвердила связь по открытому описанию."}
    return {**selected, "status": "matched", "model_basis": basis, "reason": reasons[basis]}


def synthesize(case, run_id, store, connect, daily_limit):
    key = case["finding"]
    rows = corpus(store, key, case["filter"])
    if digest(rows) != case["corpus_version"]:
        raise ValueError("Версия материалов обновилась. Запустите исследование из карточки.")
    scenario = "Воронка · " + ("Kaspersky" if key == "kes" else "Office")
    groups = GROUPS[key]
    question = case["question"]
    names = " ".join(f"{name}: {labels[1]}." for name, labels in groups.items())

    def operation_batch(operations):
        with connect() as db:
            db.executemany("INSERT INTO radar_operations(run,at,payload) VALUES (?,?,?)",
                           [(run_id, now(), json.dumps(op, ensure_ascii=False)) for op in operations])

    with connect() as db:
        saved = [json.loads(row[0]) for row in db.execute(
            "SELECT payload FROM radar_operations WHERE run=? ORDER BY id", (run_id,))]
    previous_queries = [op["query"] for op in saved if op["op"] == "search"]
    if previous_queries:
        queries = dict(zip(groups, previous_queries, strict=True))
    else:
        queries = respond(connect, daily_limit, run_id, "Поисковые запросы",
                          "Дай конкретные поисковые запросы на русском, 2–5 ключевых слов по вопросу. "
                          "Ищи также опровержения. Для tasks запроси конкретный сбой или пропавшее событие для этого семейства. "
                          + names + " Вопрос: " + question,
                          schema({name:string() for name in groups}),
                          lambda reply:{name:plain(reply[name],100) for name in groups}, 150, scenario)
    hits, candidates, operations = {}, {}, []
    for group, (kind,label) in groups.items():
        eligible = [r for r in rows if r["kind"] == kind]
        context = question + (" " + TASK_FOCUS if kind == "backlog" else "")
        found = search(eligible, kind, queries[group], context)
        fallback = not found
        if kind == "backlog" and len(eligible) <= 8:
            found += [row for row in eligible if row not in found]
        elif fallback:
            found = eligible[:4]
        hits[group] = [[row["id"], row["title"], row["text"][:130 if kind == "backlog" else 86]] for row in found]
        candidates.update((row["id"],row) for row in found)
        operations.append({"op":"search","purpose":label,"type":kind,"query":queries[group],"searched":len(eligible),
                           "hits":[row["id"] for row in found],"fallback":fallback})
        if kind == "backlog":
            operations[-1]["task_hits"] = [row["task_id"] for row in found]
    if not previous_queries:
        operation_batch(operations)

    opened = {op["record"]["id"]:op["record"] for op in saved if op["op"] == "open"}
    if not any(row["kind"] != "backlog" for row in opened.values()):
        options = {group:[hit[0] for hit in hits[group]] or ["none"] for group in groups if group != "tasks"}
        if key == "kes":
            ids = options.pop("customers")
            options = {"contrast":[f"{a}/{b}" for a in ids for b in ids if a != b] or [f"{ids[0]}/none"], **options}
        def opened_ids(result):
            chosen = []
            for group, ids in options.items():
                if result[group] not in ids:
                    raise ValueError("Модель выбрала запись вне результатов поиска.")
                chosen.extend(item for item in result[group].split("/") if item != "none")
            return list(dict.fromkeys(chosen))
        chosen = respond(connect, daily_limit, run_id, "Выбор записей",
                         "Выбери, какие полные записи открыть, по одному ID на группу. "
                         "contrast — два разных ID из customers через /: полезный опыт и контрпример. "
                         "Нужны прямые наблюдения по вопросу и ограничения. "
                         "Вопрос: " + question + "\nСовпадения: " +
                         json.dumps({group: rows for group, rows in hits.items() if group != "tasks"}, ensure_ascii=False),
                         schema({name:enum(ids) for name,ids in options.items()}), opened_ids, 135, scenario)
        new_records = {identifier: candidates[identifier] for identifier in chosen}
        operation_batch([{"op":"open","record":record} for record in new_records.values()])
        opened.update(new_records)
    checks = list(CHECKS[key])
    pairs = [a + "/" + b for a in opened for b in opened if a != b]
    if not pairs:
        raise ValueError("Для решения нужны две разные прочитанные записи.")

    def assessment(reply):
        if reply["check"] not in checks or reply["pair"] not in pairs:
            raise ValueError("Нужны два разных открытых основания.")
        basis, counter = reply["pair"].split("/")
        return {"check":reply["check"], "basis":basis, "counter":counter}

    decision = respond(connect, daily_limit, run_id, "Синтез",
                       "Выбери одну проверку, которая лучше всего поможет принять решение. "
                       "pair — две разные открытые записи через /: основание и ограничение. "
                       "Выбор проверки: " + ", ".join(f"{k} = {v[0]}" for k,v in CHECKS[key].items()) +
                       ". Открытые записи, ID, тип, заголовок и выдержка: " +
                       json.dumps([[r["id"],r["kind"],r["title"],r["text"][:260]] for r in opened.values()],ensure_ascii=False) +
                       "\nВопрос: " + question,
                       schema({"check":enum(checks), "pair":enum(pairs)}), assessment, 125, scenario)
    match = None
    if key == "kes":
        # Pass complete search results so a weak preview choice cannot rule out a relevant task.
        task_rows = {identifier: candidates[identifier] for identifier, *_ in hits["tasks"][:4]}
        new_tasks = [row for identifier, row in task_rows.items() if identifier not in opened]
        if new_tasks:
            operation_batch([{"op": "open", "record": row} for row in new_tasks])
        opened.update(task_rows)
        match = match_task(task_rows, case, connect, daily_limit, run_id, scenario)
    action, criterion = CHECKS[key][decision["check"]]
    record = {"id":run_id,"topic":"funnel","stage":case["stage"],"finding":key,"scope":case["scope"],
              "question":question,"evidence":list(opened.values()),"selected":[decision["basis"],decision["counter"]],
              "assessment":decision, "action":action,"criterion":criterion,"followup":FOLLOWUP[key],
              "historical_result":funnel.NO_RELEASE_RESULT if key == "kes"
              else "Исторические цены и счёт не дают исходов оплаты и маржи после пилота."}
    if key == "kes":
        record["task_match"] = match
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO studies VALUES (?,?)",(run_id,json.dumps(record,ensure_ascii=False)))
