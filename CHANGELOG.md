# Changelog

## 0.7.0

- pipeline: `pipeline/release_watch.py` + `pipeline/promote.py` — гейт на
  апгрейд пина `qlik-sense-mcp-server` (read-only сверка PyPI/GitHub vs
  пин, промоушен требует отчёт живого regression-теста с `verified_live:
  true` на каждый claim, иначе отказ; патчит `MCP_SERVER_VERSION`/
  `RELEASE_NOTES` только после зелёного гейта). Формат отчёта —
  `pipeline/regression-report.schema.md`.
- distribution: добавлен `.agents/plugins/marketplace.json` +
  `.codex-plugin/plugin.json` — Codex CLI (0.140.0, live-подтверждено
  19.08.2026) читает СВОЙ проприетарный каталог, а НЕ корневой
  Agent-Plugins `plugin.json` напрямую (`codex plugin add` без каталога
  падал с "plugin not found"). Схема снята с живого прецедента
  (`qlik-analysis-accelerator`, отдельный локальный Codex-плагин
  пользователя, теперь выведен из эксплуатации в пользу этого репо).
  Живьём подтверждено на всех трёх клиентах: `claude plugin marketplace
  add`/`install` — плагин ставится, MCP-сервер `qlik` подключается
  (`claude mcp list` → Connected); `codex plugin marketplace add`/`add` —
  плагин ставится. Cursor — манифест на месте с 0.4.0, живой Import from
  Repo всё ещё не подтверждён (GUI-действие, не автоматизируется отсюда).
- важно: Codex CLI НЕ читает MCP-конфиг из плагина/маркетплейса вообще
  (ни `mcp.json`, ни `.mcp.json`) — это отдельный слой `codex mcp add` /
  `~/.codex/config.toml [mcp_servers.*]`. Поэтому пин версии сервера,
  который этот toolkit распространяет через `mcp.json`/`.mcp.json`,
  Codex не подхватывает никак; для Codex версия сервера обновляется
  только вручную через `codex mcp add`/правку `config.toml` — рекомендация
  дана в `README.md`, раздел "Codex CLI".

## 0.6.0

- fix: `qlik-mcp-data-access/scripts/hypercube_builder.py` —
  `engine_create_hypercube.dimensions[].field` на 2.0.2 требует
  `[квадратных скобок]` для многословных имён (падает явной
  `invalid_expression`, было — либо не требовалось, либо тихо схлопывало
  dimension на более старой версии). `build_dimension()`/
  `build_id_list_sort_expression()` теперь сами оборачивают через
  `quote_field()` — раньше это делалось только для `engine_query`.
  Live-подтверждено 16.08.2026 на `llm_model_top50_clients`.
  `build_hypercube_request_modern()` — добавлены `offset`/`suppress_zero`
  (реальные top-level параметры схемы 2.0.2, раньше не прокидывались).
- docs: `references/tool-catalog.md`/`SKILL.md` (`qlik-mcp-data-access`,
  `mcp-qlik`) — опровергнуты живым тестом две гипотезы из CHANGELOG
  апстрима 2.0.1, записанные в 0.5.0 без проверки: out-of-range `offset`
  НЕ возвращает ошибку (тихо `returned_rows: 0`, `has_more: false`);
  перевёрнутые границы периода в `filters` НЕ возвращают ошибку (сервер
  сам переставляет местами, видно в `filters_applied`/`period_check`).
  Третий пункт («противоречивые условия фильтра») не тестировался, статус
  не определён. `release_watch.py`/`promote.py` для автообнаружения
  апстрим-релизов всё ещё не реализован — апгрейд и живая проверка снова
  сделаны вручную.

## 0.5.0

- mcp: `qlik-sense-mcp-server==2.0.2` (pinned, было 2.0.0). Апстрим
  выпустил два патча без ручного апгрейда с нашей стороны:
  - 2.0.1 (13.08.2026): по CHANGELOG апстрима (НЕ live-проверено на момент
    записи) — сервер якобы больше не решает молча за вызывающую сторону:
    выход offset/limit за пределы, перевёрнутые границы периода и
    противоречивые условия фильтра теперь якобы возвращают явную ошибку;
    пустые группы значений измерения больше не выкидываются по умолчанию;
    имена полей с пробелами корректно оборачиваются в `[...]` в валидации
    выражений.
  - 2.0.2 (14.08.2026): убран служебный файл, который писался в корень при
    разборе.
  Live-тест 16.08.2026 (см. 0.6.0 ниже) ОПРОВЕРГ два из этих пунктов —
  читать 0.6.0, не эту запись, за фактическим поведением.

## 0.4.0

- fix: добавлен `.cursor-plugin/marketplace.json` — без него Dashboard ->
  Plugins -> "Import from Repo" в Cursor не распознаёт репозиторий как
  team-маркетплейс (это отдельный, проприетарный каталожный манифест,
  не путать с корневым `plugin.json`, который уже соответствует Agent
  Plugins spec и грузится в Cursor без изменений). `validate.py` теперь
  проверяет его на обязательные поля и что `source` каждого плагина
  указывает на реальный `plugin.json`/`.cursor-plugin/plugin.json`.
  Схема собрана по документации Cursor 13.08.2026, живым импортом в
  Cursor ЕЩЁ НЕ подтверждена — обновить статус после первого реального
  Import from Repo.

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
