import json
import logging
import threading

import funnel
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
GROWTH_FACTS = [
    {"id": "repeat-mail", "type": "Интервью", "title": "Повтор из письма",
     "source": "Ответы по когортам · Малоактивные, K10 · обобщение",
     "text": "Один покупатель предложил начинать повторную закупку из письма о прошлом заказе."},
    {"id": "repeat-account", "type": "Конкурентное исследование", "title": "Повтор из истории",
     "source": "Конкурентное исследование · 06_Личный_Кабинет, строки 9 и 14",
     "text": "У X-Com и Комус в исследовании отмечен вход в повтор через личный кабинет."},
]
GROWTH_CRITERION = ("Взять покупателей с продлеваемыми лицензиями. Сравнить, как они находят и повторяют заказ "
                    "из письма и из истории. Зафиксировать долю завершённых повторов и ошибки выбора лицензии.")
GROWTH_LIMIT = "Размер аудитории продлений и эффект на оплаты неизвестны. Связь с конкретным семейством не подтверждена."
FOLLOW_UP = ("После исправления сверить совпадение действия и события по идентификатору лицензии. "
             "На полных неделях с сопоставимым входом затем проверить динамику индекса и решить, продолжать ли наблюдение.")


def deviation(data, args):
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
    return {
        "filter": selected, "family": report["family_name"], "index": index,
        "weeks": funnel.WINDOWS[selected["before"]]["weeks"], "compare": report["orders"].get(compare),
        "compare_name": funnel.FAMILIES[compare], "scope": case["scope"], "source": funnel.ORDER_SOURCE,
        "evidence": case["supports"] + case["limitations"], "related": case["candidate"], "case": case,
        "login": report["login"], "released": report["released"], "jury": report["jury"],
    }


def make_case(data, args):
    mode = args.get("mode", "release")
    if mode == "release":
        item = deviation(data, args)
        if item["filter"]["family"] != "kes":
            raise ValueError("Для Astra доступен отдельный разбор прохождения подбора.")
        case = item["case"]
        case["question"] = "Есть ли связь между падением самостоятельных заказов и релизом конфигуратора Kaspersky?"
    elif mode == "growth":
        case = {
            "filter": {}, "stage": "growth", "scope": {"этап": "Повторная закупка", "семейство": "Магазин"},
            "question": "Откуда покупателям удобнее начинать повторную закупку?",
            "supports": GROWTH_FACTS, "limitations": [
                {"id": "repeat-unknown", "type": "Ограничение", "title": "Покрытие повтора неизвестно",
                 "text": GROWTH_LIMIT, "source": "Softline v17 · ограничения выгрузки"}],
            "candidate": None, "confirmation": GROWTH_LIMIT,
            "action": "Сравнить повтор из письма и истории заказов", "criterion": GROWTH_CRITERION,
            "historical_result": "В v17 нет платёжных исходов и отдельного ряда повторных покупок."}
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


def worker(connect, daily_limit):
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
                        study_funnel(case, connect, daily_limit)
                    with connect() as db:
                        db.execute("UPDATE radar_runs SET status='done',study=?,finished=? WHERE id=?",
                                   (run_id, now(), run_id))
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
    return {k: row[k] for k in ("id", "mode", "status", "created", "finished", "error", "seen", "subject")} | {
        "scope": data["scope"], "filter": data["filter"], "stage": data["stage"],
        "question": data.get("question"), "resolution": json.loads(row["resolution"]) if row["resolution"] else None}


def recent(db):
    rows = db.execute("SELECT * FROM radar_runs ORDER BY (status='done' AND seen=0) DESC, created DESC LIMIT 30")
    return [public_run(row) for row in rows]


def view_run(db, run_id, include_result=True):
    row = db.execute("SELECT * FROM radar_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None
    run = public_run(row)
    if include_result and row["status"] == "done":
        study = db.execute("SELECT payload FROM studies WHERE id=?", (row["study"],)).fetchone()
        run["result"] = json.loads(study[0])
        run["result"]["calls"] = usage_for(db, row["study"])
        run["result"]["usage"] = usage_sum(run["result"]["calls"])
    return run


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
    if kind not in {"link", "new", "defer"}:
        raise ValueError("Выберите решение PM")
    result = run["result"]
    note, followup = args.get("note", ""), args.get("followup", "")
    if not isinstance(note, str) or not isinstance(followup, str) or len(note.strip()) > 700 or len(followup.strip()) > 700:
        raise ValueError("Проверьте длину решения и условия повторной проверки")
    resolution = {"kind": kind, "note": note.strip(), "followup": followup.strip(), "at": now(),
                  "task": None, "linked": None}
    if kind == "defer":
        if not resolution["note"]:
            raise ValueError("Укажите причину или условие возвращения к исследованию")
    else:
        if not resolution["followup"]:
            raise ValueError("Укажите условие последующей проверки")
        if kind == "link":
            related = result.get("related") or result.get("candidate")
            if not related:
                raise ValueError("В источниках нет подходящей задачи для связи")
            resolution["linked"] = related["id"]
        task = save_task(db, {"study": result["id"], "title": args.get("title", ""), "criterion": args.get("criterion", "")})
        resolution["task"] = task["id"]
    db.execute("UPDATE radar_runs SET resolution=? WHERE id=?", (json.dumps(resolution, ensure_ascii=False), rid))
    return resolution
