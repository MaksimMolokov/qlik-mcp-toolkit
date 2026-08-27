# Changelog

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
