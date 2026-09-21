## MCP server (`mcp-server/`)

The ERPNext MCP server (TypeScript, stdio) lives **in this repo** at `mcp-server/` — moved here from the standalone `egdw-xxxyo/erpnext-mcp-server` repo so tool changes ship with the ERPNext code they call.

- Source: `mcp-server/src/` (`index.ts`, `labelTemplate.ts`, `scripts.ts`), docs in `mcp-server/docs/`.
- Build: `cd mcp-server && npm ci && npm run build` → `mcp-server/build/index.js` (gitignored by `mcp-server/.gitignore`).
- `.mcp.json` (gitignored, per machine) points `erp-local` / `erp-dev` / `erp-prod` at `<repo>/mcp-server/build/index.js`, each with its own `ERPNEXT_URL` / `ERPNEXT_API_KEY` / `ERPNEXT_API_SECRET`.
- After changing tool code: rebuild, then restart the MCP connection (`/mcp` reconnect or new session) — Claude does not pick up a new build in-flight.
- The old standalone repo is superseded; do not push tool changes there.
