"""Fill an organizer workbook copy from the recorded per-call measurements."""

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill


def add_journal(book, local, external):
    sheet = book.create_sheet("Журнал замера")
    sheet.append(["Контур", "Сценарий", "Задача", "Вызов", "Модель", "Вход", "Выход", "В кэше",
                  "мс", "Фактически списано", "Валюта", "Подтверждение", "Статус", "ID генерации"])
    columns = "ABCDEFGHIJKLMN"
    sizes = (22, 23, 12, 10, 25, 11, 11, 11, 12, 20, 10, 27, 17, 39)
    for column, width in zip(columns, sizes, strict=True):
        sheet.column_dimensions[column].width = width
        cell = sheet[column+"1"]
        cell.fill = PatternFill("solid", fgColor="143F34")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(wrap_text=True)
    sheet.freeze_panes = "A2"
    for environment, logs in (("Локальный ваншот", local), ("OpenRouter", external)):
        if not logs:
            continue
        task = logs["task"]
        for call in reversed(logs["journal"]["calls"]):
            cost = call.get("actual_cost") if environment == "OpenRouter" else "0"
            sheet.append([environment, call["scenario"], f"PM-{task['id']:03d}" if call["study"] == task["study"] else None,
                          call["id"], call["model"], call["prompt_tokens"], call["completion_tokens"], call["cached_tokens"],
                          call["elapsed_ms"], float(cost) if cost is not None else None,
                          "USD" if environment == "OpenRouter" else "RUB",
                          call.get("receipt") if environment == "OpenRouter" else "usage llama.cpp; тариф 0",
                          call["status"], call.get("generation")])
            sheet["J"+str(sheet.max_row)].number_format = "0.000000000"
    sheet.auto_filter.ref = sheet.dimensions


def write_cached(workbook, output, cells):
    with TemporaryDirectory(dir=output.parent) as directory:
        path = Path(directory) / output.name
        workbook.save(path)
        if not cells:
            path.replace(output)
            return
        result = Path(directory) / "cached.xlsx"
        with ZipFile(path) as source, ZipFile(result, "w") as target:
            for item in source.infolist():
                raw = source.read(item)
                if item.filename == "xl/worksheets/sheet1.xml":
                    for key, val in cells.items():
                        pattern = rb'(<c\b[^>]*\br="' + key.encode() + rb'"[^>]*><f>[^<]+</f>)<v\s*/>'
                        raw, changes = re.subn(pattern, lambda m: m[1]+b"<v>"+str(val).encode()+b"</v>", raw)
                        if changes != 1:
                            raise ValueError("Не удалось сохранить результат " + key)
                target.writestr(item, raw)
        result.replace(output)


def fill(original, output, local, external, rate):
    book = load_workbook(original)
    sheet = book["Расчёт"]
    sheet["A14"] = "Фактическая сумма за задачу · валюта списания"
    sheet["A15"] = "OpenRouter · синтетический прогон"
    source = external or local
    calls = source["task"]["calls"]
    if not calls or any(row["prompt_tokens"] is None or row["completion_tokens"] is None for row in calls):
        raise ValueError("Не хватает замеров токенов по задаче")
    prompt = sum(row["prompt_tokens"] for row in calls)
    completion = sum(row["completion_tokens"] for row in calls)
    total_calls = len(calls)
    row = ["Разбор → задача", calls[0]["model"], total_calls, prompt/total_calls, completion/total_calls]
    for cell, value in zip(sheet["A9:E9"][0], row, strict=True):
        cell.value = value
    sheet["A17"] = "Вход и выход по фактическому usage. В журнале одна строка на каждый вызов."
    sheet["A18"] = "Локально: Beelink, CPU, llama.cpp. Мощность, тариф и амортизация не замерены."
    sheet["A19"] = "Токены разработки Codex вне расчёта. Второй вопрос в ролике не создаёт задачу."
    caches = {}
    if external:
        if any(c.get("actual_cost") is None or not c.get("receipt") or c.get("currency") != "USD" for c in calls):
            raise ValueError("Полная стоимость всех вызовов OpenRouter не подтверждена")
        amount = sum(Decimal(c["actual_cost"]) for c in calls)
        sheet["H9"] = "$"
        sheet["I14"] = float(amount)
        sheet["I14"].number_format = '0.000000000" USD"'
        sheet["I15"] = "Подтверждён"
        sheet["I9"] = '=IF($I$3="","",$I$14*$I$3)'
        sheet["I13"] = '=IF($I$3="","",SUM(I9:I12))'
        if rate is not None:
            sheet["I3"] = float(rate)
            caches = {"I9": amount*rate, "I13": amount*rate}
        sheet["A17"] = "Списание USD из OpenRouter usage.cost / generation.total_cost. Тарифы не подставляются."
    else:
        sheet["F9"], sheet["G9"], sheet["H9"] = 0, 0, "₽"
        sheet["I14"] = 0
        sheet["I14"].number_format = '0" ₽"'
        sheet["I15"] = "Ожидает ключа и замера"
        caches = {"I9": 0, "I13": 0}
    sheet["A14"].font = Font(bold=True, color="143F34")
    add_journal(book, local, external)
    write_cached(book, output, caches)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("local", type=Path)
    parser.add_argument("--openrouter", type=Path)
    parser.add_argument("--usd-rub", type=Decimal)
    args = parser.parse_args()
    if args.template.resolve() == args.output.resolve():
        parser.error("Сохраните результат в копию шаблона")
    local = json.loads(args.local.read_text())
    external = json.loads(args.openrouter.read_text()) if args.openrouter else None
    fill(args.template, args.output, local, external, args.usd_rub)


if __name__ == "__main__":
    main()
