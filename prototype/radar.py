import json
import logging
import threading
from datetime import date

import funnel
import growth_research
import store_research
import mail_outbox
from store_history import sales_basis
from inference import study_funnel, funnel_study_identity
from workflow import digest, now, usage_for, usage_sum

CATALOG = {
    "office": {"title": "Office Home and Business 2024", "stage": "Самостоятельный счёт",
               "source": "Конкурентное исследование · 04_Покупка_Счет",
               "text": "В конкурентной сверке описан путь самостоятельного получения счёта. Можно проверить переход от запроса счёта к его выставлению."},
    "kompas": {"title": "КОМПАС-3D", "stage": "Выбор и выставление счёта",
               "source": "Конкурентное исследование · 02A_Продукты_x_Конкуренты, строка 28; 04_Покупка_Счет",
               "text": "В материалах есть сравнение предложений и прохождения покупки по счёту."},
    "nanocad": {"title": "nanoCAD", "stage": "Выбор и выставление счёта",
                 "source": "Конкурентное исследование · 02A_Продукты_x_Конкуренты, строка 29; 04_Покупка_Счет",
                 "text": "В материалах есть сравнение предложений, поиск товара и наблюдения по получению счёта."},
}
FOLLOW_UP = ("После исправления сверить совпадение действия и события по идентификатору лицензии. "
             "На полных неделях с сопоставимым входом затем проверить динамику индекса и решить, продолжать ли наблюдение.")


def deviation(data, args, store=None):
    report = funnel.report(data, args)
    selected = report["filter"]
    index = report["orders"].get(selected["family"])
    if not index:
        raise ValueError("В выбранном срезе нет индекса для карточки отклонения.")
    compare = "astra" if selected["family"] == "kes" else "kes"
    case = funnel.study_case(data, dict(selected, stage="order"))
    if selected["family"] == "kes":
        case["action"] = "Сверить корзину и события подбора Kaspersky"
        case["criterion"] = funnel.study_case(data, dict(selected, stage="cart"))["criterion"]
        case["historical_result"] = funnel.NO_RELEASE_RESULT
    result = {
        "filter": selected, "family": report["family_name"], "index": index,
        "weeks": funnel.WINDOWS[selected["before"]]["weeks"], "compare": report["orders"].get(compare),
        "compare_name": funnel.FAMILIES[compare], "scope": case["scope"], "source": funnel.ORDER_SOURCE,
        "evidence": case["supports"] + case["limitations"], "case": case,
        "login": report["login"], "released": report["released"], "jury": report["jury"],
    }
    if store:
        basis = [sales_basis(store, family, [funnel.WINDOWS[selected[k]] for k in ("before","after")])
                 for family in (selected["family"], compare)]
        result.update(coverage=report["coverage"],
                      events=[row for row in store["releases"] if row["title"] in ("R-08","R-09","R-10")],
                      reach=report["pairs"]["after"].get("cfg_reach_rate"),
                      reach_full=store.get("reach_full"),
                      definition=store["definitions"]["family_orders_idx"],
                      customer_evidence=store["interviews"],
                      cart_definition=store["definitions"]["cfg_add_to_cart_rate"])
        if not store.get("demo"):
            result["series"] = store["sales"][selected["family"]]
        result["evidence"].extend(basis + store["interviews"])
    return result


