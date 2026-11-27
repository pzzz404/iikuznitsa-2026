import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import parse, request

import openrouter
import funnel
import radar
import growth_research
import mail_outbox
from handoff import redmine_csv
from store_history import sales_basis
from evidence import ROOT, TOPICS, facts_and_tasks
from inference import DECISIONS, ModelBusy, study, study_funnel
from workflow import (EVENT_RESULTS, event_defaults, experiment, import_research, now, save_check, save_event_check, setup_workflow,
                      usage_for, usage_sum, verification_defaults)

sys.path.insert(0, str(ROOT))
from demo.crm.reconcile import cohort_balances

HERE = Path(__file__).resolve().parent
LOCAL = Path(os.getenv("PM_DATA_DIR", Path.home() / ".local/share/pm-hackathon"))
INVITES = os.getenv("PM_INVITES")
PUBLIC_ORIGIN = os.getenv("PM_PUBLIC_ORIGIN")
EVIDENCE_FILE = os.getenv("PM_EVIDENCE_FILE")
STORE_FILE = os.getenv("PM_STORE_FILE")
LIMIT = 4 if openrouter.ENABLED else (int(os.getenv("PM_MODEL_DAILY_LIMIT", "16")) if INVITES else 0)
TAG = "сгенерирована ИИ-помощником"
IMAGES = {"card": "02-crypto-card.png", "cart": "03-guest-basket.png"}
DB = LOCAL / "backlog.sqlite3"
COOKIE = "__Host-pm-jury"


