# Changelog

## 2.3.0.6

- **Git больше не нужен пользователю Cursor.** 2.3.0.5 доставлял обновления
  через `git fetch` / local-клон. У кого Git не в PATH процесса Cursor,
  плагин падал с `spawn git ENOENT`, хук не стартовал, MCP оставался на
  старом `uvx`-кэше (у коллеги: toolkit 2.3.0.5 на диске, MCP 2.0.2).
  Теперь Git опционален:
  - origin читается по HTTPS (`plugin.json` + zipball GitHub);
  - скиллы кладутся в `plugins/local` **без** `.git`, чтобы Cursor не
    спавнил git;
  - если zip недоступен — берётся уже скачанный кэш маркетплейса;
  - пин MCP как в 2.3.0.4 плюс переписывание `command: qlik-sense-mcp-server`
    (uv tool) → `uvx ==пин`.
  Первый заход / ремонт без Git:
  `irm https://raw.githubusercontent.com/MaksimMolokov/qlik-mcp-toolkit/main/hooks/install-cursor.ps1 | iex`.
  `HOOK_LOGIC_VERSION` -> `2.3.0.6`.

## 2.3.0.5

- **Хук снова сам доставляет скиллы И MCP, без Refresh маркетплейса.**
  2.3.0.4 запинывал MCP, но только из уже скачанного снимка Cursor —
  GitHub не трогал. Поэтому у коллеги toolkit мог быть новым, а MCP
  старым (или наоборот: снимок кэша завис, скиллы не едут). Теперь
  `sessionStart`:
  1. `git fetch --depth 1 origin/main` и сравнение с кэшем маркетплейса;
     побеждает большая версия, при равенстве — GitHub;
  2. local-клон сбрасывается на победителя;
  3. хуки копируются из победителя (даже если снимка маркетплейса нет);
  4. устаревшие папки в `plugins/cache` перезаписываются skills/rules/
     hooks — Cursor читает именно их, `pluginPaths` не работает;
  5. пин MCP как в 2.3.0.4 (голый пакет → `==<пин>`, prefetch uvx),
     фолбэк пина: `.mcp.json` → три цифры toolkit → `HOOK_LOGIC_VERSION`.
  `HOOK_LOGIC_VERSION` -> `2.3.0.5`.

## 2.3.0.4

- **MCP теперь доезжает вместе с toolkit, даже если конфиг был без пина.**
  У коллеги toolkit уже был 2.3.0.3, а `qlik-sense-mcp-server` оставался
  старым: хук умел только заменить `package==old` на `package==new` и
  **пропускал** голый `qlik-sense-mcp-server` (так было у Codex и у тех,
  кто ставил MCP руками). `uvx` без версии держит старый кэш и не
  смотрит на PyPI. Теперь `update_mcp_pin()`:
  - берёт пин из `.mcp.json` снимка, а если там нет `==версии` — из
    первых трёх цифр toolkit (`2.3.0.4` → `2.3.0`);
  - переписывает голый пакет в `~/.cursor/mcp.json` и plugin MCP на
    `qlik-sense-mcp-server==<пин>`;
  - prefetch'ит это колесо через `uvx --from ...==<пин>`, чтобы диск
    совпал с пином до рестарта MCP.
  Codex `.mcp.json` тоже запинен (больше не «latest с PyPI через кэш»).
  `HOOK_LOGIC_VERSION` -> `2.3.0.4`.

## 2.3.0.3

- **КРИТИЧНО: `workspaceOpen` — невалидное событие Cursor.** По логу
  самого Cursor (`cursor.hooks*.log`, 31.08.2026): `Unknown hook type:
  workspaceOpen ... Failed to parse user hooks configuration` — один плохой
  ключ отбрасывает ВЕСЬ `hooks.json`, поэтому НИ ОДИН наш хук в Cursor не
  запускался (все прежние «запуски» — ручные). Валидное событие старта —
  только `sessionStart`. `hooks/hooks.json` теперь `sessionStart`-only; из
  `output_for_event()` убрана мёртвая ветка `workspaceOpen` (её
  `pluginPaths`-оверрайд никогда не срабатывал — версию/загрузку плагина
  Cursor берёт из своего кэша маркетплейса сам). `HOOK_LOGIC_VERSION` -> `2.3.0.3`.

