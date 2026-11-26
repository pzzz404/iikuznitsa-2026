"""Prepare the isolated demo dataset and issue or revoke invitations on Beelink."""

import argparse
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from evidence import facts_and_tasks
from funnel import jury_aggregates, load_history

PARAPHRASES = {
    "F3": "В одном интервью покупатель запросил онлайн-сверку, историю покупок и возможность распечатать счёт.",
    "F4": "Один покупатель предложил повторять закупку из письма с подтверждением заказа.",
    "F6": "В одном интервью покупатель объяснил, что бессрочная лицензия пока не требует повторной закупки.",
}
ALLOWED = set("F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F11".split())


def read_json(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def write_private(path, value):
    path.parent.mkdir(exist_ok=True, parents=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".new")
    tmp.touch(mode=0o600, exist_ok=False)
    try:
        tmp.write_text(value)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def fixtures(out):
    source, _ = facts_and_tasks()
    demo = []
    for fact in source:
        if fact["id"] in ALLOWED:
            item = {key: fact[key] for key in ("id", "type", "title", "text", "source")}
            item["text"] = PARAPHRASES.get(item["id"], item["text"])
            item["image"] = ""
            demo.append(item)
    tasks = [
        {"task_id": "Д-01", "title": "Проверить полноту событий электронной торговли", "status": "К проверке"},
        {"task_id": "Д-02", "title": "Сверить пути самостоятельной оплаты", "status": "В очереди"},
    ]
    write_private(out, json.dumps({"facts": demo, "tasks": tasks}, ensure_ascii=False, indent=2))


def synthetic(out):
    material = [
        ("F1", "Наблюдение", "Выбор способа покупки",
         "В вымышленном B2B-магазине запросить счёт можно из карточки или через менеджера."),
        ("F2", "Контрольное прохождение", "Самостоятельный счёт",
         "В демонстрационном прохождении покупатель сам создал счёт, но подтверждение оплаты не проверялось."),
        ("F3", "Интервью", "Проверка статуса",
         "В вымышленном интервью покупатель просит видеть статус счёта после выставления."),
        ("F11", "Пробел", "Привязка к оплате",
         "В синтетической таблице события выставления есть, а связки идентификатора счёта с оплатой нет."),
    ]
    facts = [dict(id=id, type=kind, title=title, text=text, source="Синтетический набор · " + id, image="")
             for id, kind, title, text in material]
    write_private(out, json.dumps({"mode":"synthetic-openrouter", "facts":facts, "tasks":[]}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample")
    sample.add_argument("output", type=Path)
    fake = sub.add_parser("synthetic")
    fake.add_argument("output", type=Path)
    radar = sub.add_parser("funnel")
    radar.add_argument("output", type=Path)
    issue = sub.add_parser("issue")
    issue.add_argument("registry", type=Path)
    issue.add_argument("origin")
    issue.add_argument("expires")
    issue.add_argument("output", type=Path)
    revoke = sub.add_parser("revoke")
    revoke.add_argument("registry", type=Path)
    revoke.add_argument("invitation", type=Path)
    args = parser.parse_args()
    if args.command == "sample":
        fixtures(args.output)
        return
    if args.command == "synthetic":
        synthetic(args.output)
        return
    if args.command == "funnel":
        data = jury_aggregates(load_history())
        tasks = [{"task_id": data["task"]["id"], "title": data["task"]["title"], "status": data["task"]["status"]}]
        write_private(args.output, json.dumps({"mode": "jury-funnel", "facts": [], "tasks": tasks, "funnel": data},
                                             ensure_ascii=False, indent=2))
        return
    registry = read_json(args.registry)
    if args.command == "issue":
        expires = datetime.fromisoformat(args.expires)
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            parser.error("Укажите будущий срок с часовым поясом")
        token = secrets.token_urlsafe(36)
        registry[hashlib.sha256(token.encode()).hexdigest()] = expires.isoformat()
        write_private(args.registry, json.dumps(registry))
        write_private(args.output, args.origin.rstrip("/") + "/#invite=" + token + "\n")
    else:
        token = args.invitation.read_text().strip().split("#invite=", 1)[1]
        registry.pop(hashlib.sha256(token.encode()).hexdigest(), None)
        write_private(args.registry, json.dumps(registry))


if __name__ == "__main__":
    main()
