"""Create a small, fictional store for a public checkout of PM Radar.

The historic input workbooks are optional and are never read by this script.
"""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

BOOK = "Учебный магазин"
VERSION = "demo-1"


def source(sheet, row, title, text, kind, **fields):
    return dict(
        id=f"demo:{sheet}:{row}",
        book=BOOK,
        version=VERSION,
        sheet=sheet,
        record=str(row),
        source=f"{BOOK} · {sheet} · {row}",
        title=title,
        text=text,
        kind=kind,
        type=sheet,
        **fields,
    )


def build():
    start = date(2026, 6, 29)
    windows = {
        "summer": (0, 13),
        "aug": (7, 6),
        "oct": (14, 6),
        "oct_partial": (14, 7),
        "oct12": (15, 1),
        "oct19": (16, 1),
        "nov02": (18, 1),
        "nov09": (19, 1),
    }
    curves = {
        "kes": [125 + (i % 4) * 3 if i < 14 else 91 + (i % 3) * 4 for i in range(21)],
        "astra": [108 + i % 5 if i < 18 else [86, 81, 97][i - 18] for i in range(21)],
    }
    sales, orders, series = {}, {}, {}
    for family, values in curves.items():
        rows = [
            dict(
                date=(start + timedelta(weeks=i)).isoformat(),
                value=v,
                average=round(mean(values[i - 3 : i + 1]), 1) if i >= 3 else None,
                partial=i == 20,
                row=i + 1,
            )
            for i, v in enumerate(values)
        ]
        sales[family] = rows
        series[family] = {key: rows[i : i + n] for key, (i, n) in windows.items()}
        orders[family] = {
            key: mean(row["value"] for row in records)
            for key, records in series[family].items()
        }
    task = source(
        "Бэклог",
        1,
        "Проверить передачу события корзины",
        "В учебном бэклоге есть ошибка передачи событий электронной торговли из подбора Kaspersky. "
        "Проверить, записывается ли событие добавления после успешного пополнения корзины.",
        "backlog",
    )
    task.update(
        source_id=task["id"],
        id="T-08",
        status="Открыта",
        priority="Средний",
        metrics="cfg_add_to_cart_rate",
        releases=[],
        mechanism="cart_event",
    )
    navigation = source(
        "Бэклог", 2, "Обновить навигацию личного кабинета",
        "В шапке личного кабинета есть ссылки на поиск товаров, избранное и корзину магазина.",
        "backlog",
    )
    navigation.update(source_id=navigation["id"], id="T-06", status="Готово")
    filters = source(
        "Бэклог", 3, "Выпустить фильтры подбора Kaspersky",
        "В учебном магазине команда выпустила фильтры выбора редакции и числа лицензий. "
        "Описание фиксирует запуск функции и не содержит наблюдений об ошибках после релиза.",
        "backlog",
    )
    filters.update(source_id=filters["id"], id="T-07", status="Готово")
    releases = [
        source(
            "Релизы", i, name, text, "release", date=day, metrics="cfg", study_roles=roles
        )
        for i, (name, text, day, roles) in enumerate(
            [
                ("R-08", "Изменился вход в учебный магазин.", "2026-09-28", ["alternative"]),
                ("R-09", "В учебном магазине появились фильтры подбора.", "2026-10-02", ["alternative"]),
                ("R-10", "Обновлён блок рекомендаций.", "2026-10-23", []),
            ],
            1,
        )
    ]
    astra_cart = {"nov02": (18, 150), "nov09": (19, 238)}
    astra_ratios = {week: {"cfg_add_to_cart_rate": {"desktop": {
        "n": n, "d": d, "rows": 7, "expected_rows": 7,
    }}} for week, (n, d) in astra_cart.items()}
    definitions = {}
    for key, title in {
        "family_orders_idx": "Индекс самостоятельных заказов",
        "cfg_reach_rate": "Охват подбора",
        "cfg_add_to_cart_rate": "Добавление из подбора",
        "cfg_step_dropoff": "Переход ко второму шагу",
    }.items():
        definitions[key] = source(
            "Метрики",
            key,
            title,
            "Учебное определение. Сравниваем полные периоды.",
            "metrics",
            note="",
            rule="Две недели ниже 90",
            scope="Учебный набор",
            target="",
        )
    history = dict(
        orders=orders,
        series=series,
        ratios={"astra": astra_ratios},
        visits={},
        steps={},
        option_counts={},
        jury=False,
        released=releases[1]["date"],
        login=releases[0]["date"],
    )
    catalog = {}
    names = {
        "kes": "Kaspersky Endpoint Security",
        "astra": "Astra Linux",
        "office": "Office Home and Business 2024",
    }
    for product, name in names.items():
        offers = [
            source(
                "Цены",
                product + str(i),
                "Учебное предложение " + str(i),
                f"{name}. Цена в учебном примере {v} ₽.",
                "competitor",
                store=12000,
                amount=v,
                match="Да",
                conditions="Учебное сравнение",
                date="2026-10-22",
            )
            for i, v in enumerate([11600, 12400, 11100], 1)
        ]
        catalog[product] = dict(
            title=name,
            group="ПО",
            sources=[],
            prices=dict(matched=offers, partial=[], below_store=2, store=12000),
            invoice=source(
                "Счета",
                product,
                "Самостоятельный счёт",
                "В учебном примере счёт получен. Исход оплаты неизвестен.",
                "service",
            ),
        )
    office_prices = catalog["office"]["prices"]
    for offer in office_prices["matched"]:
        offer["conditions"] = "Бессрочная лицензия на один ПК"
    invoice_offer = office_prices["matched"][0]
    invoice_offer["conditions"] += " · счёт по запросу"
    invoice_offer["invoice_required"] = True
    office_prices["partial"].append(source(
        "Цены", "office4", "Учебное предложение 4",
        "Годовая подписка. С бессрочной лицензией сопоставима только по названию.",
        "competitor", amount=7500, match="Частичная", conditions="Годовая подписка",
        date=invoice_offer["date"],
    ))
    additional_tasks = []
    for i, (product, identifier, title, text, mechanism) in enumerate((
        ("astra", "A-01", "Сверить результат подбора Astra на ПК",
         "Повторить выбор лицензии Astra и проверить факт добавления и регистрацию в Метрике.", "astra_cart"),
        ("astra", "A-02", "Изменить сортировку каталога", "Обновить порядок отображения товаров в личном кабинете.", None),
        ("office", "O-01", "Сверить экономику сопоставимого Office",
         "Проверить лицензии, себестоимость и оплаты до решения о скидке.", "office_prices"),
        ("office", "O-02", "Переставить кнопку в карточке", "Изменить цвет и место кнопки запроса счёта.", None),
    ), 4):
        entry = source("Бэклог", i, title, text, "backlog", product=product, mechanism=mechanism, status="Открыта")
        entry.update(source_id=entry["id"], id=identifier)
        additional_tasks.append(entry)
    interviews = [
        source("Учебные интервью", i, title, text, "interview", cohort="Демо", role="", study_roles=[study_role])
        for i, (title, text, study_role) in enumerate(
            [
                (
                    "Выбор редакции",
                    "В учебном интервью покупатель сомневается между двумя вариантами лицензии.",
                    "customer",
                ),
                (
                    "Самостоятельная покупка",
                    "В другом примере покупатель без помощи повторил заказ с сайта.",
                    "counterexample",
                ),
                ("Помощь при подборе", "Вопрос менеджеру возник при смене редакции.", "customer"),
                (
                    "Продление Cloud онлайн",
                    "В учебном сценарии продление прошло через корзину.",
                    "counterexample",
                ),
            ],
            1,
        )
    ]
    initiatives = {
        k: source(
            "Инициативы",
            k,
            title,
            "Проверить изменение на подходящих заказах.",
            "metrics",
        )
        for k, title in {
            "office": "Проверка предложения Office",
            "repeat": "Повтор из письма",
        }.items()
    }
    lk_keys = ("lk_reco_status_visits", "lk_reco_shown_share", "lk_reco_ctr")
    return dict(
        synthetic=True,
        history=history,
        sales=sales,
        tasks=[task, navigation, filters, *additional_tasks],
        releases=releases,
        definitions=definitions,
        coverage=dict(
            sales_to="2026-11-17", last_full="2026-11-15", metrics_to="2026-11-17"
        ),
        catalog=catalog,
        threshold=90,
        alerts={
            f: [
                [a, b]
                for a, b in zip(rows, rows[1:])
                if max(a["value"], b["value"]) < 90
            ]
            for f, rows in sales.items()
        },
        initiatives=initiatives,
        lk=dict(
            counts=dict(
                status=320,
                visits_shown=240,
                visits_not_shown=80,
                viewed_visits=200,
                click_visits=18,
            ),
            sources={
                k: source(
                    "Личный кабинет",
                    k,
                    k,
                    "Вымышленный счётчик в демонстрации.",
                    "metrics",
                )
                for k in lk_keys
            },
        ),
        interviews=interviews,
        reach_rows={},
        reach_full=None,
        astra_rows={"cfg_step_dropoff": {}, "cfg_add_to_cart_rate": {"desktop": {
            (start + timedelta(days=18 * 7 + i)).isoformat(): [i + 1] for i in range(14)
        }}},
        book=BOOK,
        version=VERSION,
    )


