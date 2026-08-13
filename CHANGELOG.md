# Changelog

## 0.3.0

- fix: `qlik-mcp-session-context/scripts/session_store.py` — `session_key`
  никогда не передавался вызывающим кодом, поэтому хранилище было одним
  общим файлом без изоляции между беседами (population из давней беседы
  могла тихо подмениться в новую). Добавлен `stale_after_seconds`
  (default 2ч, по `updated_at`) — `load()` теперь сама сбрасывает
  хранилище на устаревшей записи. Live-подтверждено 13.08.2026 (реальный
  MCP-результат → follow-up локально → искусственно состаренная запись →
  сброс), до этого теста файл хранилища ни разу не создавался на диске.

## 0.2.0

- mcp: `qlik-sense-mcp-server==2.0.0` (pinned, было 1.9.0). Новое:
  инструмент `engine_query` (group_by/metrics/filters/sort_by/limit, batch
  `queries`, сервер сам пишет Set Analysis), `{filter}`-маркер в
  `engine_create_hypercube`. Live-подтверждено 13.08.2026.
- skills: `qlik-mcp-data-access/scripts/hypercube_builder.py` — новые
  `build_engine_query()`/`quote_field()` (многословные имена полей в
  `engine_query` требуют `[квадратных скобок]`, у `engine_create_hypercube`
  такого требования нет); `references/tool-catalog.md`/`SKILL.md`
  синхронизированы с живой схемой 2.0.0; `qlik-mcp-analysis` шаг 9
  предпочитает `engine_query` для простых group-by-вопросов.

## 0.1.0 — первый выпуск

- skills: qlik-mcp-analysis, qlik-mcp-data-access, qlik-mcp-session-context
  (санированные копии Work-скиллов, абсолютные пути заменены на
  `QLIK_MCP_TOOLKIT_HOME`).
- mcp: `qlik-sense-mcp-server==1.9.0` (pinned).