def serialize(obj):
    return json.dumps(obj, ensure_ascii=False).encode()


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def setup():
    global FACTS, IMPORTED, CRM, FUNNEL, RADAR_WAKE, RESEARCH_CORPUS, STORE
    if openrouter.ENABLED and (INVITES or not EVIDENCE_FILE or not os.getenv("PM_DATA_DIR")
                               or LOCAL.resolve() == (Path.home() / ".local/share/pm-hackathon").resolve()):
        raise RuntimeError("Для OpenRouter нужен отдельный локальный стенд с синтетическими данными")
    if INVITES and not (EVIDENCE_FILE and PUBLIC_ORIGIN and os.getenv("PM_DATA_DIR")
                        and os.getenv("PM_LOCAL_MODEL_URL") and LIMIT > 0):
        raise RuntimeError("Для жюри нужны каталог, источник демо, свой адрес модели, HTTPS и лимит")
    if EVIDENCE_FILE:
        sample = json.loads(Path(EVIDENCE_FILE).read_text())
        if openrouter.ENABLED and sample.get("mode") != "synthetic-openrouter":
            raise RuntimeError("OpenRouter принимает только синтетический набор")
        FACTS, IMPORTED = sample["facts"], sample["tasks"]
        FUNNEL = sample.get("funnel")
        if INVITES and FUNNEL and FUNNEL.get("jury") is not True:
            raise RuntimeError("Для жюри нужен отдельный файл согласованных агрегатов")
    else:
        FACTS, IMPORTED = facts_and_tasks()
        FUNNEL = funnel.load_history()
    CRM = cohort_balances(json.loads((ROOT / "demo/crm/synthetic_sales.json").read_text()))
    STORE = json.loads(Path(STORE_FILE).read_text()) if STORE_FILE and FUNNEL and not openrouter.ENABLED else None
    if STORE:
        FUNNEL = STORE["history"]
        IMPORTED = [{"task_id":row["id"], "title":row["title"], "status":row["status"]} for row in STORE["tasks"]]
    RESEARCH_CORPUS = growth_research.load() if FUNNEL and not openrouter.ENABLED else []
    LOCAL.mkdir(parents=True, exist_ok=True, mode=0o700)
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS studies (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY, study TEXT UNIQUE NOT NULL REFERENCES studies(id),
            title TEXT NOT NULL, criterion TEXT NOT NULL, created TEXT NOT NULL
        )""")
        setup_workflow(db)
        if FUNNEL:
            radar.setup(db)
    mail_path = os.getenv("PM_TEST_MAIL_CONFIG")
    mail = mail_outbox.load(mail_path, PUBLIC_ORIGIN) if mail_path and STORE and INVITES else None
    mail_wake = mail_outbox.worker(connect, mail) if mail else None
    RADAR_WAKE = radar.worker(connect, LIMIT, RESEARCH_CORPUS, STORE, mail, mail_wake) if FUNNEL else None


def uploaded(db):
    return [json.loads(row["payload"]) for row in db.execute("SELECT payload FROM research")]


def task_details(db, row):
    task = dict(row)
    record = json.loads(task.pop("payload"))
    record.setdefault("evidence", [f for f in FACTS if f["id"] in record["selected"]])
    task["study_data"] = record
    task["calls"] = usage_for(db, task["study"])
    task["usage"] = usage_sum(task["calls"])
    stored = db.execute("SELECT payload FROM checks WHERE task=?", (task["id"],)).fetchone()
    is_funnel = record["topic"] == "funnel"
    event_mode = is_funnel and record.get("stage") not in {"growth","offer"}
    metric = ("Доля оплаченных подходящих заказов Office" if record.get("stage") == "offer"
              else TOPICS["repeat"]["measure"] if is_funnel else TOPICS[record["topic"]]["measure"])
    defaults = event_defaults() if event_mode else verification_defaults(metric)
    if record.get("stage") == "offer":
        defaults["guard"] = "Доля заказов ниже согласованной минимальной маржи"
    task["plan"] = json.loads(stored[0]) if stored else defaults
    task["result"] = None if event_mode else experiment(task["plan"])
    if is_funnel and FUNNEL:
        detail = db.execute("SELECT id,mode,input,resolution FROM radar_runs WHERE study=? AND resolution IS NOT NULL", (task["study"],)).fetchone()
        if detail:
            task["radar"] = {"id": detail["id"], "mode": detail["mode"], "finding": record.get("finding"),
                             "filter": json.loads(detail["input"])["filter"],
                             **json.loads(detail["resolution"])}
    return task


def accessible_study(payload):
    return bool(payload and (not (INVITES and FUNNEL) or json.loads(payload[0])["topic"] == "funnel"))


def save_task(db, payload):
    key = payload.get("study", "")
    title = payload.get("title", "").strip()
    criterion = payload.get("criterion", "").strip()
    if not (0 < len(title) <= 180 and 0 < len(criterion) <= 1200):
        raise ValueError("Заполните название и критерий приёмки")
    if not accessible_study(db.execute("SELECT payload FROM studies WHERE id=?", (key,)).fetchone()):
        raise ValueError("Сначала завершите разбор")
    if payload.get("edit") is True:
        db.execute("UPDATE tasks SET title=?,criterion=? WHERE study=?", (title, criterion, key))
    else:
        db.execute("INSERT OR IGNORE INTO tasks(study,title,criterion,created) VALUES (?,?,?,?)",
                   (key, title, criterion, now()))
    row = db.execute(
        "SELECT t.*, s.payload FROM tasks t JOIN studies s ON t.study=s.id WHERE t.study=?", (key,)
    ).fetchone()
    if not row:
        raise ValueError("Задача пока не создана")
    return task_details(db, row)


def metrika():
    counter = os.getenv("METRIKA_COUNTER_ID")
    token = os.getenv("METRIKA_OAUTH_TOKEN")
    if EVIDENCE_FILE or not (counter and token):
        return {"configured": False, "message": "Тестовый счётчик участника пока не подключён."}
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=6)
    query = parse.urlencode({"ids": counter, "metrics": "ym:s:visits", "dimensions": "ym:s:date",
                             "date1": start, "date2": end})
    req = request.Request("https://api-metrika.yandex.net/stat/v1/data?" + query,
                          headers={"Authorization": "OAuth " + token})
    try:
        with request.urlopen(req, timeout=12) as res:
            total = json.load(res)["totals"][0]
    except (OSError, ValueError, KeyError, IndexError) as exc:
        raise RuntimeError("Не удалось получить отчёт Яндекс.Метрики. Проверьте доступ на чтение.") from exc
    return {"configured": True, "visits": total, "from": str(start), "to": str(end)}


def invite_ttl(token):
    if not isinstance(token, str) or not 30 <= len(token) <= 128:
        return 0
    try:
        invites = json.loads(Path(INVITES).read_text())
        tail = hashlib.sha256(token.encode()).hexdigest()
        for secret_hash, expiry in invites.items():
            if hmac.compare_digest(secret_hash, tail):
                return max(0, int((datetime.fromisoformat(expiry) - datetime.now(timezone.utc)).total_seconds()))
    except (OSError, ValueError, AttributeError, TypeError):
        return 0
    return 0


class Handler(BaseHTTPRequestHandler):
    timeout = 12

    def public_origin(self):
        return PUBLIC_ORIGIN

    def log_message(self, fmt, *args):
        pass

    def reply(self, data, kind="application/json; charset=utf-8", status=200, cookie=None, attachment=None):
        raw = data if isinstance(data, bytes) else serialize(data)
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorized(self):
        if not INVITES:
            return True
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            return bool(COOKIE in cookies and invite_ttl(cookies[COOKIE].value))
        except CookieError:
            return False

    def denied(self):
        return self.reply({"error": "Откройте ссылку-приглашение для жюри."}, status=401)

    def do_GET(self):
        target = parse.urlsplit(self.path)
        path = target.path
        static = {"/": ("index.html", "text/html"), "/style.css": ("style.css", "text/css"),
                  "/ui.js": ("ui.js", "application/javascript"), "/funnel-ui.js": ("funnel-ui.js", "application/javascript"),
                  "/radar-ui.js": ("radar-ui.js", "application/javascript"), "/store-ui.js": ("store-ui.js", "application/javascript")}
        if path in static:
            name, kind = static[path]
            return self.reply((HERE / name).read_bytes(), kind + "; charset=utf-8")
        if path == "/fonts/manrope.ttf":
            return self.reply((HERE / "fonts/manrope.ttf").read_bytes(), "font/ttf")
        if not self.authorized():
            return self.denied()
        if STORE and INVITES and path == "/api/task/redmine.csv":
            try:
                task_id = int(dict(parse.parse_qsl(target.query, max_num_fields=2)).get("id", ""))
            except ValueError:
                return self.reply({"error":"Задача не найдена."}, status=404)
            with connect() as db:
                row = db.execute("SELECT t.*,s.payload FROM tasks t JOIN studies s ON s.id=t.study WHERE t.id=?",
                                 (task_id,)).fetchone()
                task = task_details(db, row) if row else None
            if not task or not task.get("radar", {}).get("finding"):
                return self.reply({"error":"Для этой задачи нет экспорта с адресом находки."}, status=404)
            return self.reply(redmine_csv(task, TAG, self.public_origin()), "text/csv; charset=utf-8",
                              attachment=f"pm-radar-{task_id:03d}-redmine.csv")
        if not EVIDENCE_FILE and path.startswith("/images/") and path[8:] in IMAGES:
            file = ROOT / "research/store" / IMAGES[path[8:]]
            if file.exists():
                return self.reply(file.read_bytes(), "image/png")
        if path == "/api/data":
            with connect() as db:
                tasks = [task_details(db, row) for row in db.execute(
                    """SELECT t.*,s.payload FROM tasks t JOIN studies s ON t.study=s.id
                    WHERE NOT ? OR json_extract(s.payload, '$.topic')='funnel' ORDER BY t.id DESC""",
                    (bool(INVITES and FUNNEL),)
                )]
                research = [] if INVITES else uploaded(db)
                deferred = [] if INVITES and FUNNEL else [
                    dict(row) for row in db.execute("SELECT * FROM deferred WHERE until_date>=?", (date.today().isoformat(),))]
                return self.reply({"topics": TOPICS, "decisions": DECISIONS, "facts": FACTS,
                                   "research": research, "tasks": tasks, "tag": TAG, "deferred": deferred,
                                   "imported": [{"id": r["task_id"], "title": r["title"], "status": r["status"]}
                                                for r in IMPORTED],
                                   "crm": CRM, "sample": bool(EVIDENCE_FILE), "jury": bool(INVITES),
                                   "external": openrouter.ENABLED, "funnel": funnel.options(FUNNEL),
                                   "catalog": radar.CATALOG if FUNNEL else {},
                                   "growth": growth_research.finding(RESEARCH_CORPUS) if FUNNEL else None,
                                   "store": ({k: STORE[k] for k in ("catalog","coverage","threshold","alerts","releases",
                                             "definitions","tasks","initiatives","lk")} if STORE else None),
                                   "event_results": EVENT_RESULTS,
                                   "today": date.today().isoformat()})
        if path == "/api/funnel" and FUNNEL:
            try:
                params = dict(parse.parse_qsl(target.query, max_num_fields=12))
                return self.reply(funnel.report(FUNNEL, params))
            except ValueError as exc:
                return self.reply({"error": str(exc)}, status=400)
        if path.startswith("/api/radar/") and FUNNEL:
            try:
                args = dict(parse.parse_qsl(target.query, max_num_fields=12))
                if path == "/api/radar/deviation":
                    result = radar.deviation(FUNNEL, args, STORE)
                    result.pop("case")
                    if STORE:
                        with connect() as db:
                            result["run"] = radar.project_run(db, "kes", result["filter"], args.get("run"))
                    return self.reply(result)
                with connect() as db:
                    if STORE and path == "/api/radar/office":
                        return self.reply({"run":radar.project_run(db,"office",{},args.get("run"))})
                    if STORE and path == "/api/radar/orders":
                        params = funnel.selection(args)
                        windows = [funnel.WINDOWS[params[k]] for k in ("before","after")]
                        return self.reply({"series":STORE["sales"][params["family"]],
                                           "evidence":[sales_basis(STORE,key,windows) for key in funnel.FAMILIES]})
                    if path == "/api/radar/runs":
                        return self.reply(radar.recent(db))
                    if path == "/api/radar/finding":
                        return self.reply(radar.view_finding(db, RESEARCH_CORPUS, args.get("id", "")))
                    if path == "/api/radar/run":
                        result = radar.view_run(db, args.get("id", ""))
                        if result:
                            return self.reply(result)
            except ValueError as exc:
                return self.reply({"error": str(exc)}, status=400)
        if path == "/api/usage":
            with connect() as db:
                query = """SELECT calls.*, json_extract(r.input,'$.finding') AS finding FROM calls
                           LEFT JOIN radar_runs r ON r.id=calls.study""" if FUNNEL else "SELECT * FROM calls"
                calls = [dict(row) for row in db.execute(
                    query + " WHERE NOT ? OR scenario LIKE 'Воронка · %' ORDER BY calls.id DESC LIMIT 200",
                    (bool(INVITES and FUNNEL),))]
                return self.reply({"calls": calls, "usage": usage_sum(calls)})
        if path == "/api/metrika":
            try:
                return self.reply(metrika())
            except RuntimeError as exc:
                return self.reply({"error": str(exc)}, status=502)
        return self.reply({"error": "Нет такой страницы"}, status=404)

    def do_POST(self):
        path = parse.urlsplit(self.path).path
        origin = self.headers.get("Origin")
        expected = self.public_origin() if INVITES else "http://" + self.headers.get("Host", "")
        if (INVITES and origin != expected) or (origin and origin != expected):
            return self.reply({"error": "Запрос с другого сайта"}, status=403)
        if path != "/api/invite" and not self.authorized():
            return self.denied()
        try:
            n = int(self.headers.get("Content-Length", "0"))
            maximum = 3_500_000 if path == "/api/research" and not INVITES else 8192
            if not 0 < n <= maximum or self.headers.get_content_type() != "application/json":
                raise ValueError("Проверьте размер и формат запроса")
            data = json.loads(self.rfile.read(n))
            if not isinstance(data, dict):
                raise ValueError("Ожидается объект")
            if path == "/api/invite" and INVITES:
                token = data.get("token")
                ttl = invite_ttl(token)
                if not ttl:
                    return self.denied()
                cookie = SimpleCookie()
                cookie[COOKIE] = token
                cookie[COOKIE]["path"] = "/"
                cookie[COOKIE]["httponly"] = True
                cookie[COOKIE]["secure"] = True
                cookie[COOKIE]["samesite"] = "Strict"
                cookie[COOKIE]["max-age"] = ttl
                return self.reply({"ok": True}, cookie=cookie[COOKIE].OutputString())
            if path == "/api/study":
                if INVITES and FUNNEL:
                    raise ValueError("Выберите этап воронки в демонстрационном наборе")
                q = " ".join(data.get("question", "").split())
                if not 3 <= len(q) <= 350:
                    raise ValueError("Введите вопрос длиной от 3 до 350 символов")
                if openrouter.ENABLED and (q != TOPICS["invoice"]["question"] or data.get("topic") != "invoice"):
                    raise ValueError("Для замера OpenRouter выберите готовый сценарий о самостоятельном счёте.")
                with connect() as db:
                    research = [] if INVITES else uploaded(db)
                return self.reply(study(q, data.get("topic"), FACTS, TOPICS, research, connect, LIMIT))
            if path == "/api/funnel/study" and FUNNEL:
                return self.reply(study_funnel(funnel.study_case(FUNNEL, data), connect, LIMIT))
            if path == "/api/radar/start" and FUNNEL:
                mode, case = radar.make_case(FUNNEL, data, RESEARCH_CORPUS, STORE)
                with connect() as db:
                    run = radar.enqueue(db, mode, case)
                RADAR_WAKE.set()
                return self.reply(run, status=202)
            with connect() as db:
                if path == "/api/task":
                    response = save_task(db, data)
                elif path == "/api/check":
                    task_id = data.get("id")
                    existing = db.execute("SELECT s.payload FROM tasks t JOIN studies s ON t.study=s.id WHERE t.id=?",
                                          (task_id,)).fetchone()
                    if not accessible_study(existing):
                        raise ValueError("Задача не найдена")
                    record = json.loads(existing[0])
                    is_funnel = record["topic"] == "funnel" and record.get("stage") not in {"growth","offer"}
                    plan = save_event_check(db, task_id, data) if is_funnel else save_check(db, task_id, data)
                    response = {"plan": plan, "result": None if is_funnel else experiment(plan)}
                elif path == "/api/defer" and not (INVITES and FUNNEL):
                    topic, until, reason = data.get("topic"), data.get("date"), data.get("reason", "").strip()
                    if topic not in TOPICS or not 1 <= len(reason) <= 240:
                        raise ValueError("Выберите сигнал и укажите причину")
                    if date.fromisoformat(until) <= date.today():
                        raise ValueError("Выберите будущую дату")
                    db.execute("INSERT OR REPLACE INTO deferred VALUES (?,?,?)", (topic, until, reason))
                    response = {"ok": True}
                elif path == "/api/research" and not INVITES and not openrouter.ENABLED:
                    response = import_research(db, data.get("items"), TOPICS)
                elif path == "/api/radar/seen" and FUNNEL:
                    radar.mark_seen(db, data.get("id", ""))
                    response = {"ok": True}
                elif path == "/api/radar/resolve" and FUNNEL:
                    response = radar.resolve(db, data, save_task)
                else:
                    return self.reply({"error": "Неизвестное действие"}, status=404)
            return self.reply(response)
        except ModelBusy as exc:
            return self.reply({"error": str(exc)}, status=429)
        except (ValueError, TypeError, AttributeError) as exc:
            return self.reply({"error": str(exc)}, status=400)
        except RuntimeError as exc:
            return self.reply({"error": str(exc)}, status=503)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18763)
    args = parser.parse_args()
    setup()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
