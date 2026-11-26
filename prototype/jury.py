"""Prepare the isolated demo dataset and issue or revoke invitations."""

import argparse
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from evidence import facts_and_tasks


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
    os.environ.pop("PM_EVIDENCE_WORKBOOK", None)
    facts, tasks = facts_and_tasks()
    write_private(out, json.dumps({"facts": facts, "tasks": tasks}, ensure_ascii=False, indent=2))


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
