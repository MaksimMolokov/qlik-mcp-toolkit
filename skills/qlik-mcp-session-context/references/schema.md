# Схема хранилища сессии

Файл: `$QLIK_MCP_TOOLKIT_HOME/session-context.json` (по умолчанию `~/.qlik-mcp-toolkit/`).

Корень: `schema_version`, `session_key`, `updated_at`, `active_result_key`,
`apps`, `queries`, `derivations`.

**`queries[key]`** (ключ — `normalized_query_key()`):
- `app_id`, метрика/выражение, период, фильтры, dimensions, selection_semantics;
- `columns` и полный вернувшийся `rows` (population — точный список сущностей);
- `grand_total`, `total_rows`/`returned_rows`, признак усечения;
- `validation_status`: `validated`/`suspect`/`partial`/`failed` — только
  `validated` может быть источником для follow-up-ответа;
- `reload_fingerprint`, `tool_call_seconds`.

Провалившиеся/частичные попытки можно сохранить (для диагностики), но
`validation_status` у них не `validated`, и `active_rows()`/`derive_rows()` их
не видят.

**`derivations[]`** — след локальных операций поверх `active_rows()`:
`derived_from_query_key`, `operation`, `result`, `created_at`. Не заменяют
`queries` — это лог того, что было посчитано локально, а не новый источник
правды для СЛЕДУЮЩЕГО follow-up (для этого сохраняй новый `queries[key]`, если
операция дала данные, которые дальше пригодятся).

Никогда не пиши сюда JWT, заголовки авторизации, полные логи ошибок с
чувствительными данными.