def make_case(data, args, corpus=(), store=None):
    mode = args.get("mode", "release")
    if mode == "release":
        item = deviation(data, args)
        if item["filter"]["family"] != "kes":
            raise ValueError("Для Astra доступен отдельный разбор прохождения подбора.")
        case = item["case"]
        case["question"] = "Есть ли связь между падением самостоятельных заказов и релизом конфигуратора Kaspersky?"
        if store:
            case = store_research.make_case(store, "kes", item["filter"], case)
    elif mode == "office" and store:
        case = store_research.make_case(store, "office", {})
    elif mode == "growth":
        case = growth_research.case_for(corpus)
    elif mode == "stage":
        case = funnel.study_case(data, args)
    else:
        raise ValueError("Неизвестное действие исследования")
    question = args.get("question", "")
    if not isinstance(question, str) or len(question.strip()) > 220:
        raise ValueError("Уточнение должно содержать до 220 символов")
    if question.strip():
        case["question"] = case.get("question", "Что проверить на выбранном этапе?") + " Уточнение PM: " + " ".join(question.split())
    return mode, case


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS radar_runs (
        id TEXT PRIMARY KEY, subject TEXT NOT NULL, mode TEXT NOT NULL, input TEXT NOT NULL,
        status TEXT NOT NULL, created TEXT NOT NULL, finished TEXT, study TEXT REFERENCES studies(id),
        error TEXT, seen INTEGER NOT NULL DEFAULT 0, resolution TEXT
    )""")
    db.execute("UPDATE radar_runs SET status='queued' WHERE status='running'")
    db.execute("""CREATE TABLE IF NOT EXISTS radar_operations (
        id INTEGER PRIMARY KEY, run TEXT NOT NULL REFERENCES radar_runs(id), at TEXT NOT NULL, payload TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS radar_ops_run ON radar_operations(run)")
    db.execute("""UPDATE radar_runs SET status='failed',error='Исторический запуск относился к шаблону.'
                  WHERE mode='growth' AND status='queued' AND json_extract(input,'$.finding') IS NULL""")
    mail_outbox.setup(db)


def enqueue(db, mode, case):
    key, study_id = funnel_study_identity(case)
    subject = digest([mode, case["filter"], case["stage"]])
    db.execute("""INSERT OR IGNORE INTO radar_runs(id,subject,mode,input,status,created)
        VALUES (?,?,?,?,'queued',?)""", (study_id, subject, mode, json.dumps(case, ensure_ascii=False), now()))
    db.execute("UPDATE radar_runs SET status='queued',finished=NULL,error=NULL WHERE id=? AND status='failed'",
               (study_id,))
    return view_run(db, study_id, False)


def next_run(db):
    row = db.execute("SELECT id,input FROM radar_runs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
    if row:
        result = db.execute("UPDATE radar_runs SET status='running' WHERE id=? AND status='queued'", (row["id"],))
        if result.rowcount:
            return row["id"], json.loads(row["input"])
    return None


def worker(connect, daily_limit, corpus, store=None, mail=None, mail_wake=None):
    signal = threading.Event()

    def run():
        while True:
            signal.wait(2)
            signal.clear()
            with connect() as db:
                job = next_run(db)
            while job:
                run_id, case = job
                try:
                    with connect() as db:
                        saved = db.execute("SELECT id FROM studies WHERE id=?", (run_id,)).fetchone()
                    if not saved:
                        if case.get("finding") == growth_research.KEY:
                            growth_research.synthesize(case, run_id, corpus, connect, daily_limit)
                        elif case.get("finding") in store_research.QUESTIONS:
                            store_research.synthesize(case, run_id, store, connect, daily_limit)
                        else:
                            study_funnel(case, connect, daily_limit)
                    with connect() as db:
                        db.execute("UPDATE radar_runs SET status='done',study=?,finished=? WHERE id=?",
                                   (run_id, now(), run_id))
                        if mail and case.get("finding") == "kes":
                            mail_outbox.enqueue(db, run_id, case, store, mail)
                    if mail_wake:
                        mail_wake.set()
                except (ValueError, RuntimeError) as exc:
                    with connect() as db:
                        db.execute("UPDATE radar_runs SET status='failed',error=?,finished=? WHERE id=?",
                                   (str(exc), now(), run_id))
                except Exception:
                    logging.exception("PM Radar research job failed: %s", run_id)
                    with connect() as db:
                        db.execute("UPDATE radar_runs SET status='failed',error=?,finished=? WHERE id=?",
                                   ("Не удалось выполнить разбор.", now(), run_id))
                with connect() as db:
                    job = next_run(db)

    thread = threading.Thread(target=run, daemon=True, name="pm-radar-research")
    thread.start()
    signal.set()
    return signal


def public_run(row):
    data = json.loads(row["input"])
    current_backlog_search = data.get("format") == store_research.MATCH_FORMAT and data.get("finding") == "kes"
    return {k: row[k] for k in ("id", "mode", "status", "created", "finished", "error", "seen", "subject")} | {
        "scope": data["scope"], "filter": data["filter"], "stage": data["stage"],
        "question": data.get("question"), "finding": data.get("finding"),
        "backlog_search": current_backlog_search,
        "resolution": saved_resolution(row["resolution"], current_backlog_search)}


def saved_resolution(raw, verified):
    if not raw:
        return None
    result = json.loads(raw)
    if result.get("linked") and not verified:
        result.update(linked=None, legacy_link=True)
    return result


def study_view(db, record, case, run_id, operations=None):
    # Older runs contained a prefilled candidate. Keep the study and decision, without promoting that link.
    record.pop("candidate", None)
    record.pop("related", None)
    if case.get("finding") != "kes" or case.get("format") != store_research.MATCH_FORMAT:
        return record
    proof = record.get("task_match") or {}
    if proof.get("status") != "matched":
        return record
    if operations is None:
        operations = [json.loads(row[0]) for row in db.execute(
            "SELECT payload FROM radar_operations WHERE run=? ORDER BY id", (run_id,))]
    for op in operations:
        if op["op"] != "open":
            continue
        row = op["record"]
        if (row["kind"] == "backlog"
                and (row["id"], row["task_id"], row["source"], row["record"], row["version"], row["text"])
                == tuple(proof.get(k) for k in ("record_id", "task_id", "source", "address", "version", "quote"))
                and all((row.get("source_id"), row["record"], row["version"]))
                and store_research.task_fit(row, case["scope"]["семейство"])):
            record["related"] = {"id": row["task_id"], "record_id": row["id"], "title": row["title"],
                                 "status": row["status"], "source": row["source"]}
            return record
    record["task_match"] = {"status": "none", "reason": "Адрес открытой задачи не удалось подтвердить."}
    return record


def recent(db):
    rows = db.execute("""SELECT r.*,
                      (SELECT count(*) FROM radar_operations WHERE run=r.id) AS operation_count
                      FROM radar_runs r ORDER BY (status='done' AND seen=0) DESC, created DESC LIMIT 30""")
    return [public_run(row) | {"operation_count": row["operation_count"],"mail":mail_outbox.status(db,row["id"])}
            for row in rows]


def view_run(db, run_id, include_result=True):
    row = db.execute("SELECT * FROM radar_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None
    run = public_run(row)
    case = json.loads(row["input"])
    run["mail"] = mail_outbox.status(db,run_id)
    if include_result and run["finding"]:
        run["corpus_version"] = case["corpus_version"]
        if "known" in case:
            run["before"] = {"known": case["known"], "coverage": case["coverage"]}
        run["operations"] = [json.loads(op["payload"]) | {"at": op["at"]} for op in db.execute(
            "SELECT at,payload FROM radar_operations WHERE run=? ORDER BY id", (run_id,))]
        run["calls"] = usage_for(db, run_id)
        run["usage"] = usage_sum(run["calls"])
    if include_result and row["status"] == "done":
        study = db.execute("SELECT payload FROM studies WHERE id=?", (row["study"],)).fetchone()
        run["result"] = study_view(db, json.loads(study[0]), case, run_id, run.get("operations"))
        if run["resolution"] and run["resolution"].get("linked") != (run["result"].get("related") or {}).get("id"):
            run["resolution"]["linked"] = None
        run["result"]["calls"] = usage_for(db, row["study"])
        run["result"]["usage"] = usage_sum(run["result"]["calls"])
    return run


def project_run(db, key, filters, ref=None, summary=False):
    mode, stage = ("release","order") if key == "kes" else ("office","offer")
    subject = digest([mode, filters, stage])
    if not ref:
        row = db.execute("""SELECT id FROM radar_runs WHERE subject=?
                            AND json_extract(input,'$.finding')=?
                            AND (? != 'kes' OR json_extract(input,'$.format')=?)
                            ORDER BY (status='done') DESC, created DESC LIMIT 1""",
                         (subject,key,key,store_research.MATCH_FORMAT)).fetchone()
        ref = row["id"] if row else None
    run = view_run(db, ref, include_result=not summary) if ref else None
    if ref and (not run or run["finding"] != key or run["filter"] != filters):
        raise ValueError("Это исследование относится к другой находке или периоду.")
    return run


def view_finding(db, corpus, ref):
    finding = growth_research.finding(corpus)
    rows = db.execute("""SELECT * FROM radar_runs WHERE json_extract(input,'$.finding')=?
                         ORDER BY created DESC LIMIT 30""", (growth_research.KEY,)).fetchall()
    finding["runs"] = [public_run(row) for row in rows]
    if not ref:
        for row in rows:
            case = json.loads(row["input"])
            if case["corpus_version"] == finding["version"] and case.get("format") == growth_research.FORMAT:
                ref = row["id"]
                break
    finding["run"] = view_run(db, ref) if ref else None
    if ref and (not finding["run"] or finding["run"]["finding"] != growth_research.KEY):
        raise ValueError("У этой находки нет указанного исследования.")
    return finding


def mark_seen(db, run_id):
    db.execute("UPDATE radar_runs SET seen=1 WHERE id=? AND status='done'", (run_id,))


def resolve(db, args, save_task):
    # Serialize simultaneous resolution clicks so only one accepted disposition is written.
    db.execute("BEGIN IMMEDIATE")
    rid = args.get("id", "")
    run = view_run(db, rid)
    if not run or run["status"] != "done":
        raise ValueError("Результат исследования ещё не готов")
    if run["resolution"]:
        return run["resolution"]
    kind = args.get("kind")
    allowed = {"new", "segment", "defer"} if run["finding"] == growth_research.KEY else {"link", "new", "defer"}
    if kind not in allowed:
        raise ValueError("Выберите решение PM")
    result = run["result"]
    note, followup = args.get("note", ""), args.get("followup", "")
    if not isinstance(note, str) or not isinstance(followup, str) or len(note.strip()) > 700 or len(followup.strip()) > 700:
        raise ValueError("Проверьте длину решения и условия повторной проверки")
    resolution = {"kind": kind, "note": note.strip(), "followup": followup.strip(), "at": now(),
                  "task": None, "linked": None}
    if kind in {"defer", "segment"}:
        if not resolution["note"]:
            raise ValueError("Укажите, что нужно уточнить или когда вернуться к исследованию")
    else:
        if not resolution["followup"]:
            raise ValueError("Укажите условие последующей проверки")
        if run["finding"] in store_research.QUESTIONS:
            owner = args.get("owner", "")
            if not isinstance(owner, str) or not 1 <= len(owner.strip()) <= 120:
                raise ValueError("Укажите владельца проверки")
            try:
                due = date.fromisoformat(args.get("due","")).isoformat()
            except (ValueError,TypeError) as exc:
                raise ValueError("Укажите дату возврата к проверке") from exc
            resolution.update(owner=owner.strip(), due=due, method=result["assessment"]["check"])
        if kind == "link":
            related = result.get("related")
            if not related:
                raise ValueError("В источниках нет подходящей задачи для связи")
            resolution["linked"] = related["id"]
        task = save_task(db, {"study": result["id"], "title": args.get("title", ""), "criterion": args.get("criterion", "")})
        resolution["task"] = task["id"]
    db.execute("UPDATE radar_runs SET resolution=? WHERE id=?", (json.dumps(resolution, ensure_ascii=False), rid))
    return resolution
