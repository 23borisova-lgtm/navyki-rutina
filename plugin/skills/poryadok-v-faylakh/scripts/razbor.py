#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разбор файлов: Загрузки + Рабочий стол + россыпь в Документах -> понятная структура.
Ничего не удаляет. Каждое перемещение пишется в лог, из лога генерируется откат."""

import os, sys, csv, unicodedata, datetime, shutil
from pathlib import Path

HOME = Path.home()
DOWNLOADS = HOME / "Downloads"
DESKTOP = HOME / "Desktop"
DOCUMENTS = HOME / "Documents"
BASE = DOCUMENTS

DRY = "--run" not in sys.argv

def norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).lower()

# --- структура берётся из настройки владелицы, а не прошита в скрипт ---
CONFIG = Path(os.environ.get("PORYADOK_CONFIG",
              str(HOME / ".claude" / "poryadok" / "struktura.json")))
DEFAULT = Path(__file__).resolve().parent.parent / "assets" / "struktura.example.json"

def load_config():
    """Читает папки и правила. Образец годится только для холостого прогона:
    раскладывать настоящие файлы по чужим правилам нельзя."""
    import json
    path = CONFIG if CONFIG.exists() else DEFAULT
    if not path.exists():
        sys.exit("Нет файла структуры. Скопируй assets/struktura.example.json "
                 f"в {CONFIG} и опиши свои папки.")
    if path == DEFAULT:
        if not DRY:
            sys.exit(f"Своей структуры нет ({CONFIG}), а образец — не твои правила.\n"
                     "Скопируй assets/struktura.example.json туда, перепиши под себя\n"
                     "и только потом запускай с --run.")
        print(f"ВНИМАНИЕ: своей структуры нет, показываю по образцу {DEFAULT.name}.")
        print(f"Перед разбором скопируй его в {CONFIG} и перепиши под себя.\n")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    rules = [(r["kuda"], [norm(k) for k in r.get("slova", [])], r.get("rasshireniya", []))
             for r in cfg.get("pravila", [])]
    return path, set(cfg.get("ne_trogat", [])), tuple(cfg.get("prefiksy_struktury", [])), rules

CONFIG_USED, KEEP, NEW_TREE_PREFIXES, RULES = load_config()

PHOTO_EXT = {"jpg","jpeg","png","heic","heif","tif","tiff","webp","gif","bmp"}
VIDEO_EXT = {"mov","mp4","avi","m4v","mkv","wmv","mpg","mpeg","3gp"}
PHOTO_PAT = ("img_","dsc_","dscn","photo_","изображение_viber","снимок экрана",
             "screenshot","lwscreenshot","vid_","image_","фото","_dsc","p_2")

ARCH_BY_EXT = {
    **{e: "Документы" for e in ("doc","docx","rtf","odt","pages","txt","md","tex")},
    **{e: "Таблицы"   for e in ("xls","xlsx","csv","numbers","ods")},
    **{e: "PDF"       for e in ("pdf",)},
    **{e: "Презентации" for e in ("ppt","pptx","key","odp")},
    **{e: "Архивы"    for e in ("zip","rar","7z","tar","gz","tgz","bz2")},
    **{e: "Дизайн"    for e in ("ai","eps","cdr","psd","indd","svg","sketch","fig")},
    **{e: "Аудио"     for e in ("mp3","wav","m4a","aac","ogg")},
}

JUNK_EXT = {"dmg","pkg","crdownload","part","tmp","download","aria2"}

def year_of(p: Path) -> str:
    try:
        return datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y")
    except Exception:
        return "без даты"

def classify(p: Path):
    """вернуть путь назначения относительно BASE"""
    name = norm(p.name)
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    yr = year_of(p)
    is_dir = p.is_dir()

    # --- мусор ---
    if not is_dir:
        if p.name.startswith("~$") or p.name.startswith("._"):
            return f"09 Мусор/Временные файлы Office"
        if ext in JUNK_EXT:
            return f"09 Мусор/Установщики и обрывки загрузок"
        try:
            if p.stat().st_size == 0:
                return f"09 Мусор/Пустые файлы"
        except Exception:
            pass

    # --- ключи и сертификаты электронной подписи ---
    if not is_dir and ext in ("p12","pfx","cer","crt","key","pem"):
        return "03 Личное/Документы/Электронная подпись"

    # --- правила по ключевым словам ---
    for dest, kws, exts in RULES:
        if any(k in name for k in kws) or (ext and ext in exts):
            return f"{dest}/{yr}"

    # --- фото и видео ---
    if not is_dir:
        if ext in PHOTO_EXT or ext in VIDEO_EXT or any(name.startswith(x) for x in PHOTO_PAT):
            kind = "Видео" if ext in VIDEO_EXT else "Фото"
            return f"05 Фото и видео/{yr}/{kind}"

    # --- архив по типу ---
    if is_dir:
        return f"04 Архив/{yr}/Папки"
    return f"04 Архив/{yr}/{ARCH_BY_EXT.get(ext, 'Прочее')}"

def unique_target(dest_dir: Path, name: str) -> Path:
    t = dest_dir / name
    if not t.exists():
        return t
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    i = 2
    while True:
        cand = dest_dir / (f"{stem} ({i}).{ext}" if ext else f"{stem} ({i})")
        if not cand.exists():
            return cand
        i += 1

ONLY_INBOX = "--only-inbox" in sys.argv

def sources():
    """что разбираем"""
    import time
    fresh = time.time() - 7*86400   # свежее недели не трогаем: с этим ещё работают
    for p in sorted(DOWNLOADS.iterdir()):
        if p.name.startswith("."):
            continue
        if ONLY_INBOX:
            try:
                if p.stat().st_mtime > fresh:
                    continue
            except Exception:
                pass
        yield p
    for p in sorted(DESKTOP.iterdir()):
        if p.name.startswith("."):
            continue
        if ONLY_INBOX:
            try:
                if p.stat().st_mtime > fresh:
                    continue
            except Exception:
                pass
        yield p
    if ONLY_INBOX:
        return
    for p in sorted(DOCUMENTS.iterdir()):
        if p.name.startswith("."):
            continue
        if p.name in KEEP:
            continue
        if p.name.startswith(NEW_TREE_PREFIXES):
            continue
        yield p

def main():
    moves = []
    stats = {}
    for p in sources():
        rel = classify(p)
        stats[rel.split("/")[0] + "/" + (rel.split("/")[1] if "/" in rel else "")] = \
            stats.get(rel.split("/")[0] + "/" + (rel.split("/")[1] if "/" in rel else ""), 0) + 1
        moves.append((p, BASE / rel))

    print(f"Всего объектов к разбору: {len(moves)}\n")
    print("=== РАСКЛАДКА ===")
    for k in sorted(stats, key=lambda x: -stats[x]):
        print(f"{stats[k]:6d}  {k}")

    if DRY:
        print("\n[холостой прогон] Ничего не перемещено. Для запуска: --run")
        return

    logdir = BASE / "09 Мусор" / "_служебное"
    logdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    logpath = logdir / f"разбор_{stamp}.csv"

    done = err = 0
    with open(logpath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["откуда", "куда"])
        for src, dest_dir in moves:
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
                tgt = unique_target(dest_dir, src.name)
                shutil.move(str(src), str(tgt))
                w.writerow([str(src), str(tgt)])
                done += 1
            except Exception as e:
                err += 1
                print(f"  ! не удалось: {src.name} -> {e}")

    # скрипт отката
    undo = logdir / f"ОТКАТИТЬ_{stamp}.py"
    undo.write_text(f'''#!/usr/bin/env python3
# Возвращает всё ровно туда, где лежало до разбора {stamp}.
import csv, shutil, os
from pathlib import Path
log = Path(r"{logpath}")
n = 0
for row in list(csv.DictReader(log.open(encoding="utf-8")))[::-1]:
    src, dst = Path(row["куда"]), Path(row["откуда"])
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst)); n += 1
print("возвращено объектов:", n)
''', encoding="utf-8")

    print(f"\nПеремещено: {done}, ошибок: {err}")
    print(f"Структура: {CONFIG_USED}")
    print(f"Лог:    {logpath}")
    print(f"Откат:  python3 '{undo}'")

if __name__ == "__main__":
    main()
