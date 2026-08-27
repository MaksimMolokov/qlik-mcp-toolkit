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
- **Cursor**: плагин ставит ТОЛЬКО скиллы — с 0.13.0 он больше не несёт
  свой `mcp.json` и не регистрирует сервер `qlik` сам (раньше это создавало
  дублирующий сервер с плейсхолдерами `${QLIK_SERVER_URL}`/
  `${QLIK_JWT_TOKEN}`, которые Cursor ничем не резолвит — пользователь был
  вынужден руками находить этот сервер и второй раз вписывать туда то, что
  у него, как правило, уже настроено). Порядок действий:
  1. Сначала убедиться, что в Cursor уже есть рабочий MCP-сервер `qlik`
     (Settings → MCP). Если его ещё нет — one-click:
     [Add qlik MCP server](cursor://anysphere.cursor-deeplink/mcp/install?name=qlik&config=eyJjb21tYW5kIjogInV2eCIsICJhcmdzIjogWyJxbGlrLXNlbnNlLW1jcC1zZXJ2ZXI9PTIuMC4yIiwgIi0tc3RkaW8iXSwgImVudiI6IHsiUUxJS19TRVJWRVJfVVJMIjogIllPVVJfUUxJS19TRVJWRVJfVVJMIiwgIlFMSUtfSldUX1RPS0VOIjogIllPVVJfUUxJS19KV1RfVE9LRU4ifX0=), затем вписать свои реальные
     `QLIK_SERVER_URL`/`QLIK_JWT_TOKEN` вместо плейсхолдеров.
  2. Только потом установить плагин со скиллами — склонировать
     `https://github.com/MaksimMolokov/qlik-mcp-toolkit` в
     `~/.cursor/plugins/local/qlik-mcp-toolkit`
     (Windows: `git clone https://github.com/MaksimMolokov/qlik-mcp-toolkit "%USERPROFILE%\.cursor\plugins\local\qlik-mcp-toolkit"`),
     перезапустить Cursor, включить плагин.
     Дальше плагин обновляется сам: хук `hooks/` при перезапуске Cursor /
     новом чате агента клонирует или подтягивает этот каталог с GitHub
     (`origin/main`) и сверяет пин MCP в `~/.cursor/mcp.json` с PyPI.
  У кого сервер `qlik` уже настроен (например, тем же способом, что и для
  Claude Code, или через `mcp-qlik`) — шаг 1 просто пропускается, плагин
  использует то, что уже есть, без повторного ввода токена.
  После этого агент сразу видит `qlik-mcp-analysis`,
  `qlik-mcp-data-access` и `qlik-mcp-session-context`.
- **Codex CLI** (0.140.0+): `codex plugin marketplace add MaksimMolokov/qlik-mcp-toolkit` →
  `codex plugin add qlik-mcp-toolkit@qlik-mcp-toolkit-marketplace`. Ставит
  скиллы И MCP-сервер `qlik` (`plugins/qlik-mcp-toolkit/.mcp.json`, поле
  `mcpServers` в `.codex-plugin/plugin.json`) — БЕЗ пина версии
  (`uvx qlik-sense-mcp-server --stdio`), так что `uvx` сам резолвит
  последний релиз PyPI при каждом запуске: авто-обновление MCP для Codex
  без хука, который бы двигал пин (в отличие от Cursor). Обновление
  скиллов — по документации OpenAI (developers.openai.com/codex/plugins,
  сверено 27.08.2026) git-маркетплейсы обновляются best-effort сами при
  старте/`plugin list` (`git ls-remote` против сохранённой ревизии); если
  на практике не подтянет — ручной фолбэк `codex plugin marketplace
  upgrade` точно работает (live-подтверждено 19.08.2026).
  ⚠️ Всё, что касается `mcpServers`-поля и авто-апгрейда маркетплейса —
  ПЕРЕСМОТРЕНО 27.08.2026 по документации, НЕ живым тестом (нет доступа к
  Codex CLI в этой сессии) — до 27.08.2026 здесь стояло «Codex вообще не
  читает MCP из плагина», это утверждение было основано на живом тесте
  19.08.2026 и теперь под вопросом. Если что-то из этого не сработает —
  ручная настройка остаётся: `codex mcp add`/правка `~/.codex/config.toml`
  `[mcp_servers.qlik]`.

Версия MCP-сервера для Claude Code/Cursor обновляется ТОЛЬКО через гейт
`pipeline/promote.py` этого скилла (см. `references/architecture.md`) —
не редактируйте `mcp.json`/`.mcp.json` руками.
