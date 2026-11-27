"""Export the protected LAN projection from the source workbooks; never serve those files."""
import argparse
from collections import Counter
from datetime import date, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from zipfile import ZipFile
from xml.etree import ElementTree

from openpyxl import load_workbook

from evidence import SOURCE, read_rows
from funnel import PRODUCTS, SALES_NAMES, WINDOWS, days_in, load_history, report, selection, weeks

PRODUCT_IDS = ("sobol", "cryptopro", "redos", "kompas", "astra", "contentreader", "nanocad", "office", "kes", "chatgpt")


def open_source(pattern):
    path = next(SOURCE.rglob(pattern))
    return path, "sha256:" + sha256(path.read_bytes()).hexdigest()[:12]


def address(path, version, sheet, record, title, text, **fields):
    return dict(id=f"{path.stem}:{sheet}:{record}", book=path.name, version=version, sheet=sheet,
                record=record, source=f"{path.name} · {sheet} · {record}", title=title, text=text, **fields)


def slide(path, number):
    with ZipFile(path) as file:
        root = ElementTree.fromstring(file.read(f"ppt/slides/slide{number}.xml"))
    return [node.text for node in root.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}t")]


def project_catalog():
    path, version = open_source("Store*.xlsx")
    ppt, ppt_version = open_source("*.pptx")
    fourth, eighteenth = slide(ppt, 4), slide(ppt, 18)
    catalog, prices = {}, {}
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        basket = book["0_Конкуренты_Продукты"]
        for key, (number, row) in zip(PRODUCT_IDS, enumerate(basket.iter_rows(
                min_row=5, max_row=14, min_col=5, max_col=8, values_only=True), 5), strict=True):
            name, priority, count, group = row
            sources = [address(path, version, basket.title, f"E{number}:H{number}", name,
                               f"{group}. {priority}. Представлен на {count} из 65 изученных площадок.", type="Тестовая корзина")]
            if name in fourth:
                abc = fourth[fourth.index(name)+1:fourth.index(name)+4]
                sources.append(address(ppt, ppt_version, "Слайд 4", name, "Класс ABC",
                                       "Оборот / заказы / маржа: " + " / ".join(abc), type="Презентация"))
            catalog[key] = {"title": name, "group": group, "sources": sources}
            prices[key] = []
        price_sheet = book["03_Цена"]
        by_name = {item["title"]: key for key, item in catalog.items()}
        for number, row in enumerate(price_sheet.iter_rows(min_row=5,max_col=14,values_only=True), 5):
            site, name, sku, _, match, _, edition, term, cost, store, _, promo, terms, checked = row
            if name not in by_name or not isinstance(cost, (int, float)):
                continue
            key = by_name[name]
            details = " · ".join(str(value) for value in (sku, edition, term, promo, terms) if value)
            when = str(checked)[:10]
            store_price = f"Store {store:g} ₽" if isinstance(store, (int,float)) else "в строке нет цены Store"
            prices[key].append(address(path, version, price_sheet.title, f"A{number}:N{number}", site,
                                       f"{name} · {cost:g} ₽; {store_price} · {match} · {details}",
                                       type="Замер цены", kind="competitor", amount=cost, store=store, match=match,
                                       conditions=details, date=when))
        invoice = book["04_Покупка_Счет"]["F43"].value
        catalog["office"]["invoice"] = address(path, version, "04_Покупка_Счет", "A43:N43",
            "Самостоятельный счёт Office", f"Один исследовательский проход в Store 27.10.2026. "
            f"Самостоятельное получение счёта за {invoice} мин. Исход оплаты отсутствует.",
            type="Осмотр", kind="competitor")
    finally:
        book.close()
    for key, item in catalog.items():
        offers = prices[key]
        matched = [offer for offer in offers if offer["match"] == "Да" and isinstance(offer["store"], (int,float))]
        item["prices"] = {"matched": matched, "partial": [offer for offer in offers if offer["match"] == "Частично"],
                          "below_store": sum(offer["amount"] < offer["store"] for offer in matched),
                          "store": matched[0]["store"] if matched else None}
    initiatives = {}
    for key, title in (("office","Цены Office и ContentReader"), ("repeat","Повторить прошлый заказ"),
                       ("cryptopro", "КриптоПро + Рутокен")):
        i = eighteenth.index(title)
        initiatives[key] = address(ppt, ppt_version, "Слайд 18", title, title, eighteenth[i+2], type="Инициатива Softline")
    return catalog, initiatives


