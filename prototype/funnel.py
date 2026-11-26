"""Comparable purchase signals from v17 and the approved jury aggregates."""

import json
from datetime import date, timedelta
from statistics import mean

from openpyxl import load_workbook

from evidence import SOURCE, read_rows

FAMILIES = {"kes": "Kaspersky", "astra": "Astra"}
PRODUCTS = {"kes": "Конфигуратор Kaspersky", "astra": "Конфигуратор Астра"}
SALES_NAMES = {"Kaspersky Endpoint Security": "kes", "Astra Linux Special Edition": "astra"}
WINDOWS = {
    "aug": {"start": "2026-08-17", "weeks": 6, "label": "17.08–27.09", "slot": "before"},
    "oct": {"start": "2026-10-05", "weeks": 6, "label": "05.10–15.11", "slot": "after"},
    "oct12": {"start": "2026-10-12", "weeks": 1, "label": "12–18.10", "slot": "before"},
    "oct19": {"start": "2026-10-19", "weeks": 1, "label": "19–25.10", "slot": "after"},
}
DEFAULTS = {"family": "kes", "before": "aug", "after": "oct", "device": "all", "audience": "all"}
DEVICES = {"all": "Все устройства", "desktop": "Компьютер", "mobile": "Телефон", "tablet": "Планшет"}
AUDIENCES = {"all": "Все покупатели", "regular": "Обычный клиент", "verified": "Верифицированный клиент",
             "b2b": "B2B", "b2c": "B2C"}
AUDIENCE_GAPS = {
    "regular": "Для обычного и верифицированного клиента есть осмотр ЛК. В событиях и BI v17 нет полей роли и признака B2B/B2C.",
    "verified": "Для обычного и верифицированного клиента есть осмотр ЛК. В событиях и BI v17 нет полей роли и признака B2B/B2C.",
    "b2b": "В событиях и BI v17 нет признака физлица или юрлица. Роли обычного и верифицированного клиента описывают доступ в ЛК.",
    "b2c": "В событиях и BI v17 нет признака физлица или юрлица. Роли обычного и верифицированного клиента описывают доступ в ЛК.",
}
STAGES = {"license": "Выбор лицензии", "cart": "Корзина", "order": "Самостоятельный заказ", "paid": "Оплата"}
LOGIN_DAY = "2026-09-29"
ORDER_SOURCE = "Softline v17 · Продажи · orders_index · самостоятельные заказы"
METRIC_SOURCE = "Softline v17 · Метрики_данные"
MISSING_CART = "Для Kaspersky нет ряда добавлений из конфигуратора. Корзина может работать, хотя событие теряется."
MISSING_ORDER = "В Метрике и BI нет общего идентификатора визита и заказа."
MISSING_PAYMENT = "В v17 нет исходов оплаты и связи счёта с заказом."
NO_CONFIRMATION = "В интервью и конкурентном анализе нет подтверждения, что именно релиз подбора вызвал спад."
NO_RELEASE_RESULT = "В v17 нет результата сверки фактического добавления с событием после релиза."
PAIRS = {"cfg_add_to_cart_rate": ("add_to_cart", "open"),
         "cfg_reach_rate": ("configurator_visits", "family_visits")}


def weeks(window):
    first = date.fromisoformat(window["start"])
    return [(first + timedelta(weeks=i)).isoformat() for i in range(window["weeks"])]


