"""Раздел «Актуальные цены» (chestny-avto.ru/ceny/) из канала MAX. Запускается GitHub Actions по расписанию.

Читает последние посты канала через API ботов MAX (бот — администратор канала), берёт посты с ценой,
сохраняет первое фото и данные в ceny/prices.json и рисует статическую страницу ceny/index.html.
Машина живёт в разделе 40 дней с даты поста (решение владельца 2026-11-09).

Окружение:
    MAX_TOKEN    — токен бота (секрет репозитория, в коде его нет)
    MAX_CHAT_ID  — id канала (необязательно: если нет, ищем по событию bot_added и пишем в ceny/chat_id.txt)
    SITE_DIR     — корень живого сайта (по умолчанию текущая папка)

Проверка без сети:  python max_prices.py --sample sample.json   (сообщения в формате API)
"""
import argparse
import html
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://platform-api2.max.ru"
HERE = Path(__file__).resolve().parent
KEEP_DAYS = 40
MSK = timezone(timedelta(hours=3))
WA = "https://wa.me/79198731668?text="
e = html.escape


# ---------- разбор поста ----------

def field(text, *names):
    for n in names:
        m = re.search(rf"(?im)^[^\w\n]*{n}[^\S\n]*[:\-–][^\S\n]*(.+)$", text)
        if m:
            return m[1].strip(" *_")
    return ""


def money(n):
    return f"{n:,}".replace(",", " ") + " ₽"


def parse(text):
    """Пост → данные машины или None, если это не пост с ценой."""
    t = text.replace("\xa0", " ")
    price_raw = field(t, "Цена под ключ", "Цена")
    m = re.search(r"(\d{1,3}(?:[ .]\d{3}){2}|\d{6,8})", price_raw) if price_raw else None
    if not m:  # цена без подписи: «2 450 000 ₽»
        m = re.search(r"(\d{1,3}(?:[ .]\d{3}){2})\s*(?:₽|руб)", t)
    if not m:
        return None
    price = int(re.sub(r"\D", "", m[1]))
    if not 300_000 <= price <= 50_000_000:
        return None
    lines = [l.strip(" *_") for l in t.splitlines() if l.strip(" *_")]
    brand, model = field(t, "Марка"), field(t, "Модель")
    if brand or model:
        title = f"{brand} {model}".strip()
    else:  # первая строка с латиницей: «🔥 Mercedes-Benz A-Class 2023»
        head = next((l for l in lines[:6] if re.search(r"[A-Za-z]{2,}", l)), lines[0] if lines else "")
        title = re.sub(r"^[^\w]+", "", head)
        title = re.sub(r"\s*\b(19|20)\d{2}\b.*$", "", title).strip() or title
    year = field(t, "Год выпуска", "Год")
    ym = re.search(r"\b(19|20)\d{2}\b", year or " ".join(lines[:3]))
    km_raw = field(t, "Пробег")
    km = int(re.sub(r"\D", "", km_raw) or 0) if km_raw and not re.search(r"нов|без пробега", km_raw, re.I) else 0
    new = bool(re.search(r"нов(ый|ая)|без пробега", km_raw or t[:300], re.I)) and not km
    gear = field(t, "Коробка передач", "Коробка", "КПП")
    drive = field(t, "Привод")
    engine = field(t, "Двигатель")
    country = "Корея" if re.search(r"🇰🇷|Коре[яи]", t) else "Киргизия" if re.search(r"Киргиз|🇰🇬", t) else "Китай"
    chips = [x for x in [ym[0] if ym else "", "новая" if new else (f"{km:,} км".replace(",", " ") if km else ""),
                         engine_short(engine or t), gear_short(gear), short(drive)] if x]
    return dict(title=title[:60], year=int(ym[0]) if ym else 0, price=price, chips=chips[:5], country=country)


def engine_short(s):
    """«1.3T M282, L4, бензин, 136 л.с.» → «1.3T · 136 л.с.», электро и гибрид подписываем словом."""
    vol = re.search(r"\b(\d\.\d)\s*(T|Т|TSI|TFSI|турбо)?", s)
    hp = re.search(r"(\d{2,4})\s*л\.?\s*с", s)
    kind = "электро" if re.search(r"электро", s, re.I) and not vol else "гибрид" if re.search(r"гибрид|PHEV|HEV|EREV", s, re.I) else ""
    parts = [kind, (vol[1] + ("T" if vol[2] else "")) if vol else "", f"{hp[1]} л.с." if hp else ""]
    return " · ".join(p for p in parts if p)


def gear_short(s):
    r = (s or "").lower()
    return "" if not r else "вариатор" if re.search(r"вариатор|cvt", r) else "механика" if re.search(r"механ|мкпп", r) else "автомат"


def short(s):
    s = re.sub(r"\(.*?\)", "", s or "").strip(" ,.")
    return s[:28]


# ---------- API MAX ----------

