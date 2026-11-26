"""Сверка синтетического набора demo_crm_v1. Запуск: python3 demo/crm/reconcile.py"""

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path


def records(table):
    return [dict(zip(table["columns"], row, strict=True)) for row in table["rows"]]


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def cohort_balances(data):
    balances = []
    orders = records(data["crm"])
    by_invoice = defaultdict(list)
    for tx in records(data["billing"]):
        by_invoice[tx["invoice_id"]].append(tx)
    window = timedelta(days=data["payment_window_days"])
    as_of = timestamp(data["data_as_of"])
    for cohort in data["cohorts_by_order_creation"]:
        start = date.fromisoformat(cohort["from"])
        end = date.fromisoformat(cohort["until_exclusive"])
        paid = Counter()
        net_rub = 0
        pending = 0
        for order in orders:
            created = timestamp(order["created_at"])
            if not start <= created.date() < end:
                continue
            if created + window > as_of:
                pending += 1
                continue
            received = 0
            for tx in by_invoice[order["invoice_id"]]:
                if created <= timestamp(tx["occurred_at"]) < created + window:
                    sign = {"payment": 1, "refund": -1}[tx["kind"]]
                    received += sign * tx["amount_rub"]
            net_rub += received
            if received >= order["invoice_rub"]:
                paid[order["closing_channel"]] += 1
        balances.append({"cohort": cohort["id"], "store": paid["store"], "manager": paid["manager"],
                         "total": paid.total(), "net_rub": net_rub, "pending": pending})
    return balances


def main():
    data = json.loads(Path(__file__).with_name("synthetic_sales.json").read_text())
    print(data["provenance"])
    for b in cohort_balances(data):
        print(f"Когорта {b['cohort']}: магазин {b['store']}, менеджер {b['manager']}, "
              f"всего {b['total']}, поступления минус возвраты {b['net_rub']} ₽, "
              f"ожидают полного окна {b['pending']}.")
    server_adds = {row["operation_id"] for row in records(data["store_backend"])
                   if row["operation"] == "cart_item_added"}
    tracked = Counter(row["operation_id"] for row in records(data["analytics_events"])
                      if row["event"] == "add_to_cart")
    print(f"Корзина: {len(server_adds)} серверных добавлений, {tracked.total()} аналитических событий, "
          f"совпали {len(server_adds.intersection(tracked))} операций.")
    print("Без события:", sorted(server_adds.difference(tracked)))
    print("С повторной отправкой:", sorted(key for key, count in tracked.items() if count > 1))
    print("Без серверной операции:", sorted(tracked.keys() - server_adds))


if __name__ == "__main__":
    main()
