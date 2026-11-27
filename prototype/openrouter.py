import json
import os
import stat
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import sleep
from urllib import error, parse, request

MODEL = "qwen/qwen3-32b"
BASE = "https://openrouter.ai/api/v1"
ENABLED = os.getenv("PM_OPENROUTER") == "1"
KEY_FILE = Path(os.getenv("PM_OPENROUTER_KEY_FILE", Path.home()/".config/pm-hackathon/openrouter.key"))


def key():
    value = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not value:
        try:
            info = KEY_FILE.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError
            value = KEY_FILE.read_text().strip()
        except (OSError, ValueError):
            raise RuntimeError("Настройте ключ OpenRouter на Beelink в файле с правами 600.") from None
    if not value or any(c.isspace() for c in value):
        raise RuntimeError("Проверьте формат ключа OpenRouter.")
    return value


def headers(api_key):
    return {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}


class ResponseError(RuntimeError):
    def __init__(self, message, reply):
        super().__init__(message)
        self.reply = reply if isinstance(reply, dict) else {}


def complete(body, api_key):
    body.update(model=MODEL, max_tokens=max(224, body["max_tokens"]), reasoning={"enabled": False},
                usage={"include": True}, provider={"require_parameters": True, "data_collection": "deny"})
    body["messages"][0]["content"] += "\n/no_think"
    body["response_format"]["json_schema"]["strict"] = True
    req = request.Request(BASE + "/chat/completions",
                          data=json.dumps(body, ensure_ascii=False).encode(), headers=headers(api_key))
    try:
        with request.urlopen(req, timeout=75) as reply:
            result = json.load(reply, parse_float=Decimal)
            if isinstance(result, dict) and result.get("error"):
                raise ResponseError("OpenRouter вернул ошибку генерации.", result)
            return result
    except error.HTTPError as exc:
        messages = {401: "Ключ OpenRouter не принят.", 402: "Недостаточно средств OpenRouter.",
                    403: "OpenRouter отклонил доступ.", 429: "OpenRouter ограничил частоту запросов."}
        try:
            payload = json.load(exc, parse_float=Decimal)
        except (ValueError, OSError):
            payload = {}
        finally:
            exc.close()
        raise ResponseError(messages.get(exc.code, f"OpenRouter вернул HTTP {exc.code}."), payload) from None


def amount(value):
    try:
        result = Decimal(str(value))
        return format(result, "f") if result.is_finite() and result >= 0 else None
    except InvalidOperation:
        return None


def receipt(reply, api_key):
    usage = dict(reply.get("usage") or {})
    paid = amount(usage.get("cost"))
    generation = reply.get("id")
    route = reply.get("provider")
    method = "usage.cost" if paid is not None else None
    if generation and (paid is None or usage.get("prompt_tokens") is None or usage.get("completion_tokens") is None):
        url = BASE + "/generation?" + parse.urlencode({"id": generation})
        for delay in (0, 0.5, 1.5):
            sleep(delay)
            try:
                with request.urlopen(request.Request(url, headers=headers(api_key)), timeout=5) as response:
                    details = json.load(response, parse_float=Decimal)["data"]
                if paid is None:
                    paid = amount(details.get("total_cost"))
                    method = "generation.total_cost" if paid is not None else None
                for field, name in (("prompt_tokens", "tokens_prompt"), ("completion_tokens", "tokens_completion")):
                    if usage.get(field) is None:
                        usage[field] = details.get(name)
                route = route or details.get("provider_name")
                if paid is not None and usage.get("prompt_tokens") is not None and usage.get("completion_tokens") is not None:
                    break
            except (OSError, ValueError, KeyError):
                continue
    return usage, {"platform": "OpenRouter", "generation": generation, "actual_cost": paid,
                   "currency": "USD", "receipt": method, "upstream": route}