def api(path, **params):
    import requests
    r = requests.get(API + path, params=params, timeout=40, verify=str(HERE / "ru-ca.pem"),
                     headers={"Authorization": os.environ["MAX_TOKEN"]})
    r.raise_for_status()
    return r.json()


def find_chat_id(site):
    saved = site / "ceny" / "chat_id.txt"
    cid = os.environ.get("MAX_CHAT_ID") or (saved.read_text().strip() if saved.exists() else "")
    if cid:
        return cid
    ups = api("/updates", types="bot_added", timeout=0, limit=100).get("updates", [])
    ids = {str(u.get("chat_id")) for u in ups if u.get("chat_id")}
    if len(ids) != 1:
        sys.exit(f"Не знаю id канала: событий bot_added {len(ids)}. Удалите бота из админов канала и добавьте снова, затем перезапустите.")
    cid = ids.pop()
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(cid)
    print("Нашла id канала:", cid)
    return cid


def first_image(msg):
    for a in (msg.get("body") or {}).get("attachments") or []:
        if a.get("type") == "image" and (a.get("payload") or {}).get("url"):
            return a["payload"]["url"]
    return ""


def save_photo(url, path):
    import requests
    from PIL import Image, ImageOps
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert("RGB")
    im.thumbnail((900, 1200))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=82, optimize=True, progressive=True)


# ---------- страница ----------

def page(cars):
    cards = []
    for c in cars:
        date = datetime.fromtimestamp(c["ts"] / 1000, MSK).strftime("%d.%m.%Y")
        wa = WA + quote(f"Здравствуйте! Интересует {c['title']} за {money(c['price'])} под ключ — увидел на сайте в разделе цен.")
        chips = "".join(f"<span>{e(x)}</span>" for x in c["chips"])
        cards.append(f"""<article class="car"><div class="ph"><img src="img/{c['id']}.jpg" alt="{e(c['title'])}" loading="lazy"><b class="from">Из {e({'Китай': 'Китая', 'Корея': 'Кореи', 'Киргизия': 'Киргизии'}[c['country']])}</b></div>
<div class="bd"><h2>{e(c['title'])}</h2><div class="chips">{chips}</div><small>Под ключ в Ростове</small><div class="pr">{money(c['price'])}</div>
<p class="dt">Цена на {date}. Точную сумму на сегодня пришлём.</p><a class="btn" href="{wa}" target="_blank" rel="noopener">Хочу такую →</a></div></article>""")
    body = "\n".join(cards) or '<p class="empty">Сейчас обновляем подборку. Напишите нам — пришлём свежие варианты с ценой.</p>'
    tpl = (HERE / "template.html").read_text(encoding="utf-8")
    return tpl.replace("{{CARDS}}", body).replace("{{COUNT}}", str(len(cars)))


def quote(s):
    from urllib.parse import quote as q
    return q(s)


# ---------- основной ход ----------

def run(site, messages, fetch_photos=True):
    data_path = site / "ceny" / "prices.json"
    data = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else {"cars": []}
    known = {c["id"]: c for c in data["cars"]}
    now_ms = time.time() * 1000
    for msg in messages:
        body = msg.get("body") or {}
        mid = str(body.get("mid") or msg.get("mid") or "")
        ts = msg.get("timestamp") or 0
        if not mid or mid in known or now_ms - ts > KEEP_DAYS * 864e5:
            continue
        car = parse(body.get("text") or "")
        url = first_image(msg)
        if not car or not url:
            continue
        safe = re.sub(r"[^A-Za-z0-9_-]", "", mid)[-40:]
        if fetch_photos:
            try:
                save_photo(url, site / "ceny" / "img" / f"{safe}.jpg")
            except Exception as ex:  # фото не скачалось — попробуем в следующий раз
                print("фото не скачалось:", mid, ex)
                continue
        known[mid] = dict(car, id=safe, mid=mid, ts=ts)
        print("новая машина:", car["title"], money(car["price"]))
    fresh = sorted((c for c in known.values() if now_ms - c["ts"] <= KEEP_DAYS * 864e5), key=lambda c: -c["ts"])
    for c in known.values():
        if c not in fresh:
            (site / "ceny" / "img" / f"{c['id']}.jpg").unlink(missing_ok=True)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps({"updated": int(now_ms), "cars": fresh}, ensure_ascii=False, indent=1), encoding="utf-8")
    (site / "ceny" / "index.html").write_text(page(fresh), encoding="utf-8")
    print("в разделе:", len(fresh))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample")
    a = ap.parse_args()
    site = Path(os.environ.get("SITE_DIR", "."))
    if a.sample:
        msgs = json.loads(Path(a.sample).read_text(encoding="utf-8"))
        run(site, msgs, fetch_photos=False)
        return
    if not os.environ.get("MAX_TOKEN"):
        print("Токен бота ещё не добавлен в секреты репозитория (MAX_TOKEN) — жду, ничего не меняю.")
        return
    cid = find_chat_id(site)
    msgs = api("/messages", chat_id=cid, count=100).get("messages", [])
    run(site, msgs)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
