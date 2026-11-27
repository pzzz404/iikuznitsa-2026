"""Links and export of an approved local PM task."""
import csv
import io
from urllib.parse import quote


def finding_url(origin, finding, filters, run_id):
    if finding in {"kes", "astra"}:
        ref = ".".join(filters[key] for key in ("family", "before", "after", "device", "audience"))
        route = ("deviation/" if finding == "kes" else "astra/below90.") + ref
    elif finding == "office":
        route = "catalog/office"
    elif finding == "repeat-mail":
        route = "growth/repeat-mail"
    else:
        raise ValueError("У задачи нет адреса находки.")
    return origin.rstrip("/") + "/#" + quote(route + "~" + run_id, safe="/.~")


def redmine_csv(task, tag, origin):
    run = task["radar"]
    url = finding_url(origin, run["finding"], run["filter"], run["id"])
    description = "\n".join(line for line in (
        f"PM Radar · PM-{task['id']:03d}",
        f"Тег: {tag}",
        f"Ссылка на находку: {url}",
        f"Критерий проверки: {task['criterion']}",
        f"Условие повторной проверки: {run['followup']}" if run.get("followup") else "",
        f"Исходная задача: {run['linked']}" if run.get("linked") else "",
        f"Владелец: {run['owner']}" if run.get("owner") else "",
        f"Дата возврата: {run['due']}" if run.get("due") else "",
        f"Решение PM: {run['note']}" if run.get("note") else "",
    ) if line)
    row = (task["title"], description, tag, url, task["criterion"], run.get("linked"),
           run.get("owner"), run.get("due"))
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
    writer.writerow(("Тема", "Описание", "Тег", "Ссылка на находку", "Критерий проверки",
                     "Исходная задача", "Владелец", "Дата возврата"))
    # Quoting preserves commas and line breaks; protect spreadsheet interpretation of user fields.
    writer.writerow("'" + value if value and value.lstrip().startswith(("=", "+", "-", "@")) else value
                    for value in row)
    return buffer.getvalue().encode("utf-8-sig")
