"""Public OpenRouter research with inputs generated exclusively from the teaching fixture."""
import json
import os
from urllib.parse import urlsplit

from demo import sample_store
import funnel
import openrouter
import public_catalog_studies
import public_study
import partner_cloud
from pathlib import Path
import radar
import store_research
from growth_research import respond
from inference import funnel_study_identity
from workflow import digest, now

CALLS_PER_RUN = 4
ROUTES = {
    "release": ("kes", "order", funnel.DEFAULTS),
    "astra": ("astra", "cart", dict(funnel.DEFAULTS, family="astra", before="nov02", after="nov09", device="desktop")),
    "office": ("office", "offer", {}),
}


def check_config(invites, origin, limit):
    mode = openrouter.JURY_MODE
    if (mode not in {"public", "staging"} or openrouter.ENABLED
            or not os.getenv("PM_DATA_DIR") or not CALLS_PER_RUN <= limit <= 24
            or any(os.getenv(name) for name in ("PM_EVIDENCE_FILE", "PM_STORE_FILE", "PM_RESEARCH_FILE",
                                               "PM_TEST_MAIL_CONFIG"))):
        raise RuntimeError("Для облачного исследования нужен отдельный учебный набор и лимит 4–24 вызова.")
    if (mode == "public" and (not invites or urlsplit(origin or "").scheme != "https")
            or mode == "staging" and (invites or origin)):
        raise RuntimeError("Публичному учебному стенду нужны защищённое приглашение и HTTPS.")
    openrouter.key()


def store():
    review = os.getenv("PM_PARTNER_REVIEW")
    if review:
        store = json.loads(Path(review).read_text())
        if store.get("format") != "partner-store-v1":
            raise ValueError("Ожидалась защищённая проекция трёх кейсов.")
        return store
    sample = sample_store.build()
    sample["history"]["synthetic"] = True
    projection = os.getenv("PM_KES_EXCEL_PROJECTION")
    if projection:
        partner_cloud.apply_projection(sample, json.loads(Path(projection).read_text()))
    return sample


def specification(finding, sample):
    if finding == "kes":
        return public_study.kes_case()
    return {"astra": public_catalog_studies.astra_case, "office": public_catalog_studies.office_case}[finding](sample)


def make_case(sample, args):
    mode = args.get("mode")
    if not isinstance(mode, str) or mode not in ROUTES or args.keys() - {*funnel.DEFAULTS, "mode", "previous"}:
        raise ValueError("Выберите учебную находку на обзоре магазина.")
    finding, stage, filters = ROUTES[mode]
    supplied = {name: args[name] for name in funnel.DEFAULTS if name in args}
    if supplied != filters:
        raise ValueError("Облачное исследование доступно в исходном срезе учебной находки.")
    if finding == "office":
        item = sample["catalog"]["office"]
        scope = {"семейство": item["title"], "этап": "Выбор предложения",
                 "периоды": [item["prices"]["matched"][0]["date"]]}
    else:
        scope = funnel.study_case(sample["history"], dict(filters, stage=stage))["scope"]
    if sample.get("format") == "partner-store-v1":
        question = {"kes":"Как проверить отклонение самостоятельных заказов Kaspersky?",
                    "astra":"Как проверить изменение корзины Astra на компьютерах?",
                    "office":"Какие условия предложения Office стоит проверить?"}[finding]
        spec = {"question":question, "mechanism":{"kes":"measurement","astra":"cart","office":"price"}[finding],
                "version":sample["version"]}
    else:
        spec = specification(finding, sample)
    case = {"mode": mode, "finding": finding, "stage": stage, "filter": filters, "scope": scope,
            "format": radar.CLOUD_FORMAT, "question": spec["question"], "corpus_version": digest(sample["excel_kes"]) if finding == "kes" and "excel_kes" in sample else digest(spec),
            "mechanism": spec["mechanism"], "provider": "OpenRouter"}
    return mode, case


def enqueue(db, sample, args, limit):
    mode, case = make_case(sample, args)
    db.execute("BEGIN IMMEDIATE")
    previous = args.get("previous")
    if previous is not None:
        if not isinstance(previous, str):
            raise ValueError("Исследование не найдено.")
        past = radar.view_run(db, previous, include_result=False)
        if (not past or past["provider"] != "OpenRouter" or past["mode"] != mode
                or past["filter"] != case["filter"] or past["status"] not in {"done", "failed"}):
            raise ValueError("Завершите предыдущий запуск этой находки.")
        case["previous"] = previous
    _, run_id = funnel_study_identity(case)
    existing = radar.view_run(db, run_id, include_result=False)
    if existing:
        return existing
    today = now()[:10]
    spent = db.execute("SELECT count(*) FROM calls WHERE started >= ?", (today,)).fetchone()[0]
    pending = db.execute("""SELECT sum(max(0, ? - (SELECT count(*) FROM calls
                           WHERE study=r.id AND started >= ?))) FROM radar_runs r
                           WHERE r.status IN ('queued','running')""", (CALLS_PER_RUN, today)).fetchone()[0] or 0
    if spent + pending + CALLS_PER_RUN > limit:
        raise ValueError("До следующего дня не осталось полной квоты на исследование. Готовые разборы доступны.")
    return radar.enqueue(db, mode, case)


