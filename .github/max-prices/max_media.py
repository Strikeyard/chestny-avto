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
    for m in msgs:  # начало текста постов без цены — чтобы настроить отбор (посты канала публичные)
        text = ((m.get("body") or {}).get("text") or "").replace("\n", " ")
        k = set(kinds(m)) - {"inline_keyboard"}
        if k and not parse(text):
            print("ПОСТ", ",".join(sorted(k)), "|", text[:110])
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


# ---------- отбор постов-выдач ----------

HANDOVER = re.compile(r"(?i)(вот это была выдача|сегодня выдача|очередная[^.!\n]{0,20}выдача|выдали\b|выдали [А-ЯЁA-Z]|поздравля|встречай|получил[аи]? сво|пополнени\w* в семье|снова с нами|по рекомендации|привёз (ему|ей)|отзыв на 5|благодарю за доверие|привезли нового|привозишь машину|клиент становится другом|у нас ?-? ?праздник)")
NOT_HANDOVER = re.compile(r"(?i)не выдача|не на выдаче|к выдаче|на выдачу|забронировали|выкупили для|выкуплена")
MAX_VIDEOS, MAX_PHOTOS = 40, 150  # чтобы сайт не разрастался
VERSION = 2  # при смене правил отбора увеличить: всё из канала пересоберётся заново


_CASCADE = None


def has_people(im):
    """Есть ли в кадре человек (лицо анфас). Нужно, чтобы в «Ключи уже у них» не попадали салоны и машины без клиентов.
    Людей не узнаёт — только находит, что лицо в кадре есть."""
    global _CASCADE
    import cv2
    import numpy as np
    if _CASCADE is None:
        _CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    g = np.array(im.convert("L"))
    scale = 900 / max(g.shape)
    if scale < 1:
        g = cv2.resize(g, None, fx=scale, fy=scale)
    faces = _CASCADE.detectMultiScale(g, scaleFactor=1.1, minNeighbors=6, minSize=(24, 24))
    return len(faces) > 0


def video_frames(path, n=4):
    """Несколько кадров из видео — для проверки, есть ли люди, и для обложки."""
    import subprocess
    from PIL import Image
    out = []
    for k in range(n):
        f = Path("/tmp") / f"frame-{k}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(1 + k * 4), "-i", str(path), "-frames:v", "1", str(f)])
        if f.exists() and f.stat().st_size:
            out.append(Image.open(f).convert("RGB"))
            f.unlink()
    return out


def is_handover(text):
    head = text[:400]
    return bool(HANDOVER.search(head)) and not NOT_HANDOVER.search(head[:160])


def caption(text):
    """«Светлана, поздравляем с приобретением Volkswagen Polo! 🔥» → цитата и подпись."""
    from max_prices import car_name
    first = next((l.strip() for l in text.splitlines() if l.strip()), "")
    first = re.sub(r"[^\w\s,.!?—–«»\"'()+\-:№]", "", first).strip(" -—")
    car = next((n for l in text.splitlines()[:6] if (n := car_name(l))), "")
    return first[:120], car


def ahash(im, n=12):
    g = im.convert("L").resize((n, n))
    px = list(g.getdata())
    m = sum(px) / len(px)
    return [1 if v > m else 0 for v in px]


def near(h, pool, limit=18):
    return any(sum(a != b for a, b in zip(h, p)) <= limit for p in pool)


def fetch_image(url):
    import io
    import requests
    from PIL import Image, ImageOps
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert("RGB")


def site_hashes(site):
    """Отпечатки фото, которые уже стоят на сайте (галерея, отзывы), — чтобы не дублировать."""
    from PIL import Image, ImageOps
    out = []
    for d in ("img", "video"):
        for p in (site / d).glob("*.jpg"):
            try:
                out.append(ahash(ImageOps.exif_transpose(Image.open(p))))
            except Exception:
                pass
    return out


