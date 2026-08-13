# qlik-mcp-toolkit

Общий дистрибутив qlik-mcp-скиллов (семантика приложения → hypercube →
валидация → population-lock для уточнений) + пин версии MCP-сервера
`qlik-sense-mcp-server==2.0.0`. Один и тот же `skills/` читают Claude Code, Cursor и Codex
CLI — расходятся только тонкие манифесты (`.claude-plugin/` для Claude
Code, корневой `plugin.json`/`mcp.json` для Cursor и Codex, стандарт
Agent Plugins).

Источник истины и живая отладка — `Work\MCP qlik\.claude\skills\qlik-mcp-*`
в рабочем репозитории; сюда попадает через `qlik-mcp-toolkit/scripts/bootstrap.py`.
Секреты (`QLIK_SERVER_URL`, `QLIK_JWT_TOKEN`) не хранятся здесь — задаются
в окружении клиента.

## Подключение

- **Claude Code**: `claude plugin marketplace add <url-этого-репо>`, затем
  включить плагин; тумблер auto-update — в `/plugin` → Marketplaces.
- **Cursor**: импортировать репозиторий в Marketplace (личный или Team),
  включить Auto Refresh (нужен Cursor GitHub App).
- **Codex CLI**: зарегистрировать как источник portable Agent Plugins
  (v0.147.0+) — команда регистрации кастомного каталога уточняется.

Версия MCP-сервера обновляется только через `bootstrap.py` этого скилла
(гейт на regression — см. `references/architecture.md`, раздел "Дальше",
пока не реализован), не редактируйте `mcp.json`/`.mcp.json` руками.
