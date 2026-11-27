"""Closed SMTP outbox for completed Kaspersky reviews."""
from base64 import b64encode
from email.message import EmailMessage
from email.utils import formatdate
from html import escape
from ipaddress import ip_address
import json
import logging
from pathlib import Path
import smtplib
import ssl
from threading import Event, Thread
from urllib import parse, request

import funnel
from handoff import finding_url
from workflow import now

RECIPIENT = "pm-test@pm-radar.test"
SENDER = "pm-radar@pm-radar.test"


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS radar_mail (
        run TEXT PRIMARY KEY REFERENCES radar_runs(id),
        status TEXT NOT NULL, payload TEXT NOT NULL, smtp_at TEXT, inbox_at TEXT
    )""")
    db.execute("UPDATE radar_mail SET status='uncertain' WHERE status='sending'")


def load(path, origin):
    config = json.loads(Path(path).read_text())
    app = parse.urlsplit(origin or "")
    box = parse.urlsplit(config["inbox"])
    if (app.scheme != "https" or box.scheme != "https" or app.hostname != box.hostname
            or not ip_address(app.hostname or "").is_private or box.path not in {"", "/"}
            or box.username or box.fragment or box.query or not 1024 <= config["smtp_port"] <= 65535):
        raise ValueError("Для тестовой почты нужен закрытый ящик на LAN.")
    config["origin"] = origin
    return config


def enqueue(db, run_id, case, store, config):
    f = case["filter"]
    change = funnel.delta(store["history"], f["family"], f["before"], f["after"])
    saved = json.loads(db.execute("SELECT payload FROM studies WHERE id=?", (run_id,)).fetchone()[0])
    amount = f"{abs(change['change']):.1f}".replace(".", ",")
    direction = "↓" if change["change"] < 0 else "↑" if change["change"] > 0 else "·"
    payload = {
        "subject": f"Kaspersky {direction} {amount}% · разбор готов",
        "signal": f"Средний недельный индекс самостоятельных заказов Kaspersky {direction} {amount}%.",
        "period": " и ".join(funnel.WINDOWS[f[key]]["label"] for key in ("before", "after")),
        "action": saved["action"],
        "url": finding_url(config["origin"], case["finding"], f, run_id),
    }
    db.execute("INSERT OR IGNORE INTO radar_mail(run,status,payload) VALUES (?,'queued',?)",
               (run_id, json.dumps(payload, ensure_ascii=False)))


def status(db, run_id):
    row = db.execute("SELECT status,smtp_at,inbox_at FROM radar_mail WHERE run=?", (run_id,)).fetchone()
    return (dict(row) | {"recipient":RECIPIENT}) if row else None


def mail_id(run_id):
    return f"{run_id}@pm-radar.test"


def send(row, smtp_port):
    fields = json.loads(row["payload"])
    msg = EmailMessage()
    msg["From"], msg["To"] = SENDER, RECIPIENT
    msg["Subject"], msg["Message-ID"] = fields["subject"], f"<{mail_id(row['run'])}>"
    msg["Date"] = formatdate(usegmt=True)
    lines = (fields["signal"], f"Периоды: {fields['period']}.",
             f"Нужно решение PM. Предложение Qwen: {fields['action'].lower()}.")
    msg.set_content("\n".join((*lines, "", "Открыть находку: " + fields["url"])))
    html = "".join(f"<p>{escape(line)}</p>" for line in lines)
    msg.add_alternative(html + f'<p><a href="{escape(fields["url"], quote=True)}">Открыть находку</a></p>',
                        subtype="html")
    smtp = smtplib.SMTP("127.0.0.1", smtp_port, timeout=6)
    try:
        smtp.send_message(msg, from_addr=SENDER, to_addrs=[RECIPIENT])
    finally:
        smtp.close()


def inbox_has(config, run_id):
    key = mail_id(run_id)
    query = parse.urlencode({"query":"message-id:" + key,"limit":2})
    url = config["inbox"].rstrip("/") + "/api/v1/search?" + query
    auth = b64encode(f'{config["user"]}:{config["password"]}'.encode()).decode()
    context = ssl.create_default_context(cafile=config["certificate"])
    opener = request.build_opener(request.ProxyHandler({}), request.HTTPSHandler(context=context))
    with opener.open(request.Request(url,headers={"Authorization":"Basic " + auth}),timeout=4) as reply:
        messages = json.load(reply).get("messages") or []
    return any(message.get("MessageID", "").strip("<>") == key
               and any(t.get("Address") == RECIPIENT for t in message.get("To", [])) for message in messages)


def worker(connect, config):
    wake = Event()

    def work_queue():
        while True:
            wake.wait(2)
            wake.clear()
            with connect() as db:
                row = db.execute("""UPDATE radar_mail SET status='sending' WHERE run=(
                        SELECT run FROM radar_mail WHERE status='queued' ORDER BY rowid LIMIT 1)
                        RETURNING run,payload""").fetchone()
            if row:
                try:
                    send(row, config["smtp_port"])
                    result, accepted = "accepted", now()
                except (smtplib.SMTPResponseException, smtplib.SMTPRecipientsRefused, ConnectionRefusedError):
                    result, accepted = "failed", None
                except OSError:
                    # A disconnected SMTP client may have missed a successful final response.
                    result, accepted = "uncertain", None
                with connect() as db:
                    db.execute("UPDATE radar_mail SET status=?,smtp_at=? WHERE run=?", (result, accepted, row["run"]))
            with connect() as db:
                unchecked = db.execute("""SELECT run FROM radar_mail WHERE inbox_at IS NULL
                        AND status IN ('accepted','uncertain') ORDER BY rowid DESC LIMIT 10""").fetchall()
            for item in unchecked:
                run_id = item["run"]
                try:
                    if inbox_has(config, run_id):
                        with connect() as db:
                            db.execute("UPDATE radar_mail SET inbox_at=? WHERE run=?", (now(),run_id))
                except (OSError, KeyError, ValueError):
                    logging.debug("PM Radar inbox verification pending for %s",run_id)
                    break

    Thread(target=work_queue, daemon=True, name="pm-radar-mail").start()
    return wake