def load_history():
    book = load_workbook(next(SOURCE.glob("Датасет*.xlsx")), read_only=True, data_only=True)
    try:
        indices = {}
        for row in read_rows(book["Продажи"]):
            family = SALES_NAMES.get(row["product_family"])
            if family:
                indices[(family, str(row["week_start"])[:10])] = row["orders_index"]
        metrics = {}
        for row in read_rows(book["Метрики_данные"]):
            metric, product = row["metric_id"], row["product"]
            if metric not in {*PAIRS, "cfg_step_dropoff"} or product not in PRODUCTS.values():
                continue
            metrics[(product, metric, row["segment"], str(row["date"])[:10])] = json.loads(row["detail_json"])

        orders, ratios, steps = {}, {}, {}
        for family, product in PRODUCTS.items():
            orders[family], ratios[family] = {}, {}
            for key, window in WINDOWS.items():
                dates = weeks(window)
                index = [indices[(family, w)] for w in dates if indices.get((family, w)) is not None]
                if len(index) == len(dates):
                    orders[family][key] = mean(index)
                start = date.fromisoformat(window["start"])
                days = [(start + timedelta(days=i)).isoformat() for i in range(7 * len(dates))]
                ratios[family][key] = {
                    metric: {device: value for device in DEVICES
                             if (value := metric_pair(metrics, product, metric, days, device, *fields))}
                    for metric, fields in PAIRS.items()}
                if family == "astra":
                    chain = astra_steps(metrics, product, dates)
                    if chain:
                        steps[key] = chain
        task = next(row for row in read_rows(book["Бэклог_задачи"]) if row["task_id"] == "T-08")
        releases = {r["release_id"]: str(r["release_date"])[:10] for r in read_rows(book["Релизы"])}
        return {"orders": orders, "ratios": ratios, "steps": steps, "released": releases["R-09"],
                "login": releases["R-08"], "task": {"id": task["task_id"], "title": task["title"],
                                                    "status": task["status"]}, "jury": False}
    finally:
        book.close()


def metric_pair(metrics, product, metric, dates, device, numerator, denominator):
    segments = tuple(device for device in DEVICES if device != "all") if device == "all" else (device,)
    rows = [(day, metrics[(product, metric, segment, day)])
            for day in dates for segment in segments if (product, metric, segment, day) in metrics]
    if not rows:
        return None
    n, d = sum(r[numerator] for _, r in rows), sum(r[denominator] for _, r in rows)
    return {"n": n, "d": d, "rows": len(rows), "expected_rows": len(dates)*len(segments)}


def astra_steps(metrics, product, dates):
    rows = [metrics[(product, "cfg_step_dropoff", "all", w)]["visits_reached_step"]
            for w in dates if (product, "cfg_step_dropoff", "all", w) in metrics]
    return [{"from": i, "to": i+1,
             "n": sum(row[str(i+1)] for row in eligible),
             "d": sum(row[str(i)] for row in eligible), "rows": len(eligible), "expected_rows": len(dates)}
            for i in range(1, 12)
            if (eligible := [row for row in rows if str(i) in row and str(i+1) in row])]


def jury_aggregates(history):
    # Only the approval scope: the two six-week indexes and Astra's two named transitions.
    return {"jury": True, "released": history["released"], "login": history["login"],
            "orders": {f: {k: history["orders"][f][k] for k in ("aug", "oct")} for f in FAMILIES},
            "steps": {k: history["steps"][k][:1] for k in ("oct12", "oct19")},
            "ratios": {}, "task": {"id": "T-08", "title": "Проверить передачу событий электронной торговли",
                                    "status": "Открыта"}}


def options(data):
    if data is None:
        return None
    return {"families": FAMILIES, "windows": WINDOWS, "defaults": DEFAULTS, "devices": DEVICES,
            "audiences": {k: AUDIENCES[k] for k in ("all", "regular", "verified")}}


def selection(args):
    values = {key: args.get(key, default) for key, default in DEFAULTS.items()}
    for key, choices in (("family", FAMILIES), ("before", WINDOWS), ("after", WINDOWS),
                         ("device", DEVICES), ("audience", AUDIENCES)):
        if not isinstance(values[key], str) or values[key] not in choices:
            raise ValueError("Проверьте параметры воронки")
    before, after = WINDOWS[values["before"]], WINDOWS[values["after"]]
    if before["slot"] != "before" or after["slot"] != "after" or before["weeks"] != after["weeks"]:
        raise ValueError("Выберите два последовательных периода одинаковой длины")
    return values


