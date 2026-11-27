"""Comparable purchase signals from v17 and the approved jury aggregates."""

import json
from collections import Counter
from datetime import date, timedelta
from statistics import mean

from openpyxl import load_workbook

from evidence import SOURCE, read_rows

FAMILIES = {"kes": "Kaspersky", "astra": "Astra"}
PRODUCTS = {"kes": "Конфигуратор Kaspersky", "astra": "Конфигуратор Астра"}
SALES_NAMES = {"Kaspersky Endpoint Security": "kes", "Astra Linux Special Edition": "astra"}
WINDOWS = {
    "summer": {"start": "2026-06-29", "weeks": 13, "label": "29.06–27.09", "slot": "before"},
    "aug": {"start": "2026-08-17", "weeks": 6, "label": "17.08–27.09", "slot": "before"},
    "oct": {"start": "2026-10-05", "weeks": 6, "label": "05.10–15.11", "slot": "after"},
    "oct_partial": {"start": "2026-10-05", "weeks": 7, "label": "05.10–22.11", "slot": "after", "partial": True},
    "oct12": {"start": "2026-10-12", "weeks": 1, "label": "12–18.10", "slot": "before", "mate": "oct19"},
    "oct19": {"start": "2026-10-19", "weeks": 1, "label": "19–25.10", "slot": "after", "mate": "oct12"},
    "nov02": {"start": "2026-11-02", "weeks": 1, "label": "02–08.11", "slot": "before", "mate": "nov09"},
    "nov09": {"start": "2026-11-09", "weeks": 1, "label": "09–15.11", "slot": "after", "mate": "nov02"},
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


def days_in(window):
    start = date.fromisoformat(window["start"])
    return [(start + timedelta(days=i)).isoformat() for i in range(7 * window["weeks"])]


def load_history():
    book = load_workbook(next(SOURCE.glob("Датасет*.xlsx")), read_only=True, data_only=True)
    try:
        indices = {}
        for row in read_rows(book["Продажи"]):
            family = SALES_NAMES.get(row["product_family"])
            if family:
                indices[(family, str(row["week_start"])[:10])] = row["orders_index"]
        metrics = {}
        option_rows = {}
        for row in read_rows(book["Метрики_данные"]):
            metric, product = row["metric_id"], row["product"]
            day = str(row["date"])[:10]
            if metric == "cfg_family_views" and product in PRODUCTS.values():
                metrics[(product, metric, row["segment"], day)] = row["value"]
            if metric == "cfg_option_share" and product == PRODUCTS["kes"]:
                option_rows[(row["segment"], day)] = json.loads(row["detail_json"])["visits_by_value"]
            if metric not in {*PAIRS, "cfg_step_dropoff"} or product not in PRODUCTS.values():
                continue
            metrics[(product, metric, row["segment"], day)] = json.loads(row["detail_json"])

        orders, ratios, steps, series, visits = {}, {}, {}, {}, {}
        option_counts = {}
        for family, product in PRODUCTS.items():
            orders[family], ratios[family] = {}, {}
            series[family], visits[family] = {}, {}
            for key, window in WINDOWS.items():
                dates = weeks(window)
                index = [indices[(family, w)] for w in dates if indices.get((family, w)) is not None]
                if len(index) == len(dates):
                    orders[family][key] = mean(index)
                    series[family][key] = [{"date": day, "value": value} for day, value in zip(dates,index,strict=True)]
                days = days_in(window)
                visits[family][key] = {d: value for d in DEVICES if d != "all"
                                       and (value := family_visits(metrics, product, days, d))}
                ratios[family][key] = {
                    metric: {device: value for device in DEVICES
                             if (value := metric_pair(metrics, product, metric, days, device, *fields))}
                    for metric, fields in PAIRS.items()}
                if family == "astra":
                    chain = astra_steps(metrics, product, dates)
                    if chain:
                        steps[key] = chain
                else:
                    option_counts[key] = {}
                    for group in ("edition", "duration", "license_type"):
                        values = Counter()
                        for day in dates:
                            values.update(option_rows.get((group, day), {}))
                        if values:
                            option_counts[key][group] = dict(values.most_common())
        releases = {r["release_id"]: str(r["release_date"])[:10] for r in read_rows(book["Релизы"])}
        return {"orders": orders, "ratios": ratios, "steps": steps, "series": series, "visits": visits,
                "option_counts": option_counts, "released": releases["R-09"],
                "login": releases["R-08"], "jury": False}
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


def family_visits(metrics, product, days, device):
    rows = [metrics[(product, "cfg_family_views", device, day)] for day in days
            if (product, "cfg_family_views", device, day) in metrics]
    return {"total": sum(rows), "days": len(rows), "expected": len(days)} if rows else None


def astra_steps(metrics, product, dates):
    rows = [metrics[(product, "cfg_step_dropoff", "all", w)]["visits_reached_step"]
            for w in dates if (product, "cfg_step_dropoff", "all", w) in metrics]
    return [{"from": i, "to": i+1,
             "n": sum(row[str(i+1)] for row in eligible),
             "d": sum(row[str(i)] for row in eligible), "rows": len(eligible), "expected_rows": len(dates)}
            for i in range(1, 12)
            if (eligible := [row for row in rows if str(i) in row and str(i+1) in row])]


def jury_aggregates(history):
    # Named aggregates from the approved brief. Keep raw series and rows in the closed workspace.
    return {"jury": True, "released": history["released"], "login": history["login"],
            "orders": {f: {k: history["orders"][f][k] for k in ("aug", "oct")} for f in FAMILIES},
            "steps": {k: history["steps"][k][:1] for k in ("oct12", "oct19")},
            "ratios": {
                "kes": {"oct": {"cfg_reach_rate": {"all": history["ratios"]["kes"]["oct"]["cfg_reach_rate"]["all"]}}},
                "astra": {"oct": {"cfg_add_to_cart_rate": {"all": history["ratios"]["astra"]["oct"]["cfg_add_to_cart_rate"]["all"]}}},
            },
            "visits": {"astra": {key: {"desktop": history["visits"]["astra"][key]["desktop"]} for key in ("oct12","oct19")}}}


def options(data):
    if data is None:
        return None
    available = {key: window for key, window in WINDOWS.items() if not data["jury"] or key in ("aug","oct","oct12","oct19")}
    return {"families": FAMILIES, "windows": available, "defaults": DEFAULTS, "devices": DEVICES,
            "audiences": {k: AUDIENCES[k] for k in ("all", "regular", "verified")}}


def selection(args):
    values = {key: args.get(key, default) for key, default in DEFAULTS.items()}
    for key, choices in (("family", FAMILIES), ("before", WINDOWS), ("after", WINDOWS),
                         ("device", DEVICES), ("audience", AUDIENCES)):
        if not isinstance(values[key], str) or values[key] not in choices:
            raise ValueError("Проверьте параметры воронки")
    before, after = WINDOWS[values["before"]], WINDOWS[values["after"]]
    if (before["slot"] != "before" or after["slot"] != "after"
            or (before.get("mate") and before["mate"] != values["after"])
            or (after.get("mate") and after["mate"] != values["before"])):
        raise ValueError("Выберите два окна вокруг релиза или соседние недели из одной пары.")
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
    visits = data.get("visits", {}).get(family, {}) if not audience_gap else {}
    series = data.get("series", {}).get(family, {}) if orders else {}
    order_source = "Учебный магазин · продажи · недельный индекс" if data.get("synthetic") else ORDER_SOURCE
    metric_source = "Учебный магазин · метрики" if data.get("synthetic") else METRIC_SOURCE
    coverage = {"before": WINDOWS[before]["weeks"] if orders.get(family) else 0,
                "after": WINDOWS[after]["weeks"] if orders.get(family) else 0,
                "partial": bool(WINDOWS[after].get("partial"))}
    missing_orders = (audience_gap or ("В BI v17 нет поля устройства." if device != "all" else
                      ("Для этих недель нет разрешённого индекса в демовыборке." if data["jury"] else
                       "Для сравнения нужны индексы всех недель в каждом периоде.")))
    cart_gap = MISSING_CART if family == "kes" else (
        "Для этого среза нет агрегата «открытие → корзина»." if data["jury"] else
        "В выбранном срезе нет пары счётчиков добавлений и открытий.")
    return {"filter": params, "family_name": FAMILIES[family], "jury": data["jury"],
            "orders": orders, "pairs": pairs, "steps": steps, "audience_gap": audience_gap, "coverage": coverage,
            "visits": {"before": {} if tracking_break else visits.get(before, {}), "after": visits.get(after, {})},
            "series": {"before": series.get(before, []), "after": series.get(after, [])},
            "options": data.get("option_counts", {}).get(after, {}) if family=="kes" and device=="all" and not audience_gap else {},
            "orders_gap": missing_orders, "cart_gap": cart_gap, "order_gap": MISSING_ORDER,
            "payment_gap": MISSING_PAYMENT, "tracking_break": tracking_break, "login": data["login"],
            "released": data["released"], "order_source": order_source, "metric_source": metric_source}


def study_case(data, args):
    stage = args.get("stage")
    if not isinstance(stage, str) or stage not in STAGES:
        raise ValueError("Выберите этап воронки")
    r = report(data, args)
    f = r["filter"]
    metric_source = r["metric_source"]
    history_source = "Учебный магазин" if data.get("synthetic") else "Softline v17"
    if r["audience_gap"]:
        raise ValueError(r["audience_gap"])
    chosen = r["orders"].get(f["family"])
    values = (f"{chosen['before']:.1f} → {chosen['after']:.1f} ({chosen['change']:+.1f}%)."
              if chosen else r["orders_gap"])
    measurement = r["pairs"].get("after", {}).get("cfg_add_to_cart_rate")
    measured_cart = (f"{measurement['n']} визитов с добавлением из {measurement['d']} визитов с открытием."
                     if measurement and measurement["rows"] == measurement["expected_rows"] else
                     f"{measurement['n']} визитов с добавлением из {measurement['d']} визитов с открытием по доступным строкам."
                     if measurement else r["cart_gap"])
    cart = {"id": "v17-cart", "title": "Открытие конфигуратора → корзина", "type": "Учёт",
            "text": measured_cart, "source": metric_source + " · cfg_add_to_cart_rate"}
    counts = r["steps"]["after"]
    reach = r["pairs"].get("after", {}).get("cfg_reach_rate")
    selected = (f"{counts[0]['n']} из {counts[0]['d']} визитов достигли шага 2 после шага 1." if counts else
                f"{reach['n']} из {reach['d']} зафиксированных визитов достигли конфигуратора." if reach else
                "В выбранном разрезе нет счётчиков шагов выбора.")
    supports = [
        {"id": "v17-orders", "title": "Динамика самостоятельных заказов", "type": "Индекс BI",
         "text": f"{r['family_name']} · {values} Это средний недельный индекс.", "source": r["order_source"]},
        {"id": "v17-release", "title": "Хронология изменений", "type": "Релизы",
         "text": f"Вход изменён {data['login']}. Фильтры подбора Kaspersky выпущены {data['released']}.",
         "source": history_source + " · Релизы · R-08, R-09"},
    ]
    if stage == "license":
        supports.insert(0, {"id": "v17-choice", "title": "Наблюдаемое начало выбора", "type": "Замер",
                            "text": selected, "source": metric_source + " · cfg_step_dropoff / cfg_reach_rate"})
    if stage == "cart" and measurement:
        supports.insert(0, cart)
    limitations = [
        cart if stage != "cart" or not measurement else
        {"id": "v17-attribution", "title": "Полнота событий", "type": "Ограничение",
         "text": "Зафиксированные события требуют сверки с журналом корзины.", "source": metric_source},
        {"id": "v17-join", "title": "Связка шагов отсутствует", "type": "Ограничение",
         "text": f"{MISSING_ORDER} {MISSING_PAYMENT}", "source": history_source + " · Метрики и продажи"},
    ]
    if r["tracking_break"]:
        limitations.append({"id": "v17-entry", "title": "Изменение механизма входа", "type": "Сопоставимость",
                            "text": "После смены входа мог измениться состав визитов. Сравнение визитных долей через 29.09 некорректно.",
                            "source": history_source + " · Релизы · R-08"})
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
            "supports": supports, "limitations": limitations,
            "confirmation": NO_CONFIRMATION if f["family"] == "kes" else
            "В интервью и конкурентном анализе нет подтверждения причины для этого среза.",
            "historical_result": historical}
