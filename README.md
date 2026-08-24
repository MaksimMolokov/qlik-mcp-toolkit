# qlik-mcp-toolkit

Общий дистрибутив qlik-mcp-скиллов (семантика приложения → hypercube →
валидация → population-lock для уточнений) + пин версии MCP-сервера
`qlik-sense-mcp-server==2.0.2` (для Claude Code/Cursor — см. ниже про Codex). Один и тот же
`skills/` читают все три клиента — расходятся только тонкие манифесты:
`.claude-plugin/` (Claude Code), `.cursor-plugin/` (Cursor), `.agents/
plugins/` + `.codex-plugin/` (Codex CLI, свой проприетарный формат, НЕ
Agent Plugins spec — живьём проверено 19.08.2026), плюс корневой
`plugin.json`/`mcp.json` по спеке Agent Plugins для прочих клиентов.

Источник истины и живая отладка — `Work\.claude\skills\qlik-mcp-*`
в рабочем репозитории; сюда попадает через `qlik-mcp-toolkit/scripts/bootstrap.py`.
Секреты (`QLIK_SERVER_URL`, `QLIK_JWT_TOKEN`) не хранятся здесь — задаются
в окружении клиента.

## Подключение

- **Claude Code**: `claude plugin marketplace add MaksimMolokov/qlik-mcp-toolkit` →
  `claude plugin install qlik-mcp-toolkit@qlik-mcp-toolkit-marketplace`.
  Скиллы И пин MCP-сервера (`.mcp.json`) ставятся одним плагином, дальше
  auto-update (`autoUpdatesChannel: "latest"` в settings.json, либо тумблер
  в `/plugin` → Marketplaces) подтягивает новые версии сам — руками ничего
  обновлять не нужно. Live-подтверждено 19.08.2026 (`claude mcp list` →
  `qlik: ... - ✔ Connected`).
- **Cursor**: один плагин ставит все скиллы и MCP. Клиентам сказать:
  «Установите `qlik-mcp-toolkit` — склонируйте
  `https://github.com/MaksimMolokov/qlik-mcp-toolkit` в
  `~/.cursor/plugins/local/qlik-mcp-toolkit`».
  Windows: `git clone https://github.com/MaksimMolokov/qlik-mcp-toolkit "%USERPROFILE%\.cursor\plugins\local\qlik-mcp-toolkit"`.
  Затем перезапустить Cursor, включить плагин и вписать свои
  `QLIK_SERVER_URL`/`QLIK_JWT_TOKEN` в MCP-сервер `qlik`.
  После этого агент сразу видит `qlik-mcp-analysis`,
  `qlik-mcp-data-access` и `qlik-mcp-session-context`.
  Запасной one-click только для MCP: [Add qlik MCP server](cursor://anysphere.cursor-deeplink/mcp/install?name=qlik&config=eyJjb21tYW5kIjogInV2eCIsICJhcmdzIjogWyJxbGlrLXNlbnNlLW1jcC1zZXJ2ZXI9PTIuMC4yIiwgIi0tc3RkaW8iXSwgImVudiI6IHsiUUxJS19TRVJWRVJfVVJMIjogIllPVVJfUUxJS19TRVJWRVJfVVJMIiwgIlFMSUtfSldUX1RPS0VOIjogIllPVVJfUUxJS19KV1RfVE9LRU4ifX0=)
  (если плагин ещё не подхватил `mcp.json`).
- **Codex CLI** (0.140.0+): `codex plugin marketplace add MaksimMolokov/qlik-mcp-toolkit` →
  `codex plugin add qlik-mcp-toolkit@qlik-mcp-toolkit-marketplace`. Ставит
  ТОЛЬКО скиллы — Codex не читает MCP-конфиг из плагина/маркетплейса
  вообще (ни `mcp.json`, ни `.mcp.json`), это отдельный слой. MCP-сервер —
  разовая ручная настройка через `codex mcp add` (или правка
  `~/.codex/config.toml`, секция `[mcp_servers.qlik]`), БЕЗ пина версии
  (`uvx qlik-sense-mcp-server --stdio`, без `==версия`) — это единственный
  способ получить действительно автообновляемую версию сервера в Codex,
  раз маркетплейс её не разносит. Live-подтверждено 19.08.2026.

Версия MCP-сервера для Claude Code/Cursor обновляется ТОЛЬКО через гейт
`pipeline/promote.py` этого скилла (см. `references/architecture.md`) —
не редактируйте `mcp.json`/`.mcp.json` руками.
