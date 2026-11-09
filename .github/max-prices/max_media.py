"""Видео и фото с выдач из канала MAX → сайт chestny-avto.ru. Запускается GitHub Actions.

Режимы:
    python max_media.py probe   — только посмотреть, какие посты с видео и фото есть (ничего не меняет)
    python max_media.py run     — скачать новые видео и фото выдач в media/ и обновить media/media.json

Окружение как у max_prices.py: MAX_TOKEN, CA_BUNDLE, SITE_DIR; id канала берётся из ceny/chat_id.txt.
"""
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from max_prices import api, parse  # noqa: E402

DAYS = 120  # первичный разбор: 4 месяца (решение владельца 09.11.2026)


def history(cid, days):
    msgs, frm, cutoff = [], None, time.time() * 1000 - days * 864e5
    for _ in range(60):
        params = {"chat_id": cid, "count": 100}
        if frm:
            params["from"] = frm
        batch = api("/messages", **params).get("messages", [])
        seen = {(m.get("body") or {}).get("mid") for m in msgs}
        new = [m for m in batch if (m.get("body") or {}).get("mid") not in seen]
        if not new:
            break
        msgs += new
        oldest = min(m.get("timestamp") or 0 for m in new)
        if oldest < cutoff:
            break
        frm = oldest - 1
    return [m for m in msgs if (m.get("timestamp") or 0) >= cutoff]


def kinds(msg):
    return [a.get("type") for a in (msg.get("body") or {}).get("attachments") or []]


def probe(site):
    cid = (site / "ceny" / "chat_id.txt").read_text().strip()
    msgs = history(cid, DAYS)
    print("постов за", DAYS, "дней:", len(msgs))
    c = Counter()
    for m in msgs:
        k = kinds(m)
        text = (m.get("body") or {}).get("text") or ""
        price = bool(parse(text))
        tag = ("цена" if price else "без цены") + " | " + ",".join(sorted(set(k)) or ["текст"])
        c[tag] += 1
    for k, v in c.most_common():
        print(f"{v:4}  {k}")
    # как выглядит вложение-видео (без ссылок и токенов)
    for m in msgs:
        for a in (m.get("body") or {}).get("attachments") or []:
            if a.get("type") == "video":
                p = a.get("payload") or {}
                print("ключи payload видео:", sorted(p.keys()), "| ключи вложения:", sorted(a.keys()))
                vt = p.get("token")
                if vt:
                    try:
                        v = api(f"/videos/{vt}")
                        print("ключи /videos:", sorted(v.keys()), "| urls:", sorted((v.get("urls") or {}).keys()))
                    except Exception as ex:
                        print("/videos ошибка:", str(ex)[:120])
                return


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    site = Path(os.environ.get("SITE_DIR", "."))
    if not os.environ.get("MAX_TOKEN"):
        print("Нет MAX_TOKEN — жду.")
        sys.exit(0)
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if mode == "probe":
        probe(site)
