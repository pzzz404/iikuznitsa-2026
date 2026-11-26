"""Export an address-level projection from the local workbooks for protected LAN use."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path

from openpyxl import load_workbook

from evidence import SOURCE, facts_and_tasks, read_rows


# Allowlisted answer cells, with a role only where its original cell is anonymous.
ANSWERS = {
    "Активные": ("B5", "B14", "B28", "D29"),
    "Малоактивные": ("C3", "L7", "C8", "K10", "C11", "L11"),
    "Новички": ("D11", "E11"),
    "Отток": ("I3", "I7", "I12"),
}


def build():
    rows = []

    def open_book(pattern):
        path = next(SOURCE.rglob(pattern))
        book = load_workbook(path, read_only=True, data_only=True)
        version = "sha256:" + sha256(path.read_bytes()).hexdigest()[:12]

        def add(kind, sheet, cell, title, text, **metadata):
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"Ожидалась текстовая запись {sheet}!{cell}")
            rows.append(dict(id=f"S{len(rows)+1:02}", kind=kind, book=path.name, sheet=sheet, record=cell,
                             version=version, title=title, text=text, **metadata))

        return book, add

    book, add = open_book("E-com*.xlsx")
    for cohort, addresses in ANSWERS.items():
        sheet = book[cohort]
        for address in addresses:
            cell = sheet[address]
            question = sheet.cell(2, cell.column).value
            role = sheet["A10"].value if (cohort, address) == ("Малоактивные", "K10") else ""
            add("interview", cohort, address, question, cell.value, cohort=cohort, role=role)
    book.close()
    book, add = open_book("Отток клиентов*.xlsx")
    for address in ("C5", "D5"):
        cell = book["CustDev_Small"][address]
        add("interview", "CustDev_Small", address, book["CustDev_Small"].cell(2, cell.column).value,
            cell.value, cohort="Small · исследование оттока")
    book.close()

    book, add = open_book("Store*.xlsx")
    sheet = book["06_Личный_Кабинет"]
    for number, row in enumerate(sheet.iter_rows(min_row=5, max_row=15, max_col=4, values_only=True), 5):
        site, _, history, repeat = row
        add("competitor", sheet.title, f"A{number}, C{number}:D{number}", site,
            f"{site} · {sheet['C4'].value}: {history}. {sheet['D4'].value}: {repeat}.", derived=True)
    book.close()

    book, add = open_book("Датасет*.xlsx")
    facts, tasks = facts_and_tasks()
    coverage = next(f for f in facts if f["id"] == "F11")
    add("metrics", "Продажи", "channel · все строки", "Покрытие заказов, оплат и канала менеджера",
        coverage["text"], derived=True)
    engagement = next(f for f in facts if f["id"] == "F10")
    add("metrics", "Метрики_данные", "lk_reco_ctr · 26.10–22.11", engagement["title"], engagement["text"], derived=True)
    metric_keys = [row["metric_id"] for row in read_rows(book["Метрики_справочник"])]
    add("metrics", "Метрики_справочник", "metric_id · все строки", "Перечень доступных показателей",
        "Справочник содержит метрики: " + ", ".join(metric_keys)
        + ". В перечне нет показателя оплаченного повтора из письма и размера аудитории продлений.", derived=True)
    for number, item in enumerate(tasks, 2):
        add("backlog", "Бэклог_задачи", f"A{number}:B{number}, D{number}",
            f'{item["task_id"]} · {item["title"]}', f'Статус: {item["status"]}. {item["title"]}', derived=True)
    book.close()
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    target = parser.parse_args().output
    temporary = target.with_suffix(".new")
    os.umask(0o077)
    temporary.write_text(json.dumps(build(), ensure_ascii=False, indent=2))
    temporary.replace(target)