def delta(history, family, before, after):
    first, second = (history["orders"].get(family, {}).get(p) for p in (before, after))
    if first is None or second is None or first == 0:
        return None
    return {"before": first, "after": second, "change": (second / first - 1) * 100}


def comparable_pairs(data, family, before, after, device, tracking_break):
    def period(window):
        base = data["ratios"].get(family, {}).get(window, {})
        return {metric: value[device] for metric, value in base.items() if device in value}
    return {"before": {} if tracking_break else period(before), "after": period(after)}


def report(data, args):
    params = selection(args)
    family, before, after, device, audience = (params[k] for k in DEFAULTS)
    tracking_break = WINDOWS[before]["start"] < data["login"] <= WINDOWS[after]["start"]
    audience_gap = AUDIENCE_GAPS.get(audience)
    orders = {f: delta(data, f, before, after) for f in FAMILIES} if not audience_gap and device == "all" else {}
    pairs = comparable_pairs(data, family, before, after, device, tracking_break) if not audience_gap else {}
    show_steps = family == "astra" and device == "all" and not audience_gap
    steps = {"before": data["steps"].get(before, []) if show_steps and not tracking_break else [],
             "after": data["steps"].get(after, []) if show_steps else []}
    missing_orders = (audience_gap or ("В BI v17 нет поля устройства." if device != "all" else
                      ("Для этих недель нет разрешённого индекса в демовыборке." if data["jury"] else
                       "Для сравнения нужны индексы всех недель в каждом периоде.")))
    cart_gap = MISSING_CART if family == "kes" else (
        "Для этого среза нет агрегата «открытие → корзина»." if data["jury"] else
        "В выбранном срезе нет пары счётчиков добавлений и открытий.")
    return {"filter": params, "family_name": FAMILIES[family], "jury": data["jury"],
            "orders": orders, "pairs": pairs, "steps": steps, "audience_gap": audience_gap,
            "orders_gap": missing_orders, "cart_gap": cart_gap, "order_gap": MISSING_ORDER,
            "payment_gap": MISSING_PAYMENT, "tracking_break": tracking_break, "login": data["login"],
            "released": data["released"], "order_source": ORDER_SOURCE, "metric_source": METRIC_SOURCE}