def interview_records():
    result = []
    for pattern, selections in (
        ("E-com*.xlsx", (("Активные", 9, "L9", "Канал покупки Kaspersky"),
                         ("Новички", 6, "F6", "Выбор опции на сайте"),
                         ("Новички", 6, "I6", "Онлайн и консультация по лицензии"))),
        ("Сервисные*.xlsx", (("Small_Результаты анализа", 7, "C7, D7, E7, G7, J7, K7", "Продление KES Cloud"),)),
    ):
        path, version = open_source(pattern)
        book = load_workbook(path, read_only=True, data_only=True)
        for sheet, number, cells, title in selections:
            row = next(book[sheet].iter_rows(min_row=number,max_row=number,max_col=12,values_only=True))
            values = [row[ord(cell[0])-ord("A")] for cell in cells.split(", ")]
            role = row[2] if pattern.startswith("Сервис") else ""
            result.append(address(path, version, sheet, cells, title, " · ".join(values),
                                  type="Интервью", kind="interview", cohort=sheet, role=role))
        book.close()
    return result


def export_history():
    path, version = open_source("Датасет*.xlsx")
    book = load_workbook(path, read_only=True, data_only=True)
    history = load_history()
    def source(sheet, at, title, text, **fields):
        return address(path, version, sheet, at, title, text, **fields)
    try:
        sales = {family: [] for family in SALES_NAMES.values()}
        covered_to = None
        for number, row in enumerate(read_rows(book["Продажи"]), 2):
            family = SALES_NAMES[row["product_family"]]
            week = str(row["week_start"])[:10]
            note = row["comment"] or ""
            if found := re.search(r"\d{2}\.\d{2}\.\d{4}", note):
                d, m, y = found[0].split(".")
                covered_to = f"{y}-{m}-{d}"
            sales[family].append({"date": week, "value": row["orders_index"], "average": row["orders_index_4w"],
                                  "partial": "неполной" in note, "row": number})
        last_full = (date.fromisoformat(max(row["date"] for row in sales["kes"] if not row["partial"])) + timedelta(days=6)).isoformat()
        releases = []
        for number, row in enumerate(read_rows(book["Релизы"]), 2):
            event = source("Релизы", f"A{number}:G{number}", row["release_id"], row["description"],
                           type="Событие", kind="release", date=str(row["release_date"])[:10],
                           metrics=row["affected_metrics"], related=row["related_task_ids"])
            releases.append(event)
        tasks = []
        for number, row in enumerate(read_rows(book["Бэклог_задачи"]), 2):
            fact = source("Бэклог_задачи", f"A{number}:K{number}", row["title"], row["description_short"],
                          type="Исходная задача", kind="backlog")
            tasks.append({**fact, "source_id": fact["id"], "id": row["task_id"], "status": row["status"],
                          "priority": row["priority"], "metrics": row["linked_metric_ids"],
                          "releases": [event["title"] for event in releases if row["task_id"] in event["related"]]})
        definitions = {}
        for number, row in enumerate(read_rows(book["Метрики_справочник"]), 2):
            definitions[row["metric_id"]] = source("Метрики_справочник", f"A{number}:J{number}", row["metric_name"],
                row["formula_or_logic"], type="Определение", kind="metrics", rule=row["bad_signal"],
                scope=row["segment"], target=row["target_value"], note=row["comment"])
        threshold = int(re.search(r"ниже\s+(\d+)", definitions["family_orders_idx"]["rule"])[1])
        alerts = {}
        for family, entries in sales.items():
            alerts[family] = [[a,b] for a,b in zip(entries, entries[1:]) if not b["partial"] and
                              a["value"] < threshold and b["value"] < threshold and
                              date.fromisoformat(b["date"]) - date.fromisoformat(a["date"]) == timedelta(days=7)]
        lk, lk_rows, reach_rows, reach_full = Counter(), {}, {}, Counter()
        astra_rows = {"cfg_step_dropoff": {}, "cfg_add_to_cart_rate": {}}
        filters_day = next(r["date"] for r in releases if r["title"] == "R-09")
        max_metric_date = ""
        for number, row in enumerate(read_rows(book["Метрики_данные"]), 2):
            day, metric = str(row["date"])[:10], row["metric_id"]
            max_metric_date = max(max_metric_date, day)
            if row["product"] == PRODUCTS["astra"] and metric in astra_rows:
                astra_rows[metric].setdefault(row["segment"], {}).setdefault(day, []).append(number)
            if metric == "cfg_reach_rate" and row["product"] == "Конфигуратор Kaspersky" and row["segment"] in ("desktop","mobile","tablet"):
                reach_rows.setdefault(day, []).append(number)
                if day >= filters_day:
                    reach_full.update(json.loads(row["detail_json"]))
            if "2026-10-26" <= day <= "2026-11-22" and metric in ("lk_reco_shown_share","lk_reco_status_visits","lk_reco_ctr"):
                lk_rows.setdefault(metric, []).append(number)
                if metric == "lk_reco_status_visits":
                    lk["status"] += row["value"]
                else:
                    lk.update(json.loads(row["detail_json"]))
        lk_sources = {metric: source("Метрики_данные", f"строки {min(rows)}–{max(rows)} · {metric}", definitions[metric]["title"],
                    definitions[metric]["text"],type="Метрика") for metric, rows in lk_rows.items()}
    finally:
        book.close()
    catalog, initiatives = project_catalog()
    return {"history": history, "sales": sales, "definitions": definitions, "releases": releases, "tasks": tasks,
            "coverage": {"sales_to": covered_to, "last_full": last_full, "metrics_to": max_metric_date},
            "alerts": alerts, "threshold": threshold, "catalog": catalog, "initiatives": initiatives,
            "lk": {"counts": dict(lk), "sources": lk_sources}, "reach_rows": reach_rows,
            "reach_full": {"n":reach_full["configurator_visits"],"d":reach_full["family_visits"],"since":filters_day},
            "interviews": interview_records(), "astra_rows": astra_rows,
            "book": path.name, "version": version}