def build_jury(aggregates):
    """Combine explicitly approved Funnel totals with authored demonstration records."""
    history = aggregates["funnel"]
    if history.get("jury") is not True:
        raise ValueError("Нужен согласованный файл агрегатов жюри.")
    sample = build()
    sample.update(
        demo=True,
        history={key: history[key] for key in ("jury", "released", "login", "orders", "steps", "ratios", "visits")},
        sales={"kes": [], "astra": []},
        alerts={"kes": [], "astra": []},
    )
    sample["releases"].clear()
    for key, title, wording in (
        ("login", "R-08", "Изменение механизма входа ограничивает сравнение визитных долей."),
        ("released", "R-09", "Вышло обновление фильтров подбора Kaspersky. Само совпадение дат не устанавливает причину."),
    ):
        row = source("Хронология", title, title, wording, "release", date=history[key], metrics="cfg")
        row.update(source="Согласованные агрегаты для жюри · " + title, version="jury-aggregates")
        sample["releases"].append(row)
    return sample


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    directory = parser.parse_args().directory
    directory.mkdir(parents=True, exist_ok=True)
    sample = build()
    evidence = json.loads(
        Path(__file__).with_name("evidence.json").read_text(encoding="utf-8")
    )
    evidence["funnel"] = {"jury": True}
    research = [
        dict(
            id=f"D{i:02}",
            kind="interview",
            book="Учебные материалы",
            sheet="Малоактивные",
            record=cell,
            version="demo",
            title=title,
            text=text,
            cohort="Учебная группа",
            role="",
        )
        for i, (cell, title, text) in enumerate(
            [
                (
                    "K10",
                    "Повтор из письма",
                    "В вымышленном интервью покупатель хочет повторить прошлый заказ.",
                ),
                (
                    "K11",
                    "Долгая лицензия",
                    "В учебном примере следующая покупка потребуется через несколько лет.",
                ),
            ],
            1,
        )
    ]
    for name, data in (
        ("store.json", sample),
        ("input.json", evidence),
        ("research.json", research),
    ):
        (directory / name).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