def study_case(data, args):
    stage = args.get("stage")
    if not isinstance(stage, str) or stage not in STAGES:
        raise ValueError("Выберите этап воронки")
    r = report(data, args)
    f = r["filter"]
    if r["audience_gap"]:
        raise ValueError(r["audience_gap"])
    chosen = r["orders"].get(f["family"])
    values = (f"{chosen['before']:.1f} → {chosen['after']:.1f} ({chosen['change']:+.1f}%)."
              if chosen else r["orders_gap"])
    related = data["task"] if f["family"] == "kes" and stage in {"cart", "order"} else None
    measurement = r["pairs"].get("after", {}).get("cfg_add_to_cart_rate")
    measured_cart = (f"{measurement['n']} визитов с добавлением из {measurement['d']} визитов с открытием."
                     if measurement and measurement["rows"] == measurement["expected_rows"] else
                     f"{measurement['n']} визитов с добавлением из {measurement['d']} визитов с открытием по доступным строкам."
                     if measurement else r["cart_gap"])
    cart = {"id": "v17-cart", "title": "Открытие конфигуратора → корзина", "type": "Учёт",
            "text": measured_cart, "source": METRIC_SOURCE + " · cfg_add_to_cart_rate"}
    counts = r["steps"]["after"]
    reach = r["pairs"].get("after", {}).get("cfg_reach_rate")
    selected = (f"{counts[0]['n']} из {counts[0]['d']} визитов достигли шага 2 после шага 1." if counts else
                f"{reach['n']} из {reach['d']} зафиксированных визитов достигли конфигуратора." if reach else
                "В выбранном разрезе нет счётчиков шагов выбора.")
    supports = [
        {"id": "v17-orders", "title": "Динамика самостоятельных заказов", "type": "Индекс BI",
         "text": f"{r['family_name']} · {values} Это средний недельный индекс.", "source": ORDER_SOURCE},
        {"id": "v17-release", "title": "Хронология изменений", "type": "Релизы",
         "text": f"Вход изменён {data['login']}. Фильтры подбора Kaspersky выпущены {data['released']}.",
         "source": "Softline v17 · Релизы · R-08, R-09"},
    ]
    if stage == "license":
        supports.insert(0, {"id": "v17-choice", "title": "Наблюдаемое начало выбора", "type": "Замер",
                            "text": selected, "source": METRIC_SOURCE + " · cfg_step_dropoff / cfg_reach_rate"})
    if stage == "cart" and measurement:
        supports.insert(0, cart)
    limitations = [
        cart if stage != "cart" or not measurement else
        {"id": "v17-attribution", "title": "Полнота событий", "type": "Ограничение",
         "text": "Зафиксированные события требуют сверки с журналом корзины.", "source": METRIC_SOURCE},
        {"id": "v17-join", "title": "Связка шагов отсутствует", "type": "Ограничение",
         "text": f"{MISSING_ORDER} {MISSING_PAYMENT}", "source": "Softline v17 · Метрики и продажи"},
    ]
    if r["tracking_break"]:
        limitations.append({"id": "v17-entry", "title": "Изменение механизма входа", "type": "Сопоставимость",
                            "text": "После смены входа мог измениться состав визитов. Сравнение визитных долей через 29.09 некорректно.",
                            "source": "Softline v17 · Релизы · R-08"})
    action = {"license": "Воспроизвести путь выбора лицензии на компьютере и телефоне",
              "cart": "Сверить фактическое добавление с событием корзины",
              "order": "Сверить корзину с событиями и самостоятельным заказом",
              "paid": "Проверить связку заказа, счёта и оплаты"}[stage]
    criterion = {
        "cart": "Для компьютера и телефона записать выбранную лицензию, фактическое содержимое корзины и событие "
        "с тем же идентификатором. Каждому успешному добавлению соответствует ровно одно событие. "
        "Если действие работает, а событие пропало или дублируется, исправить учёт. "
        "Если добавление ломается, воспроизвести сбой и вынести решение об откате на PM.",
        "license": "На компьютере и телефоне пройти подбор и сверить выбранную лицензию и исход каждого шага. "
        "Зафиксировать незавершённый шаг и условие воспроизведения.",
        "order": "Сверить факт добавления с событием. Затем для каждого тестового самостоятельного заказа "
        "сверить идентификаторы корзины и заказа, признак самостоятельного канала и состав заказа.",
        "paid": "Для выставленного счёта сверить идентификаторы заказа, счёта и платежа. "
        "Проверить подтверждённый исход оплаты и зафиксировать отсутствующие поля.",
    }[stage]
    historical = {"cart": NO_RELEASE_RESULT, "license": "В v17 нет результата проверки выбранного шага после релиза.",
                  "order": MISSING_ORDER, "paid": MISSING_PAYMENT}[stage]
    scope = {"этап": STAGES[stage], "семейство": r["family_name"], "устройство": DEVICES[f["device"]],
             "аудитория": AUDIENCES[f["audience"]], "периоды": [WINDOWS[f[k]]["label"] for k in ("before", "after")]}
    return {"filter": f, "stage": stage, "scope": scope, "action": action, "criterion": criterion,
            "supports": supports, "limitations": limitations, "candidate": related,
            "confirmation": NO_CONFIRMATION if f["family"] == "kes" else
            "В интервью и конкурентном анализе нет подтверждения причины для этого среза.",
            "historical_result": historical}