def run(site):
    import subprocess
    import requests
    cid = (site / "ceny" / "chat_id.txt").read_text().strip()
    media = site / "media"
    data_path = media / "media.json"
    data = json.loads(data_path.read_text(encoding="utf-8")) if data_path.exists() else {}
    if data.get("v") != VERSION:  # правила отбора поменялись — пересобираем всё заново
        for sub in ("img", "video"):
            for f in (media / sub).glob("*"):
                f.unlink()
        data = {"v": VERSION, "photos": [], "videos": []}
    done = {x["mid"] for x in data["photos"]} | {x["mid"] for x in data["videos"]}
    pool = site_hashes(site) + [x["hash"] for x in data["photos"] + data["videos"] if x.get("hash")]
    msgs = sorted(history(cid, DAYS), key=lambda m: m.get("timestamp") or 0)  # от старых к новым
    added_p = added_v = 0
    for m in msgs:
        body = m.get("body") or {}
        mid, ts, text = str(body.get("mid") or ""), m.get("timestamp") or 0, body.get("text") or ""
        if not mid or mid in done or parse(text) or not is_handover(text):
            continue
        safe = re.sub(r"[^A-Za-z0-9_-]", "", mid)[-40:]
        quote, car = caption(text)
        for i, a in enumerate(body.get("attachments") or []):
            p = a.get("payload") or {}
            try:
                if a.get("type") == "image" and p.get("url"):
                    im = fetch_image(p["url"])
                    h = ahash(im)
                    if near(h, pool) or not has_people(im):  # салон и машина без людей — не в «Ключи уже у них»
                        continue
                    im.thumbnail((1000, 1400))
                    name = f"{safe}-{i}.jpg"
                    (media / "img").mkdir(parents=True, exist_ok=True)
                    im.save(media / "img" / name, quality=82, optimize=True, progressive=True)
                    data["photos"].append(dict(mid=mid, ts=ts, file=name, alt=f"Выдача {car}".strip(), hash=h))
                    pool.append(h)
                    added_p += 1
                elif a.get("type") == "video" and p.get("token"):
                    v = api(f"/videos/{p['token']}")
                    url = (v.get("urls") or {}).get("mp4_720") or next(iter((v.get("urls") or {}).values()), "")
                    thumb = (a.get("thumbnail") or {}).get("url") or (v.get("thumbnail") or {}).get("url") or ""
                    if not url:
                        continue
                    poster = fetch_image(thumb) if thumb else None
                    h = ahash(poster) if poster else None
                    if h and near(h, pool, 14):
                        continue
                    (media / "video").mkdir(parents=True, exist_ok=True)
                    raw = Path("/tmp") / f"{safe}-{i}.raw.mp4"
                    with requests.get(url, timeout=300, stream=True) as r:
                        r.raise_for_status()
                        with open(raw, "wb") as f:
                            for chunk in r.iter_content(1 << 20):
                                f.write(chunk)
                    name = f"{safe}-{i}"
                    # в отзывы — только видео с людьми (разгрузка автовоза, салон, таможня — мимо)
                    frames = video_frames(raw)
                    with_people = [f for f in ([poster] if poster else []) + frames if has_people(f)]
                    if not with_people:
                        raw.unlink(missing_ok=True)
                        continue
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-vf", "scale='min(720,iw)':-2",
                                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "96k",
                                    "-movflags", "+faststart", str(media / "video" / f"{name}.mp4")], check=True)
                    raw.unlink(missing_ok=True)
                    cover = with_people[0]
                    cover.thumbnail((720, 1280))
                    cover.save(media / "video" / f"{name}.jpg", quality=82)
                    h = h or ahash(cover)
                    dur = int(v.get("duration") or a.get("duration") or 0)
                    data["videos"].append(dict(mid=mid, ts=ts, file=name, quote=quote, car=car,
                                               dur=f"{dur // 60}:{dur % 60:02d}" if dur else "", hash=h))
                    if h:
                        pool.append(h)
                    added_v += 1
            except Exception as ex:  # одно вложение не скачалось — остальное размещаем
                print("пропуск вложения:", mid, type(ex).__name__, str(ex)[:120])
        done.add(mid)
        if added_v >= 15:  # первый разбор большой: не больше 15 видео за запуск, остальные — в следующий час
            break
    # новые сверху, лишнее старое — долой
    for key, cap, sub in (("photos", MAX_PHOTOS, "img"), ("videos", MAX_VIDEOS, "video")):
        items = sorted(data[key], key=lambda x: -x["ts"])
        for x in items[cap:]:
            for f in (media / sub).glob(x["file"].rsplit(".", 1)[0] + "*"):
                f.unlink()
        data[key] = items[:cap]
    media.mkdir(parents=True, exist_ok=True)
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"добавлено фото: {added_p}, видео: {added_v}; всего фото {len(data['photos'])}, видео {len(data['videos'])}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    site = Path(os.environ.get("SITE_DIR", "."))
    if not os.environ.get("MAX_TOKEN"):
        print("Нет MAX_TOKEN — жду.")
        sys.exit(0)
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if mode == "probe":
        probe(site)
    elif mode == "run":
        run(site)
