"""Opt-in loopback research over aggregated BI and a short backlog projection."""
import json
from pathlib import Path
from statistics import mean

import funnel
from growth_research import plain, respond
from workflow import digest, now


def projection(store):
    # Only this projection is installed on the invited stand. Never install the importer's full export.
    days = set(funnel.days_in(funnel.WINDOWS["aug"]) + funnel.days_in(funnel.WINDOWS["oct"]))
    weeks = [{k:r[k] for k in ("date", "row", "value", "partial")} for r in store["sales"]["kes"] if r["date"] in days]
    if len(weeks) != 12 or any(r["partial"] for r in weeks):
        raise ValueError("Нужны два полных шестинедельных окна Kaspersky.")
    eligible = [r for r in store["tasks"] if r["kind"] == "backlog"]
    fields = ("id","source_id","record","kind","book","version","source","sheet","title","text","status","type")
    tasks = [{k:r[k] for k in fields} for r in eligible]
    d = store["definitions"]["family_orders_idx"]
    definition = {k:d[k] for k in ("id","record","kind","book","version","source","sheet","title","text","type")}
    return {"format":"kes-excel-v1","book":store["book"], "version":store["version"],
            "sales":{"kes":weeks},"definitions":{"family_orders_idx":definition},"tasks":tasks}


def apply_projection(sample, data):
    if data.get("format") != "kes-excel-v1":
        raise ValueError("Ожидалась проекция Kaspersky. Исходные рабочие книги не принимаются.")
    sample["excel_kes"] = data
    weeks = data["sales"]["kes"]
    sample["sales"]["kes"] = weeks
    series = {}
    for key, window in funnel.WINDOWS.items():
        dates = funnel.days_in(window)
        part = [r for r in weeks if r["date"] in dates]
        if len(part) == window["weeks"]:
            series[key] = part
    sample["history"]["series"]["kes"] = series
    sample["history"]["orders"]["kes"] = {key:mean(r["value"] for r in part) for key,part in series.items()}
    return sample


def run(case, run_id, store, connect, daily_limit):
    import public_study
    from store_research import task_fit, task_evidence

    if case["finding"] != "kes" or case["filter"] != funnel.DEFAULTS or case["corpus_version"] != digest(store):
        raise ValueError("Для частного облачного разбора выберите базовые периоды Kaspersky.")
    family = case["scope"]["семейство"]
    definition = store["definitions"]["family_orders_idx"]
    windows = [funnel.days_in(funnel.WINDOWS[case["filter"][key]]) for key in ("before", "after")]
    means, references = [], []
    for days in windows:
        data = [r for r in store["sales"]["kes"] if r["date"] in days and not r["partial"]]
        if len(data) != 6:
            raise ValueError("Неполные окна BI.")
        means.append(round(mean(r["value"] for r in data), 1))
        references.append(f'C{data[0]["row"]}:C{data[-1]["row"]}')
    area = ', '.join(references)
    values = [format(v, ".1f").replace(".", ",") for v in means]
    value = f"{family}: средний индекс за 6 недель {values[0]} → {values[1]}."
    source = dict(definition, id="bi-window-index", sheet="Продажи", record=area,
                  source=f'{store["book"]} · Продажи · {area}', title="Средний недельный индекс", text=value)
    tasks = [{**r, "task_id":r["id"], "id":r["source_id"]} for r in store["tasks"]]
    by_id = {r["task_id"]:r for r in tasks}
    opened = [source, definition, *tasks]
    with connect() as db:
        ops = [{"op":"search","purpose":"Сравнить периоды и описания задач","type":"BI и бэклог","query":family,
                "searched":len(opened),"hits":[r["id"] for r in opened]}]+[{"op":"open","record":r} for r in opened]
        db.executemany("INSERT INTO radar_operations(run,at,payload) VALUES(?,?,?)",
                       [(run_id,now(),json.dumps(op,ensure_ascii=False)) for op in ops])
    context = {"показатель":value,"определение":definition["text"]}
    def call(step, prompt, schema, limit):
        return respond(connect, daily_limit, run_id, step, prompt, schema, lambda v:v,
                       limit, "Закрытый Excel · Kaspersky", jury_provider="siliconflow/fp8")

    def ask(step, instruction, data, fields, limit):
        schema={"type":"object","properties":fields,"required":list(fields),"additionalProperties":False}
        return call(step, instruction+"\n"+json.dumps(data, ensure_ascii=False), schema, limit)

    # Use the public stand's candidate serializer and matching procedure; the model never sees mechanism labels.
    candidates = []
    for row in tasks:
        evidence = task_evidence(row)
        mechanism = "measurement" if task_fit(row, family) and evidence["telemetry"] else "other"
        candidates.append({"id":row["task_id"], "title":row["title"], "text":row["text"],
                           "status":row["status"], "mechanism":mechanism})
    target = {"question":f"{value} {definition['text']} Есть ли зарегистрированный дефект измерения у этого семейства?",
              "mechanism":"measurement"}
    raw, selected, reason, _ = public_study.match_task(
        call, target, candidates, f"Проверить качество регистрации действий покупателя при выборе {family}.", None)
    row = by_id.get(selected)
    match = {"status":"none", "model_task":raw, "reason":reason}
    if row:
        match.update(status="matched", model_basis="telemetry", record_id=row["id"], task_id=row["task_id"],
                     source=row["source"], address=row["record"], version=row["version"], quote=row["text"])
    steps = public_study.kes_steps()
    fields = {key:{"type":"string","enum":list(steps[key]["choices"])} for key in ("test","technical","effect")}
    menu = {key:{"вопрос":steps[key]["label"],"ответы":steps[key]["choices"]} for key in fields}
    choices = ask("Критерий приёмки и эффект на продажи",
        "Выбери первую проверку, технический критерий и независимый способ оценить изменение продаж. "
        "Опирайся на описание задачи и определение показателя. Сверка одной попытки не устанавливает причину изменения BI.",
        {**context,"задача":row["text"] if row else "связь не установлена","варианты":menu},fields,224)
    plan = {out:steps[key]["choices"][choices[key]] for out,key in
            (("action","test"),("acceptance","technical"),("business","effect"))}
    if row and any(choices[key] not in steps[key]["accepted"] for key in fields):
        raise ValueError("Предложение Qwen не подтверждает техническую приёмку и отдельное измерение эффекта. Проверьте источники.")
    if not row:
        plan["action"] = "Уточнить основание для новой проверки"
        plan["acceptance"] = "Установить наблюдаемый дефект и источник данных для воспроизведения."
    payload={"id":run_id,"topic":"funnel","stage":case["stage"],"finding":"kes","scope":case["scope"],
             "question":case["question"],"evidence":opened,"selected":[source["id"],definition["id"]],
             "assessment":{"check":"paired"},"action":plain(plan["action"],180),"criterion":plain(plan["acceptance"],1200),
             "followup":plain(plan["business"],700),"task_match":match,"partner_cloud":True,
             "historical_result":"Фактический эффект исправления на продажи в материалах не измерен."}
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO studies VALUES(?,?)",(run_id,json.dumps(payload,ensure_ascii=False)))