def prepare_records(rows, sample):
    tasks = {task["id"]: task for task in sample["tasks"]}
    offers = [row for item in sample["catalog"].values()
              for group in ("matched", "partial") for row in item["prices"][group]]
    sources = {row["source"]: row for row in (*sample["interviews"], *sample["releases"],
                                             *offers)}
    opened = []
    for row in rows:
        original = tasks.get(row["id"]) if row["kind"] == "Задача" else sources.get(row["source"])
        if row["kind"] == "Задача":
            opened.append({**original, **row, "text": original["text"], "kind": "backlog",
                           "task_id": original["id"]})
        else:
            opened.append({**(original or {}), **row, "type": row["kind"],
                           "record": (original or {}).get("record", row["id"]),
                           "book": sample["book"],
                           "version": sample["version"]})
    return opened


def qualified_task(result, opened, case):
    identifier = result["task"]
    if identifier == "none":
        return {"status": "none", "model_task": result["model_task"], "reason": result["task_reason"]}
    row = next((item for item in opened if item.get("task_id") == identifier), None)
    if not row or row["mechanism"] != case["mechanism"]:
        return {"status": "none", "model_task": identifier,
                "reason": "Открытое описание не подтверждает связь с этой проверкой."}
    basis = "mechanism"
    if case["finding"] == "kes":
        kinds = store_research.task_evidence(row)
        if not store_research.task_fit(row, case["scope"]["семейство"]):
            return {"status": "none", "model_task": identifier,
                    "reason": "Открытое описание не подтверждает связь с этой проверкой."}
        basis = "telemetry" if kinds["telemetry"] else "purchase"
    return {"status": "matched", "model_task": identifier, "model_basis": basis,
            "record_id": row["id"], "task_id": identifier, "source": row["source"],
            "address": row["record"], "version": row["version"], "quote": row["text"],
            "reason": result["task_reason"]}


def synthesize(case, run_id, connect, daily_limit):
    sample = store()
    _, expected = make_case(sample, {"mode": case.get("mode"), **case.get("filter", {})})
    if {key: value for key, value in case.items() if key != "previous"} != expected:
        raise ValueError("Исследование относится к другой версии учебного набора.")
    if case["finding"] == "kes" and "excel_kes" in sample:
        return partner_cloud.run(case, run_id, sample["excel_kes"], connect, daily_limit)
    if sample.get("format") == "partner-store-v1":
        return partner_cloud.other_study(case["finding"],case,run_id, sample,connect,daily_limit)
    spec = specification(case["finding"], sample)

    def call(step, prompt, schema, limit):
        provider = ("deepinfra/fp8" if step in {"Отбор свидетельств", "Сопоставление задачи"}
                    else "siliconflow/fp8")
        return respond(connect, daily_limit, run_id, step, prompt, schema, lambda value: value,
                       limit, f"Учебный магазин · {case['scope']['семейство']}", jury_provider=provider)

    def log_open(purpose, selected, searched):
        opened = prepare_records(selected, sample)
        ops = [{"op": "search", "purpose": purpose, "type": "каталог",
                "query": case["question"], "searched": searched, "hits": [row["id"] for row in opened]}]
        ops.extend({"op": "open", "record": row} for row in opened)
        with connect() as db:
            db.executemany("INSERT INTO radar_operations(run,at,payload) VALUES (?,?,?)",
                           [(run_id, now(), json.dumps(op, ensure_ascii=False)) for op in ops])

    study = public_study.research(call, on_open=log_open, case=spec)
    result = study["result"]
    if study["issues"]:
        first = result.get("next_action")
        details = f"Первая проверка подтверждена по открытым данным. {first} " if first else ""
        raise ValueError("Вывод требует проверки. " + details + " ".join(study["issues"]))
    opened = prepare_records(study["opened"], sample)
    branch = "\n".join(f'{item["label"]} — {item["text"]}' for item in result["branches"])
    payload = {"id": run_id, "topic": "funnel", "stage": case["stage"], "finding": case["finding"], "scope": case["scope"],
               "question": case["question"], "evidence": opened, "selected": [],
               "cloud_claims": {name: result[name] for name in ("signal", "alternative", "customer", "counterexample", "limit")},
               "cloud_branches": result["branches"], "cloud_business": result["business_conclusion"],
               "action": result["next_action"], "criterion": branch, "followup": result["after_release"],
               "assessment": {"check": "cloud"},
               "task_match": qualified_task(result, opened, case),
               "historical_result": "В учебном наборе нет результатов после проверки."}
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO studies VALUES (?,?)", (run_id, json.dumps(payload, ensure_ascii=False)))
