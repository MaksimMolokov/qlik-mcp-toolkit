# qlik-mcp-toolkit

Общий дистрибутив qlik-mcp-скиллов (семантика приложения → hypercube →
валидация → population-lock для уточнений) + пин версии MCP-сервера
`qlik-sense-mcp-server==2.3.0` (для Claude Code/Cursor — см. ниже про Codex). Один и тот же
`skills/` читают все три клиента — расходятся только тонкие манифесты:
`.claude-plugin/` (Claude Code), `.cursor-plugin/` (Cursor), `.agents/
plugins/` + `.codex-plugin/` (Codex CLI, свой проприетарный формат, НЕ
Agent Plugins spec — живьём проверено 19.08.2026), плюс корневой
`plugin.json`/`mcp.json` по спеке Agent Plugins для прочих клиентов.

Источник истины и живая отладка — `Work\.claude\skills\qlik-mcp-*`
в рабочем репозитории; сюда попадает через `qlik-mcp-toolkit/scripts/bootstrap.py`.
Секреты (`QLIK_SERVER_URL`, `QLIK_JWT_TOKEN`) не хранятся здесь — задаются
в окружении клиента.

## Логирование вопрос-ответ

`qlik-mcp-analysis` логирует каждое взаимодействие через MCP — вопрос,
итоговый ответ, приложение-источник и время выполнения — в
`$QLIK_MCP_TOOLKIT_HOME/Report-MCP/YYYY-MM-DD.jsonl` (по умолчанию
`~/.qlik-mcp-toolkit/Report-MCP/`, локально у КАЖДОГО пользователя плагина
на его машине). Дописывание в конец файла, без перечитывания — не
замедляет обычную работу MCP. Цель — сырьё для дальнейшей доработки
скиллов/MCP, не пользовательский отчёт.

## Подключение

- **Claude Code**: `claude plugin marketplace add MaksimMolokov/qlik-mcp-toolkit` →
  `claude plugin install qlik-mcp-toolkit@qlik-mcp-toolkit-marketplace`.
  Скиллы И пин MCP-сервера (`.mcp.json`) ставятся одним плагином, дальше
  auto-update (`autoUpdatesChannel: "latest"` в settings.json, либо тумблер
  в `/plugin` → Marketplaces) подтягивает новые версии сам — руками ничего
  обновлять не нужно. Live-подтверждено 19.08.2026 (`claude mcp list` →
  `qlik: ... - ✔ Connected`).
- **Cursor**: Git **не нужен** — ни для установки, ни для обновлений.
  Плагин ставит скиллы; MCP-сервер `qlik` живёт отдельно в `~/.cursor/mcp.json`
  (с 0.13.0 плагин сам его не регистрирует, чтобы не плодить дубль с
  плейсхолдерами `${QLIK_SERVER_URL}` / `${QLIK_JWT_TOKEN}`).
  1. Если MCP `qlik` ещё нет — one-click
     [Add qlik MCP server](cursor://anysphere.cursor-deeplink/mcp/install?name=qlik&config=eyJjb21tYW5kIjogInV2eCIsICJhcmdzIjogWyJxbGlrLXNlbnNlLW1jcC1zZXJ2ZXI9PTIuMy4wIiwgIi0tc3RkaW8iXSwgImVudiI6IHsiUUxJS19TRVJWRVJfVVJMIjogIllPVVJfUUxJS19TRVJWRVJfVVJMIiwgIlFMSUtfSldUX1RPS0VOIjogIllPVVJfUUxJS19KV1RfVE9LRU4ifX0=),
     затем вписать реальные `QLIK_SERVER_URL` / `QLIK_JWT_TOKEN`.
     У кого сервер уже настроен — шаг пропускается.
  2. Плагин со скиллами, **без Git**, в PowerShell:
     `irm https://raw.githubusercontent.com/MaksimMolokov/qlik-mcp-toolkit/main/hooks/install-cursor.ps1 | iex`
     Скрипт кладёт файлы в `~/.cursor/plugins/local/qlik-mcp-toolkit` (без
     `.git` — иначе Cursor делает `spawn git` и плагин не грузится),
     регистрирует хуки и записывает пин MCP. Полностью закрыть Cursor,
     открыть снова, включить плагин в Settings → Plugins.
     Дальше на каждый `sessionStart` хук сам подтягивает скиллы и MCP:
     GitHub по HTTPS (zip), либо уже скачанный кэш маркетплейса. Git не
     требуется. Пин `qlik-sense-mcp-server==<первые три цифры toolkit>`
     пишется в `~/.cursor/mcp.json` (голый пакет, старый пин, или запуск
     через `uv tool`). После смены пина — перезапуск MCP `qlik`.
  После этого агент видит `qlik-mcp-analysis`,
  `qlik-mcp-data-access` и `qlik-mcp-session-context`.
- **Codex CLI** (0.140.0+): `codex plugin marketplace add MaksimMolokov/qlik-mcp-toolkit` →
  `codex plugin add qlik-mcp-toolkit@qlik-mcp-toolkit-marketplace`. Ставит
  скиллы И MCP-сервер `qlik` (`plugins/qlik-mcp-toolkit/.mcp.json`, поле
  `mcpServers` в `.codex-plugin/plugin.json`) с тем же пином, что и
  Cursor (`uvx qlik-sense-mcp-server==2.3.0 --stdio`). Голый пакет без
  версии специально больше не используется: `uvx` кэширует резолв и
  оставляет коллег на старом MCP при уже новом toolkit. Хуки Codex
  (`plugins/qlik-mcp-toolkit/hooks/`, событие `SessionStart`):
  1. копируют личные `QLIK_SERVER_URL`/`QLIK_JWT_TOKEN` из
     `%USERPROFILE%\.codex\config.toml` секции `[mcp_servers.qlik.env]`
     в `.mcp.json` плагина;
  2. запускают `codex plugin marketplace upgrade`, чтобы подтянуть
     новую версию тулкита.
  Один раз доверь хуки плагина через `/hooks` в Codex — без этого
  клиент их пропускает. Если маркетплейс сам не обновится, тот же
  `codex plugin marketplace upgrade` можно запустить вручную.

Версия MCP-сервера для Claude Code/Cursor обновляется ТОЛЬКО через гейт
`pipeline/promote.py` этого скилла (см. `references/architecture.md`) —
не редактируйте `mcp.json`/`.mcp.json` руками.