def store_for_review(store):
    """Build from the partner workbook importer, excluding unneeded interview records."""
    keys = ("history","sales","definitions","releases","tasks","coverage","alerts","threshold","catalog",
            "initiatives","lk","reach_rows","reach_full","astra_rows","book","version")
    subset = {k:store[k] for k in keys}
    # The importer already limits the interview excerpts to four business observations.
    subset["interviews"] = [{k:r[k] for k in (
        "id","book","version","sheet","record","source","title","text","type","kind") if k in r}
        for r in store["interviews"]]
    subset["excel_kes"] = projection(store)
    subset["format"] = "partner-store-v1"
    return subset


def other_study(key, case, run_id, store, connect, daily_limit):
    import public_study
    from store_history import astra_diagnostic
    origin = "Astra" if key == "astra" else "Office"
    action_scope = case["scope"]
    if key == "astra":
        dashboard = astra_diagnostic(store,{**case["filter"],"finding":"below90"})
        evidence = list(dashboard["evidence"])
        evidence.extend(r for r in store["interviews"] if "astra" in r["text"].lower())
        question = "Как проверить изменение добавлений в корзину среди открытий подбора Astra на компьютерах?"
        mechanism = "cart"
    elif key == "office":
        product = store["catalog"][key]
        prices = product["prices"]
        evidence = [*prices["matched"],*prices["partial"]]
        if product["invoice"]:
            evidence.append(product["invoice"])
        question = "Какие сопоставимые цены и условия действительно дают основание проверить предложение Office?"
        mechanism = "price"
    else:
        raise ValueError("Неизвестный кейс.")
    for r in evidence:
        r.setdefault("record",r["source"].split(" · ")[-1])
        r.setdefault("version",store["version"])
        r.setdefault("kind","metrics")
    by_id = {str(i):r for i,r in enumerate(evidence,1)}
    def call(step,prompt,schema,limit):
        return respond(connect,daily_limit,run_id,step,prompt,schema,lambda v:v,limit,
                       "Материалы заказчика · "+origin,jury_provider="siliconflow/fp8")
    evidence_rows = [{"id":i,"свидетельство":r["title"],"выдержка":r["text"]} for i,r in by_id.items()]
    if key == "astra":
        options = {
            "audience": ("Проверить состав открытий подбора Astra на компьютерах",
                "Сравнить источники входа и конфигурации за обе недели. В каждом сопоставимом сегменте сверить открытия, успешные добавления и регистрацию события.",
                "После изменения сравнить долю добавлений и независимый индекс заказов Astra за полные недели при сопоставимом трафике."),
            "flow": ("Проверить переход из подбора Astra в корзину",
                "Повторить одинаковую конфигурацию на компьютере. Зафиксировать выбранную позицию, товар в корзине и соответствующее событие.",
                "После исправления сравнить долю успешных добавлений и недельный индекс самостоятельных заказов Astra при сопоставимых условиях."),
        }
        limit = "Доля добавлений зависит и от числа открытий, и от числа регистраций. Без связи визита с заказом причина изменения индекса BI остаётся гипотезой."
    else:
        options = {
            "offer": ("Проверить конкурентоспособность предложения Office",
                "Для того же артикула подтвердить срок лицензии, число устройств, условия счёта и действующую цену до изменения карточки.",
                "На сопоставимых предложениях проверить долю оплаченных счетов и валовую маржу. Учитывать изменение цены закупки."),
            "invoice": ("Проверить путь от карточки Office до оплаты счёта",
                "Для совпадающего артикула сравнить видимые условия, способ и время получения счёта. Зафиксировать, где покупатель прекращает оформление.",
                "После пилота сравнить долю оплаченных счетов и маржу Office. Отдельно учесть сделки с участием менеджера."),
        }
        limit = "Ценовые замеры и контрольный заказ не дают исходов оплат, объёмов продаж или маржи после изменения предложения."
    fields={"action":{"type":"string","enum":list(options)}}
    fields.update({k:{"type":"string","enum":list(by_id)} for k in ["source","contrast"]})
    schema={"type":"object","properties":fields,"required":list(fields),"additionalProperties":False}
    choice = call("Анализ свидетельств и проверка",
        question+" Выбери из списка одну проверку и две разные записи, которые объясняют её приоритет "
        "и позволяют проверить интерпретацию. Учитывай покрытие, знаменатели и сопоставимость. "
        "Варианты действий: "+json.dumps({k:v[0] for k,v in options.items()},ensure_ascii=False)+
        "\nМатериалы: "+json.dumps(evidence_rows,ensure_ascii=False),schema,240)
    action,acceptance,business=options[choice["action"]]
    proposal={**choice,"action":action,"acceptance":acceptance,"business":business,"limit":limit}
    tasks=[{**r,"task_id":r["id"],"id":r["source_id"],"product":key} for r in store["tasks"]]
    for r in tasks:
        body=(r["title"]+" "+r["text"]).lower()
        active=r["status"].lower() not in {"done","closed","закрыта","выполнена","завершена"}
        in_scope=origin.lower() in body
        terms=("корзин","добавл") if key=="astra" else ("цен","предложен")
        r["mechanism"]=mechanism if active and in_scope and any(t in body for t in terms) else "other"
    candidates=[{"id":r["task_id"],"title":r["title"],"text":r["text"],"status":r["status"],"mechanism":r["mechanism"]} for r in tasks]
    raw,chosen,reason,_=public_study.match_task(call,{"question":question,"mechanism":mechanism},candidates,proposal["action"],None)
    match={"status":"none","model_task":raw,"reason":"В выданном бэклоге не подтверждена открытая задача для этой проверки."}
    row=next((r for r in tasks if r["task_id"]==chosen),None)
    if row:
        match.update(status="matched",model_basis="mechanism",reason=reason,record_id=row["id"],task_id=chosen,
                     source=row["source"],address=row["record"],version=row["version"],quote=row["text"])
    selected=list(dict.fromkeys(by_id[proposal[k]]["id"] for k in ("source","contrast")))
    scope_note=plain(proposal["limit"],650)
    result={"id":run_id,"topic":"funnel","stage":case["stage"],"finding":key,"scope":action_scope,
            "question":question,"evidence":evidence+tasks,"selected":selected,"assessment":{"check":mechanism},
            "action":plain(proposal["action"],180),"criterion":plain(proposal["acceptance"],1200),
            "followup":plain(proposal["business"],700),"task_match":match,"partner_cloud":True,"historical_result":scope_note}
    with connect() as db:
        ops=[{"op":"search","purpose":"Сверка источников и бэклога","type":"материалы задачи","query":question,
              "searched":len(evidence)+len(tasks),"hits":[r["id"] for r in evidence+tasks]}]
        ops += [{"op":"open","record":r} for r in evidence+tasks]
        db.executemany("INSERT INTO radar_operations(run,at,payload) VALUES (?,?,?)",
                       [(run_id,now(),json.dumps(op,ensure_ascii=False)) for op in ops])
        db.execute("INSERT OR IGNORE INTO studies VALUES(?,?)",(run_id,json.dumps(result,ensure_ascii=False)))


if __name__ == "__main__":
    import argparse
    import os
    parser = argparse.ArgumentParser(description="Подготовить минимальную выборку Kaspersky из локального импорта Excel")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--all-cases", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    args.output.write_text(json.dumps((store_for_review if args.all_cases else projection)(json.loads(args.input.read_text())), ensure_ascii=False))