def sales_basis(store, family, windows):
    if store.get("demo"):
        averages = store["history"]["orders"][family]
        values = [f"{window['label']}: {averages[key]:.2f}" for key, window in WINDOWS.items()
                  if window in windows and key in averages]
        return {"id": "sales-" + family, "title": "Средний недельный индекс", "type": "Индекс BI",
                "source": "Согласованные агрегаты для жюри · самостоятельные заказы", "version": store["version"],
                "text": "; ".join(values) if values else "Для выбранного окна агрегат недоступен."}
    dates = {day for window in windows for day in weeks(window)}
    points = [point for point in store["sales"][family] if point["date"] in dates]
    ids = ", ".join(str(point["row"]) for point in points)
    return {"id": "sales-" + family, "title": "Недели, использованные в расчёте", "type": "Индекс BI",
            "source": f'{store["book"]} · Продажи · строки {ids}', "version": store["version"],
            "text": "; ".join(f'{point["date"]} · {point["value"]}' + (" (неполная)" if point["partial"] else "")
                              for point in points) + ". База 100: 04.05–28.06.2026."}


def astra_alert(store, before, after):
    selected_days = set(days_in(WINDOWS[before]) + days_in(WINDOWS[after]))
    matches = [pair for pair in store["alerts"]["astra"]
               if all(point["date"] in selected_days for point in pair)]
    return matches[-1] if matches else None


def astra_diagnostic(store, args):
    filters = selection(args)
    finding = args.get("finding", "comparison")
    before, after = filters["before"], filters["after"]
    windows = [WINDOWS[key] for key in (before, after)]
    if filters["family"] != "astra" or not windows[0].get("mate") or finding not in {"comparison", "below90"}:
        raise ValueError("Для разбора Astra выберите пару соседних недель.")
    pair = next((points for points in store["alerts"]["astra"]
                 if [p["date"] for p in points] == [w["start"] for w in windows]), None)
    if finding == "below90" and pair is None:
        raise ValueError("Для указанных недель нет сигнала ниже порога.")
    all_devices = report(store["history"], {**filters, "device": "all", "audience": "all"})
    desktop = report(store["history"], {**filters, "device": "desktop", "audience": "all"})
    evidence = [sales_basis(store, "astra", windows), store["definitions"]["family_orders_idx"]]
    periods = {}
    for slot, window in zip(("before", "after"), windows, strict=True):
        cart = desktop["pairs"][slot].get("cfg_add_to_cart_rate")
        steps = all_devices["steps"][slot]
        step = steps[0] if steps else None
        points = all_devices["series"][slot]
        periods[slot] = {"label":window["label"], "index":points[0]["value"] if points else None,
                         "cart":cart, "step":step}
        for metric, device, measure, title in (
            ("cfg_add_to_cart_rate", "desktop", cart, "Подбор → корзина · компьютеры"),
            ("cfg_step_dropoff", "all", step, "Шаг 1 → 2 · все устройства")
        ):
            if not measure:
                continue
            rows = store["astra_rows"][metric].get(device, {})
            numbers = sorted(number for day in days_in(window) for number in rows.get(day, []))
            record = ", ".join(map(str, numbers))
            evidence.append({"id":f"astra-{metric}-{slot}", "type":"Счётчики", "title":title,
                             "source":("Согласованные агрегаты для жюри · шаги подбора" if store.get("demo")
                                       else f'{store["book"]} · Метрики_данные · строки {record}'),
                             "version":store["version"],
                             "text":f'{window["label"]}: {measure["n"]} из {measure["d"]}. '
                                    f'Покрытие {measure["rows"]}/{measure["expected_rows"]}.'})
    return {"filter":filters, "finding":finding, "threshold":store["threshold"], "periods":periods,
            "visits":all_devices["visits"], "evidence":evidence}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    target = parser.parse_args().output
    os.umask(0o077)
    temporary = target.with_suffix(".new")
    temporary.write_text(json.dumps(export_history(), ensure_ascii=False, default=str))
    temporary.replace(target)