## 2.3.0.2

- **fix: удаление события в `hooks/hooks.json` теперь доезжает до
  установленного Cursor.** `hooks.json` не входит в `HOOK_FILES` и как скрипт
  не копировался — из-за этого снятый в 0.20.0 триггер `beforeSubmitPrompt`
  оставался в `~/.cursor/hooks.json` навсегда. Добавлен `reconcile_hooks_json()`
  (вызывается из `refresh_user_hooks`): наши записи (узнаём по имени команды
  `update-qlik-mcp`/`sync-qlik-mcp-env`) в `~/.cursor/hooks.json` и
  `~/.cursor/hooks/hooks.json` приводятся к снимку маркетплейса, чужие хуки
  не трогаются, опустевшие события удаляются. `HOOK_LOGIC_VERSION` -> `2.3.0.2`.

## 2.3.0.1

- **новая схема версий toolkit** (по просьбе пользователя 31.08.2026):
  `TOOLKIT_VERSION` = `<пин MCP-сервера>.<итерация>` (первые три цифры всегда
  равны `MCP_SERVER_VERSION`, четвёртая — правки самого toolkit). Была `0.21.0`
  под пин 2.3.0 — стала `2.3.0.1`. `pipeline/promote.py` при бампе пина теперь
  ставит `<новый пин>.1`. `HOOK_LOGIC_VERSION` -> `2.3.0.1`. Ранние релизы
  `0.1.0..0.21.0` в истории не трогаются. Функциональных изменений нет.

## 0.21.0

- follow-up к регрессии 2.3.0 (2 решения пользователя 31.08.2026):
  - **хук `hooks/update-qlik-mcp.py` больше НЕ бампит пин MCP с PyPI/GitHub.**
    `update_mcp_pin()` теперь выравнивает `~/.cursor/mcp.json` (и локальный
    клон) ТОЛЬКО по `.mcp.json` снимка маркетплейса — то есть по тому, что
    прошло гейт `pipeline/promote.py` и было запушено. Закрыт давний открытый
    вопрос «хук обходит гейт». Удалены `pypi_latest`/`github_latest_tag`/
    `pypi_has_version`/`http_json`/`version_gt`/`MCP_GITHUB_REPO`. Из
    `hooks/hooks.json` убран триггер `beforeSubmitPrompt` (проверка версии
    только на `workspaceOpen`/`sessionStart`). `HOOK_LOGIC_VERSION` 0.18.0 -> 0.21.0.
  - **`{filter}` в `engine_create_hypercube` заблокирован в коде.**
    `hypercube_builder.build_measure()` и `build_hypercube_request_modern()`
    бросают `ValueError` на маркер `{filter}` (регрессия 2.3.0 — молча даёт
    нули). Фильтрованная мера: `engine_query` (там `{filter}` работает) или
    ручной Set Analysis. Обновлены `qlik-mcp-data-access` SKILL.md +
    `references/tool-catalog.md` (раздел «2.0.2 -> 2.3.0») и `qlik-mcp-analysis`
    `references/tool-workflows.md` + `source-notes.md`.

## 0.20.0

