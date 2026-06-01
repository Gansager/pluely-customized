#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-of-meeting summarizer.

Reads recent conversations from Pluely's SQLite (pluely.db), concatenates them
chronologically, sends to `claude -p` for a structured summary, saves the result
as markdown in ~/Documents/Pluely Meetings/, and copies it to the clipboard.

Window heuristic: walk back from the latest message; treat any gap > GAP_MINUTES
as a session boundary. Override with --hours N to use a fixed lookback.
"""
import argparse, os, sqlite3, subprocess, sys, time, shutil, ctypes, datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = Path(os.environ["APPDATA"]) / "com.srikanthnani.pluely" / "pluely.db"
OUT_DIR = Path(os.environ["USERPROFILE"]) / "Documents" / "Pluely Meetings"
GAP_MINUTES = 30

PROMPT_HEADER = """Ты — ассистент, который пишет краткий протокол ТЕХНИЧЕСКОГО созвона команды разработки. Ниже — хронологический лог: транскрипции голоса (через STT — могут быть опечатки и спутаны имена сервисов/тикетов) + ответы ИИ-суфлёра. Все реплики идут как role=user, без разделения на меня/коллег — разбирайся по смыслу.

Сделай структурированный маркдаун на языке преобладающей речи (RU/EN/DE).

## Что обсудили
- 3–8 буллетов с темами обсуждения. Если упомянуты конкретные сервисы / репы / тикеты / PR-ы — называй их прямо.

## Технические решения
- архитектурные/инженерные решения с коротким "почему" (или "Нет явных решений")
- если решение спорное и были возражения — отметь

## Action items
- "- [ ] <кто>: <что> — <дедлайн|приоритет>" (если ответственный/срок не явный — пиши "?"). Группируй: сначала action items на меня, потом на остальных.

## Блокеры и риски
- что мешает или может мешать (или "Нет")

## Открытые технические вопросы
- что не решили / надо вынести в отдельную сессию (или "Нет")

## Ссылки/референсы
- PR #N, тикет PROJ-123, ссылка на доку, имя сервиса в проде — всё что упоминалось как артефакт. Если ничего — пропусти секцию.

ПРАВИЛА:
- Игнорируй технический шум: ошибки сетевых запросов ассистента, тестирование STT/настройки Pluely, фразы "раз-два-три проверка связи".
- Не выдумывай имена сервисов/тикетов которых не было в логе.
- Будь краток. Только маркдаун, без преамбулы.

---
ЛОГ ВСТРЕЧИ:
"""

def fetch_messages(hours: int | None):
    if not DB_PATH.exists():
        sys.exit(f"DB не найдена: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # Get all messages sorted oldest→newest
    rows = list(cur.execute("SELECT timestamp, role, content FROM messages ORDER BY timestamp ASC"))
    con.close()
    if not rows:
        sys.exit("Нет сообщений в истории Pluely.")
    if hours is not None:
        cutoff = int(time.time() * 1000) - hours * 3600 * 1000
        rows = [r for r in rows if r[0] >= cutoff]
        if not rows:
            sys.exit(f"Нет сообщений за последние {hours}ч.")
        return rows
    # Gap heuristic: start from the latest, walk back while gap < GAP_MINUTES
    gap_ms = GAP_MINUTES * 60 * 1000
    cut_idx = 0
    for i in range(len(rows) - 1, 0, -1):
        if rows[i][0] - rows[i - 1][0] > gap_ms:
            cut_idx = i
            break
    return rows[cut_idx:]

def format_log(rows):
    lines = []
    for ts, role, content in rows:
        t = datetime.datetime.fromtimestamp(ts / 1000).strftime("%H:%M")
        tag = "Я" if role == "user" else "Ассистент"
        lines.append(f"[{t}] {tag}: {content}")
    return "\n".join(lines)

def call_claude(full_prompt: str) -> str:
    claude = shutil.which("claude.cmd") or shutil.which("claude.exe") or shutil.which("claude")
    if not claude:
        sys.exit("claude CLI не найден в PATH.")
    r = subprocess.run([claude, "-p", "--output-format", "text"],
                       input=full_prompt, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300, shell=False)
    if r.returncode != 0:
        sys.exit(f"claude rc={r.returncode}: {(r.stderr or '').strip()[:500]}")
    return (r.stdout or "").strip()

def copy_to_clipboard(text: str):
    try:
        p = subprocess.Popen(["clip.exe"], stdin=subprocess.PIPE)
        p.communicate(input=text.encode("utf-16-le"))
    except Exception as e:
        print(f"⚠️  Не смог скопировать в буфер: {e}", file=sys.stderr)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=None, help="Фиксированный lookback в часах. По умолчанию — авто (gap > 30 мин = граница).")
    ap.add_argument("--open", action="store_true", help="Открыть итоговый md в системе после сохранения.")
    a = ap.parse_args()

    rows = fetch_messages(a.hours)
    span_min = (rows[-1][0] - rows[0][0]) / 60000
    print(f"Сессия: {len(rows)} сообщений, {span_min:.0f} мин ({datetime.datetime.fromtimestamp(rows[0][0]/1000):%H:%M}–{datetime.datetime.fromtimestamp(rows[-1][0]/1000):%H:%M})", flush=True)

    log = format_log(rows)
    print(f"Отправляю в Claude ({len(log):,} симв)…", flush=True)
    summary = call_claude(PROMPT_HEADER + log)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fname = datetime.datetime.now().strftime("%Y-%m-%d_%H%M") + ".md"
    out = OUT_DIR / fname
    header = f"# Pluely meeting — {datetime.datetime.now():%Y-%m-%d %H:%M}\n\n_сообщений: {len(rows)} · длительность: {span_min:.0f} мин_\n\n"
    out.write_text(header + summary + "\n\n---\n\n<details><summary>Полный лог</summary>\n\n```\n" + log + "\n```\n</details>\n", encoding="utf-8")
    copy_to_clipboard(summary)
    print(f"✅ Сохранено: {out}")
    print("✅ Скопировано в буфер обмена.")
    if a.open:
        os.startfile(str(out))

if __name__ == "__main__":
    main()
