"""Логирует каждый вопрос-ответ через Qlik MCP: вопрос, ответ, приложение-
источник и время выполнения.

Назначение — не для пользователя-читателя (это НЕ worklog), а сырьё для
дальнейшей доработки скиллов/MCP: накопить реальные вопросы и то, как на
них ответили, чтобы потом видеть, где ответы были медленными/неверными/
неполными.

Формат хранения — JSON Lines, один файл в день (`Report-MCP/YYYY-MM-DD.jsonl`),
строго ДОПИСЫВАНИЕМ в конец файла ("a", один `write()`) — никогда не читает
и не перезаписывает файл целиком, чтобы не тормозить обычную работу MCP
(итоговая стоимость записи — миллисекунды, дешевле любого одного вызова
mcp__qlik__*).

Два режима, вызываются агентом как два отдельных шага workflow
(qlik-mcp-analysis/SKILL.md):

  python log_interaction.py --start
      Печатает текущее время ISO 8601 — агент запоминает его как started_at
      и передаёт в --finish без изменений. Никакой файл не создаётся и не
      трогается — это не логирование, а просто "текущее время" из одного
      надёжного источника (не полагаемся на то, что модель точно знает
      текущее время до секунды).

  python log_interaction.py --finish --started-at TS --app "..."
                             --question "..." --answer "..."
      Считает duration_ms = now - started_at, дописывает одну JSON-строку
      в Report-MCP/<сегодня>.jsonl.

Путь хранения — `REPORT_DIR` ниже, локальная разработка (это репо
Work\\.claude\\skills\\...) использует абсолютный путь по тем же соглашениям,
что app_cache.py/session_store.py; qlik-mcp-toolkit/scripts/bootstrap.py
патчит этот путь на переменную окружения `QLIK_MCP_TOOLKIT_HOME` (по
умолчанию `~/.qlik-mcp-toolkit/`) при сборке дистрибутива — у конечного
пользователя лог ложится в ЕГО домашний каталог, не на диск разработчика.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import os
REPORT_DIR = Path(os.environ.get("QLIK_MCP_TOOLKIT_HOME", str(Path.home() / ".qlik-mcp-toolkit"))) / "Report-MCP"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def finish(started_at: str, app: str, question: str, answer: str, report_dir: Path = REPORT_DIR) -> Path:
    started = datetime.fromisoformat(started_at)
    finished = datetime.now(timezone.utc).astimezone()
    duration_ms = round((finished - started).total_seconds() * 1000)

    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / f"{finished.date().isoformat()}.jsonl"
    entry = {
        "ts": finished.isoformat(timespec="milliseconds"),
        "question": question,
        "answer": answer,
        "app": app,
        "duration_ms": duration_ms,
    }
    # Один write() в режиме append — не читаем и не парсим существующий
    # файл, поэтому стоимость не растёт с числом уже записанных строк.
    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--start", action="store_true", help="Напечатать текущее время ISO 8601 и выйти")
    mode.add_argument("--finish", action="store_true", help="Записать завершённое взаимодействие")
    ap.add_argument("--started-at", help="Значение, напечатанное предыдущим --start (обязательно для --finish)")
    ap.add_argument("--app", help="Имя/id приложения-источника ответа (обязательно для --finish)")
    ap.add_argument("--question", help="Вопрос пользователя как есть (обязательно для --finish)")
    ap.add_argument("--answer", help="Итоговый ответ как есть (обязательно для --finish)")
    args = ap.parse_args()

    if args.start:
        print(now_iso())
        return

    missing = [name for name, val in (("--started-at", args.started_at), ("--app", args.app),
                                       ("--question", args.question), ("--answer", args.answer)) if not val]
    if missing:
        print(f"ERROR: --finish требует {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    out_path = finish(args.started_at, args.app, args.question, args.answer)
    print(f"OK: записано в {out_path}")


if __name__ == "__main__":
    main()