- mcp: `qlik-sense-mcp-server==2.3.0` (pinned, было `2.0.2`). Гейт
  `pipeline/promote.py` — regression прогнан живьём 2026-08-31T10:04:38+00:00
  на `llm_model_top50_clients + Профиль клиента (MCP)`, отчёт заархивирован в
  `pipeline/regression-reports/2.3.0.json`:
  - get_app_details smoke — opens app, returns full data model + field
    comments — **confirmed** (llm_model_top50_clients (5 tables, 74 fields)
    returned in 11.9s; Профиль клиента (MCP) (29 tables, 202 fields) in 29.1s.
    New in output: named_sets.bookmarks list (8 bookmarks on the 2nd app).)
  - engine_query smoke — group_by + aggregate metric — **confirmed**
    (group_by=[Вид спорта], sum(Оборот по позиции), sort+limit 5 → 5 rows,
    grand_total 6,447,684,363.9, 3.9s. engine_query is promoted to the front
    of the Engine tool list in 2.3.0 --help.)
  - multi-word field names no longer need [square brackets] in engine_query
    group_by / metrics[].field — **confirmed** (Passed 'Вид спорта' / 'Оборот
    по позиции' unbracketed in group_by and metrics[].field — resolved
    correctly. On <=2.0.2 the skill wrapped these in brackets
    (hypercube_builder.quote_field); on 2.3.0 unbracketed works. Bracketed
    form still accepted.)
  - engine_query period filter — {field, period:'2026-08'} — server writes set
    analysis and reports what it selected — **confirmed** (period '2026-08' →
    filters_applied reports serial_from 46235 / serial_to_exclusive 46266 /
    distinct_values_in_period 30, and period_check reports earliest_in_result
    01.08.2026 / latest 30.08.2026 / filter_applied true. Richer verification
    payload than 2.0.2.)
  - engine_create_hypercube modern schema (top-level
    dimensions/measures/sort_by/sort_order/limit) + manual Set Analysis on a
    text field in a measure — **confirmed** (dims=[Вид спорта], measure
    Sum({<[Тип ставки]={'Одинар'}>} [Оборот по позиции]), sort_by+limit → real
    numbers (футбол 2,549,886,729.3), 1.9s. Modern schema and manual
    set-analysis quoting both work.)
  - {filter} marker in engine_create_hypercube measures — server substitutes
    the described filter into the set modifier — **refuted** (REGRESSION.
    Sum({filter} [GGR по позиции]) with filters=[{Дата, period:'2026-08'}] AND
    Sum({filter} [Оборот по позиции]) with filters=[{Тип ставки,
    values:['Одинар']}] both returned ALL ZEROS. The measures[] echo in the
    response keeps the literal string 'Sum({filter} ...)' — the {filter} token
    is NOT expanded, Qlik evaluates it as nothing. Same call with an explicit
    manual set analysis returns correct numbers. On 2.0.0-2.0.2
    {filter}-in-hypercube was reported working. Workaround: use manual Set
    Analysis in hypercube measures, or use engine_query (see next check).)
  - {filter} marker works in engine_query measures[].expression —
    **confirmed** (engine_query measure Sum({filter} [Оборот по позиции]) with
    filters=[{Тип ставки, values:['Одинар']}] → correct numbers (футбол
    2,549,886,729.3, identical to the manual-SA value), and
    measure_filters[].filters_applied is reported. So {filter} is broken only
    in engine_create_hypercube, not in engine_query.)
  - out-of-range offset in engine_query — explicit error vs silent empty —
    **confirmed** (offset=999999 → returned_rows 0, no error, but now adds
    numbers_verified:false and warning 'No rows matched...'. Still silent-ish
    (no hard error) as on 2.0.2, marginally better signal.)
  - inverted period bounds (from > to) in engine_query filters — explicit
    error vs silent auto-swap — **confirmed** (CHANGED. filter {Дата,
    from:'2026-08-31', to:'2026-08-01'} → error_category 'invalid_period',
    message 'Period on [Дата] starts at 2026-08-31 and ends at 2026-08-01,
    which is earlier.' On 2.0.2 the server silently swapped the bounds. Now an
    explicit, isolated per-query failure (queries_failed:1, other queries in
    the batch still ran).)
  - contradictory filters (same field, two disjoint single-value selections)
    in engine_query — **partial** (filters=[{Тип ставки:['Одинар']},{Тип
    ставки:['Экспресс']}] → no error, returns a non-empty result (grand_total
    1,691,093,915) that looks like last-filter-wins rather than an
    intersection. filters_applied echoes both without a warning. Low severity,
    but silent.)
  - large filters[].values list (~120 client numbers) on Профиль клиента (MCP)
    — deterministic failure (was 5/5 ConnectionError on v7_sonnet5 / 2.0.2) —
    **partial** (1st attempt: error_type ConnectionError 'Not connected to
    Engine API' after 45.7s. Immediate retry (same 120 values): SUCCESS in
    14.9s, real data (Год 2025: 7,497,725 / 2026: 4,920,438). So on 2.3.0 it
    is NOT deterministic — it is the reconnect bug, and the mandatory
    single-retry recovers it.)
  - reconnect bug ('Not connected to Engine API' / CreateSessionObject
    timeout) — claimed fixed since 1.8.0, never verified our side —
    **refuted** (STILL PRESENT on 2.3.0. The 120-value engine_query failed on
    the first attempt with a ~45s ConnectionError even though the connection
    was warm (several successful calls immediately before), then succeeded on
    retry. The qlik-mcp-data-access mandatory 'retry the same call up to
    twice' rule stays in force.)
  - engine_query batch queries[] (multiple independent queries in one call)
    with partial-failure handling — **confirmed** (4-query batch (smoke /
    period / inverted-bounds / oor-offset) → queries_run 3, queries_failed 1,
    failed:['inverted_bounds'], the 3 good queries all returned. Batch is a
    new/expanded capability in the 2.3.0 schema (up to 25 queries,
    Metric.of/op/per/inner_agg, Scope with bookmarks & alternate states,
    Filter.matching/not_matching).)

## 0.19.0

- fix (по вопросу пользователя 27.08.2026 — увидел на GitHub что-то, что
  выглядело как «структура сломана»): найден и убран осиротевший
  `.codex-plugin/plugin.json` на КОРНЕ репозитория — версия застряла на
  0.12.0 (не обновлялась 6 версий подряд), ничего его не читает
  (`.agents/plugins/marketplace.json` указывает Codex на
  `./plugins/qlik-mcp-toolkit`, не на корень; реальный файл —
  `plugins/qlik-mcp-toolkit/.codex-plugin/plugin.json`, актуальный).
  Похоже, остался от версий ДО введения `CODEX_PLUGIN_SUBDIR` в 0.7.0 и
  никогда не был добавлен в `OBSOLETE_FILES`. Данные Cursor (`.cursor-
  plugin/plugin.json`, `hooks/hooks.json`, `rules/qlik-mcp.mdc`) сверены
  отдельно — на месте и актуальны (0.18.0), с этим проблем не было.

## 0.18.0

- cursor: хук больше НЕ тянет GitHub HEAD мимо маркетплейса и НЕ отдаёт
  `pluginPaths` на устаревший local-клон. Источник истины — новейший снимок
  `%USERPROFILE%\.cursor\plugins\cache\*\qlik-mcp-toolkit\<gitRef>`.
  Хук выравнивает `plugins/local` на ЭТОТ коммит, `pluginPaths` указывает
  на снимок маркетплейса, копирует хуки снимка в `~/.cursor/hooks` (без
  даунгрейда более новой user-hook сборки), выравнивает пин MCP и сразу
  гоняет env-sync по новому снимку (в том числе на beforeSubmitPrompt,
  не чаще раза в 60с). Если маркетплейса нет — фолбэк на origin/main.
- codex: после `marketplace upgrade` берёт новейший кэш-снимок и копирует
  хуки в `~/.codex/hooks`, затем env-sync.

## 0.17.0

- cursor + codex: хук `sync_qlik_mcp_env` копирует ЛИЧНЫЕ
  `QLIK_SERVER_URL` и `QLIK_JWT_TOKEN` пользователя в `.mcp.json` плагина.
  Cursor читает `%USERPROFILE%\.cursor\mcp.json` (`mcpServers.qlik.env`).
  Codex читает `%USERPROFILE%\.codex\config.toml`
  (`[mcp_servers.qlik.env]`). После обновления снимок снова приходит с
  `${QLIK_*}` — хук вписывает живые значения обратно. Секреты в git не
  коммитятся, в лог не пишутся.
- cursor: `hooks/hooks.json` на workspaceOpen / sessionStart — git
  fetch+reset `~/.cursor/plugins/local/qlik-mcp-toolkit` и пин MCP в
  `~/.cursor/mcp.json`, затем env-sync.
- codex: отдельная схема хуков в `plugins/qlik-mcp-toolkit/hooks/`
  (`SessionStart` startup|resume) — `codex plugin marketplace upgrade` +
  тот же env-sync из `config.toml`. Плагинные хуки Codex нужно один раз
  доверить через `/hooks`.

## 0.16.0

- codex (по просьбе пользователя 27.08.2026 — цель тулкита в целом:
  установил плагин → скиллы и MCP обновляются сами при каждом
  перезапуске/запуске клиента): добавлен `plugins/qlik-mcp-toolkit/.mcp.json`
  + поле `mcpServers` в `.codex-plugin/plugin.json`. Сервер `qlik` БЕЗ
  пина версии (`uvx qlik-sense-mcp-server --stdio`) — `uvx` сам резолвит
  последний PyPI-релиз при каждом запуске, авто-обновление MCP для Codex
  без хука-бампера пина (в отличие от Cursor 0.15.0).
- docs: пересверка 27.08.2026 (developers.openai.com/codex/plugins/build,
  learn.chatgpt.com/docs/hooks, codex.danielvaughan.com) ОПРОВЕРГАЕТ
  запись 0.7.0 «Codex не читает MCP-конфиг из плагина вообще» — документация
  прямо описывает поле `mcpServers` → `.mcp.json`. Не знаем, появилось ли
  это после 19.08.2026 или было пропущено тогда. Также нашли: `hooks/
  hooks.json` у Codex авто-обнаруживается так же, как у Cursor (`./hooks/
  hooks.json` без явного поля `hooks` в `plugin.json`), но СХЕМА другая —
  события `SessionStart`/`SessionEnd`/... (НЕ `workspaceOpen`, это
  Cursor-специфика), вложенная структура `matcher`+`hooks[]` с
  `type: "command"`. Кастомный хук для Codex (аналог 0.15.0) НЕ добавлен —
  по одним поисковым сниппетам (без прямого подтверждения в первичных
  доках) git-маркетплейсы Codex и так обновляются best-effort сами
  (`git ls-remote` против сохранённой ревизии, триггер — старт плагина/
  `plugin list`); риск, что самодельный git-хук поверх директории, которой
  и так управляет сам Codex, будет с ней конфликтовать — не оценён.
  ⚠️ НИЧЕГО из этой записи не проверено живым Codex CLI (нет доступа в
  этой сессии) — статус "живьём подтверждено" не выдаётся нигде, только
  свежее прочтение документации + план/пуш кода.

## 0.15.0

- cursor: плагин сам себя обновляет с GitHub. `hooks/hooks.json`
  (workspaceOpen + sessionStart) клонирует или `git fetch`+`reset --hard`
  `~/.cursor/plugins/local/qlik-mcp-toolkit` на origin/main и сверяет пин
  `qlik-sense-mcp-server` в `~/.cursor/mcp.json` с PyPI. Маркетплейсный
  снимок Cursor не переписывается (клиент его пинит) — хук держит рядом
  живой клон и отдаёт его в `pluginPaths`. Не проверено живым
  перезапуском Cursor у клиента после push — статус "живьём подтверждено"
  не выдаётся.

## 0.14.0

- feature (по просьбе пользователя 26.08.2026): `qlik-mcp-analysis` теперь
  логирует КАЖДЫЙ вопрос-ответ через MCP — новый скрипт
  `scripts/log_interaction.py` (`--start`/`--finish`), два новых шага 0/14
  workflow в `SKILL.md`. Формат — JSON Lines, один файл в день
  (`Report-MCP/YYYY-MM-DD.jsonl`: `ts`/`question`/`answer`/`app`/
  `duration_ms`), строго дописыванием в конец файла — не читает и не
  парсит существующий файл, поэтому не замедляет обычную работу MCP.
  Путь — `$QLIK_MCP_TOOLKIT_HOME/Report-MCP` (по умолчанию
  `~/.qlik-mcp-toolkit/`, патч в PATCHES как у app_cache.py/
  session_store.py) — у КАЖДОГО пользователя плагина лог ложится в ЕГО
  собственный домашний каталог на его машине, а не куда-либо ещё. Цель —
  сырьё для дальнейшей доработки скиллов/MCP (не пользовательский
  worklog). Не проверено живым MCP-вызовом конца в конец (проверен только
  сам скрипт изолированно) — статус "живьём подтверждено" не выдаётся.

## 0.13.0

- fix (по живой обратной связи пользователя 24.08.2026): убран корневой
  `mcp.json` из генерируемого набора (`OBSOLETE_FILES` чистит его из
  существующих рабочих копий). Раньше Cursor подхватывал этот файл
  автоматически при установке плагина и регистрировал СВОЙ сервер `qlik`
  с плейсхолдерами `${QLIK_SERVER_URL}`/`${QLIK_JWT_TOKEN}` — Cursor их
  ничем не резолвит (не читает ни переменные окружения ОС, ни другой
  MCP-файл), так что пользователь после установки плагина был вынужден
  руками находить этот новый сервер в MCP-настройках и второй раз вписывать
  туда то, что у него, как правило, уже настроено отдельно (тот же сервер
  `qlik`, тот же токен). Теперь плагин для Cursor ставит ТОЛЬКО скиллы —
  MCP-регистрация окончательно вынесена в отдельный, разовый и НЕ
  зависящий от установки плагина шаг (one-click deeplink — для тех, у
  кого сервера ещё нет; у кого уже есть — просто используется как есть).
  Тот же принцип, что уже применялся к Codex CLI в 0.7.0 по структурной
  необходимости — здесь применён к Cursor уже как осознанное решение,
  не вынужденное. `.mcp.json` для Claude Code НЕ трогали — там иной,
  live-подтверждённый флоу без замеченного конфликта.
- docs: README.md "Cursor" переписан на двухшаговый порядок (сначала MCP,
  потом плагин); `references/architecture.md` — обновить при следующем
  запуске тулкита.
  ⚠️ Не проверено живым переустановлением плагина в Cursor после правки
  (нет доступа к Cursor GUI в этой сессии) — статус "живьём подтверждено"
  не выдаётся, только план+push кода.

## 0.12.0

- cursor: один плагин ставит все три скилла и пин MCP. Клиентам
  достаточно клонировать репозиторий в `~/.cursor/plugins/local/qlik-mcp-toolkit`
  (Windows: `%USERPROFILE%\.cursor\plugins\local\qlik-mcp-toolkit`) и
  прописать `QLIK_SERVER_URL`/`QLIK_JWT_TOKEN`. Это штатный путь Cursor
  для локальных плагинов — не зависит от Team Marketplace / Import from Repo.
- cursor: `.cursor-plugin/plugin.json` дополнен `homepage`/`repository`/
  `category`/`tags`/`rules` по образцу официального create-plugin.
  Описание больше не говорит «для Claude Code» — плагин общий.
- cursor: добавлено `rules/qlik-mcp.mdc` (`alwaysApply: true`) — после
  установки агент сам берёт qlik-mcp-analysis / data-access / session-context,
  клиенту не нужно подключать скиллы по одному.

## 0.11.1

- fix: 0.11.0 сняло `.cursor-plugin/marketplace.json` из
  генерируемого набора, но не удалило сам файл из рабочей копии —
  bootstrap.py пишет только то, что есть в `manifests{}` этого прогона, и
  не чистит то, что раньше писал прежний прогон. Файл остался лежать в
  первом push 0.11.0 (проверено сразу после — `.cursor-plugin/
  marketplace.json` был всё ещё на месте). Добавлен `OBSOLETE_FILES` —
  явный список путей на unlink после записи manifests{}.

## 0.11.0

- fix: `.cursor-plugin/marketplace.json` убран. Источник — официальный
  `cursor/plugin-template` (github.com/cursor/plugin-template, README
  сверен 20.08.2026 по прямой просьбе пользователя): для single-plugin
  репозитория шаблон явно требует держать contents на корне, ОДИН
  `.cursor-plugin/plugin.json` и убрать `.cursor-plugin/marketplace.json`
  (тот только для multi-plugin репо). Этот репозиторий — ровно
  single-plugin (skills/ и mcp.json на корне, не под `plugins/*/`), так
  что 0.9.0 держал marketplace.json "на всякий случай" ошибочно — теперь
  правка по прямому указанию из официального шаблона, а не по
  предположению. `.cursor-plugin/plugin.json` остаётся единственным
  манифестом Cursor. Не отменяет открытый вопрос 0.10.0 (план
  Free/Pro/Teams и реальный путь установки в UI) — тот всё ещё не
  подтверждён живьём.

## 0.10.0

- fix: живьём (личный + корпоративный Teams-аккаунт, 19.08.2026) "Team
  Marketplace / Import from Repo" НЕ нашлась в текущем Cursor UI вообще —
  ни кнопки Import, ни поля под ссылку под "Add". Доки cursor.com,
  видимо, устарели/расходятся с реальным UI (тот же класс проблемы, что
  был у Codex в 0.7.0). Вместо неё в README.md — два независимых от плана
  механизма, найденных через docs.cursor.com напрямую: (1) официальный
  one-click MCP deeplink (`cursor://anysphere.cursor-deeplink/mcp/install`,
  cursor.com/docs/mcp/install-links, `cursor_mcp_deeplink()` в
  bootstrap.py генерирует его из `mcp_servers_block()`); (2) skills —
  Customize → Rules → Add Rule → "Remote Rule (GitHub)"
  (cursor.com/docs/skills). Ни один из двух путей НЕ подтверждён живьём
  (нет доступа к Cursor GUI) — это лучшая находка по докам на сегодня,
  не гарантия.

## 0.9.0

- fix: добавлен `.cursor-plugin/plugin.json` на корне репозитория —
  cursor.com/docs/reference/plugins (сверено 19.08.2026) говорит, что
  single-plugin репо должен иметь СВОЙ `.cursor-plugin/plugin.json`
  (name/skills/mcp.json auto-discovered), а `.cursor-plugin/marketplace.json`
  — только для multi-plugin репо. Раньше был только `marketplace.json`,
  обёрткой указывающий на корневой Agent-Plugins `plugin.json` — по
  Codex-прецеденту 19.08.2026 (см. 0.7.0) это ровно тот класс ошибки,
  который один раз уже сломал распознавание плагина. `marketplace.json`
  оставлен (докам не противоречит, живьём вреда не подтверждено).
  MCP-конфиг отдельно объявлять не пришлось — `mcp.json` на корне плагина
  Cursor "discovers automatically" (та же схема `{mcpServers: {...}}`,
  что и Claude Code, подтверждено сверкой с `cursor/plugin-template`).
  ⚠️ Не проверено живьём (нет Cursor-аккаунта с Teams/Enterprise планом
  под рукой) — доки прямо говорят: "Team marketplaces are available on
  Teams and Enterprise plans", на Free/Pro Import from Repo недоступен
  вообще, это не чинится правками в этом репозитории.

## 0.8.0

- security: репозиторий публичный с момента создания (12.08.2026) —
  обнаружено 19.08.2026, что структурные фрагменты одного конкретного
  Qlik-приложения (2 реальных app-GUID, конкретное имя тестового
  приложения и имя приложения из cross-app примера в `qlik-mcp-analysis`)
  утекли в опубликованные скиллы. Секретов/токенов в утечке НЕ было —
  дизайн с самого начала ссылается на `${QLIK_SERVER_URL}`/
  `${QLIK_JWT_TOKEN}` из окружения клиента, не хранит их в репо. Заменены
  на плейсхолдеры (`<app_name>`/`<app_id>` и т.п.) во всех трёх Work-
  скиллах — история старых коммитов (0.1.0-0.7.0) не переписывалась
  (публичная, уже расходилась дальше — force-push сломал бы существующие
  клоны, включая тот, что уже стоит в Cursor), только текущий HEAD чист.
  business-термины (GGR, VIP-статус и т.п.) НЕ считаются утечкой и не
  трогались — это отраслевая терминология, не идентификатор конкретного
  приложения/клиента (тот же подход, что в `check_genericity.py` у
  `qlik-analysis-accelerator`).

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
