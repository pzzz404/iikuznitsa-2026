import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACT_FIELDS = ("id", "type", "title", "text", "source")
TASK_FIELDS = ("task_id", "title", "status")


def read_rows(sheet, fields):
    rows = iter(sheet.values)
    headings = next(rows, ())
    if headings != fields:
        raise ValueError(f"В листе {sheet.title} ожидаются столбцы {', '.join(fields)}")
    return [dict(zip(fields, row, strict=True)) for row in rows if any(value is not None for value in row)]


def facts_and_tasks():
    workbook = os.getenv("PM_EVIDENCE_WORKBOOK")
    if workbook:
        from openpyxl import load_workbook

        book = load_workbook(workbook, read_only=True, data_only=True)
        try:
            facts = read_rows(book["Evidence"], FACT_FIELDS)
            tasks = read_rows(book["Backlog"], TASK_FIELDS)
        finally:
            book.close()
    else:
        fixture = json.loads((ROOT / "demo/evidence.json").read_text(encoding="utf-8"))
        facts, tasks = fixture["facts"], fixture["tasks"]
    missing = {item for topic in TOPICS.values() for item in topic["allowed"]} - {fact["id"] for fact in facts}
    if missing:
        raise ValueError("Не хватает свидетельств: " + ", ".join(sorted(missing)))
    return [dict(fact, image="") for fact in facts], tasks


TOPICS = {
    "invoice": {"title":"Самостоятельная покупка по счёту","question":"Как вырастить оплаченные заказы по счёту без менеджера?", "allowed":["F1","F2","F3","F11"],"short":"Путь до счёта существует. Сколько счетов оплачивают?","action":"Измерить путь от выбора счёта до оплаты","criterion":"Для подходящих B2B-заказов связать выбор счёта, выставление и оплату. Отдельно посчитать обращения к менеджеру и долю заказов без связи с оплатой.","measure":"Доля подходящих организаций с оплаченным заказом","limit":"Нужны фактические оплаты и единица наблюдения. Оценка прироста пока недоступна."},
    "repeat": {"title":"Повторные закупки","question":"Где покупателю удобнее повторить закупку?","allowed":["F4","F5","F6"],"short":"Клиент упомянул письмо, а конкуренты предлагают историю заказов.","action":"Проверить повтор из письма и из истории заказов","criterion":"Проверить два сценария у покупателей с потребностью в продлении. Записать успешные попытки и причины отказа по каждому пути.","measure":"Доля подходящих клиентов, завершивших повторную закупку","limit":"Один ответ клиента не определяет размер сегмента. Для бессрочных лицензий потребность может отсутствовать."},
    "cross": {"title":"Допродажа в корзине","question":"Как проверить, увеличивают ли рекомендации в корзине допродажи?","allowed":["F9","F10","F11"],"short":"Два предложения в корзине; их вклад в оплаченные заказы неизвестен.","action":"Связать показ рекомендации с оплатой сопутствующего товара","criterion":"Для одной товарной связки раздельно посчитать показы в корзине, добавления, оплаченные комплекты и завершение основной покупки.","measure":"Оплаченные комплекты на подходящую корзину","limit":"Показатели личного кабинета нельзя присваивать корзине магазина."},
    "kes": {"title":"Снижение заказов семейства A","question":"Что проверить после падения самостоятельных заказов семейства A?","allowed":["F7","F8","F11"],"short":"Снижение индекса заказов совпало с изменениями конфигуратора и входа.","action":"Проверить путь от выбора лицензии семейства A до корзины","criterion":"На компьютере и телефоне для трёх семейств сверить выбранную лицензию, содержимое корзины и передачу события. Связать результат с Д-03.","measure":"Индекс самостоятельных заказов семейства A","limit":"Неполная последняя неделя исключена. Совпадение по времени не устанавливает причину."}
}
