import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def setup_workflow(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY, study TEXT, scenario TEXT NOT NULL, model TEXT NOT NULL,
            started TEXT NOT NULL, elapsed_ms INTEGER, prompt_tokens INTEGER,
            completion_tokens INTEGER, cached_tokens INTEGER, status TEXT NOT NULL, request_key TEXT
        );
        CREATE INDEX IF NOT EXISTS calls_study ON calls(study);
        CREATE TABLE IF NOT EXISTS research (
            id TEXT PRIMARY KEY, payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS checks (
            task INTEGER PRIMARY KEY REFERENCES tasks(id), payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS deferred (
            topic TEXT PRIMARY KEY, until_date TEXT NOT NULL, reason TEXT NOT NULL
        );
    """)
    columns = {row[1] for row in db.execute("PRAGMA table_info(calls)")}
    for field in ("request_key", "platform", "generation", "actual_cost", "currency", "receipt", "upstream"):
        if field not in columns:
            db.execute(f"ALTER TABLE calls ADD COLUMN {field} TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS calls_request ON calls(request_key)")
    db.execute("UPDATE calls SET status='interrupted' WHERE status='running'")


def words(value):
    return {p[:5] for p in re.findall(r"[\w-]{4,}", value.casefold().replace("ё", "е"))}


def shortlist(uploaded, question, topics):
    query = words(question)
    ranked = []
    for item in uploaded:
        if item["topic"] in topics:
            overlap = len(query & words(item["title"] + " " + item["text"]))
            if overlap:
                ranked.append((overlap, item["id"], item))
    return [(score, item) for score, _, item in sorted(ranked, reverse=True)[:3]]


def import_research(db, rows, topics):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError("Загрузите от 1 до 1000 источников")
    inputs = []
    for row in rows:
        field_limits = {"title": 120, "text": 1000, "source": 160, "version": 60}
        if not isinstance(row, dict) or row.get("topic") not in topics:
            raise ValueError("Укажите тему каждого исследования")
        clean = {}
        for field, limit in field_limits.items():
            value = row.get(field)
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
                raise ValueError(f"Проверьте поле {field}, максимум {limit} символов")
            clean[field] = value.strip()
        clean["topic"] = row["topic"]
        try:
            clean["date"] = date.fromisoformat(row.get("date", "")).isoformat()
        except (ValueError, TypeError) as exc:
            raise ValueError("Укажите дату исследования в формате ГГГГ-ММ-ДД") from exc
        item_id = "R" + digest(clean)[:12]
        item = dict(clean, id=item_id, type="Добавленное исследование", image="")
        inputs.append((item_id, json.dumps(item, ensure_ascii=False)))
    before = db.total_changes
    db.executemany("INSERT OR IGNORE INTO research VALUES (?,?)", inputs)
    return {"added": db.total_changes - before}


def usage_for(db, study):
    return [dict(row) for row in db.execute("SELECT * FROM calls WHERE study=? ORDER BY id", (study,))]


def usage_sum(calls):
    measured = [c for c in calls if c["prompt_tokens"] is not None and c["completion_tokens"] is not None]
    external = [c for c in calls if c["currency"] == "USD"]
    charged = [Decimal(c["actual_cost"]) for c in external if c["actual_cost"] is not None]
    return {"calls": len(calls), "measured": len(measured),
            "prompt": sum(c["prompt_tokens"] for c in measured),
            "completion": sum(c["completion_tokens"] for c in measured),
            "elapsed_ms": sum(c["elapsed_ms"] or 0 for c in calls), "rub": 0,
            "usd": format(sum(charged, Decimal(0)), "f") if charged else None,
            "usd_calls": len(external), "usd_confirmed": len(charged)}


def verification_defaults(metric):
    return {"metric": metric, "guard": "Доля обращений к менеджеру", "target": 2,
            "guard_max": 2, "date": date.today().isoformat(), "sample": False,
            "control_n": 300, "variant_n": 300, "control_paid": 45, "variant_paid": 53,
            "control_guard": 30, "variant_guard": 31, "decision": ""}


def interval(control, variant, n_control, n_variant):
    def wilson(count, size):
        p = count / size
        z = 1.96
        denominator = 1 + z*z/size
        middle = (p + z*z/(2*size)) / denominator
        half = (z / denominator) * math.sqrt(p*(1-p)/size + z*z/(4*size**2))
        return p, middle-half, middle+half

    a, a_low, a_high = wilson(control, n_control)
    b, b_low, b_high = wilson(variant, n_variant)
    delta = b-a
    lower = delta - math.hypot(b-b_low, a_high-a)
    upper = delta + math.hypot(b_high-b, a-a_low)
    return 100*delta, 100*lower, 100*upper


def experiment(plan):
    if not plan["sample"]:
        return None
    denominators = plan["control_n"], plan["variant_n"]
    paid = interval(plan["control_paid"], plan["variant_paid"], *denominators)
    guard = interval(plan["control_guard"], plan["variant_guard"], *denominators)
    if guard[0] > plan["guard_max"]:
        outcome = "Защитный порог нарушен. Остановить расширение."
    elif paid[2] < plan["target"]:
        outcome = "Минимальный эффект не достигнут"
    elif paid[1] >= plan["target"] and guard[2] <= plan["guard_max"]:
        outcome = "Условия масштабирования выполнены"
    else:
        outcome = "Данных недостаточно"
    return {"delta": paid[0], "low": paid[1], "high": paid[2],
            "guard_delta": guard[0], "guard_high": guard[2], "outcome": outcome}


def save_check(db, task, payload):
    plan = {}
    for key, limit in {"metric": 150, "guard": 150, "decision": 700}.items():
        value = payload.get(key, "")
        if not isinstance(value, str) or len(value.strip()) > limit or (not value.strip() and key != "decision"):
            raise ValueError("Проверьте название метрики, защитный показатель и решение PM")
        plan[key] = value.strip()
    for key in ("target", "guard_max"):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise ValueError("Порог должен быть от 0 до 100 процентных пунктов")
        plan[key] = value
    try:
        plan["date"] = date.fromisoformat(payload.get("date", "")).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("Укажите дату проверки") from exc
    plan["sample"] = payload.get("sample") is True
    for group in ("control", "variant"):
        size_key = group + "_n"
        size = payload.get(size_key)
        if type(size) is not int or not 1 <= size <= 1_000_000:
            raise ValueError("Размер группы должен быть от 1 до 1 000 000")
        plan[size_key] = size
        for metric in ("paid", "guard"):
            key = group + "_" + metric
            value = payload.get(key)
            if type(value) is not int or not 0 <= value <= size:
                raise ValueError("Число исходов должно быть целым и не выше размера группы")
            plan[key] = value
    db.execute("INSERT INTO checks VALUES (?,?) ON CONFLICT(task) DO UPDATE SET payload=excluded.payload",
               (task, json.dumps(plan, ensure_ascii=False)))
    return plan
