# ERPNext (Ukrainian Edition)

ERPNext v15.96.1 with Ukrainian translations and custom manufacturing doctypes.

## Prerequisites

- Docker + Docker Compose

## Quick Start

```bash
./deploy init      # Build image, start containers, create site (~3 min)
```

Open http://localhost:8080 (Administrator / admin)

## Commands

| Command | Description |
|---|---|
| `./deploy init` | First-time setup: build image, start all services, create site |
| `./deploy start` | Start stopped containers |
| `./deploy stop` | Stop containers (data preserved) |
| `./deploy migrate` | Deploy code changes: copies files, reloads gunicorn, runs migrations |
| `./deploy setup-prod` | Enable production mode (disables destructive commands) |
| `./deploy setup-dev` | Enable dev mode (all commands available) |
| `./deploy nuke` | Remove all containers and data (dev only) |
| `./deploy destroy` | Same as nuke (dev only) |

## Deploy Code Changes

After editing files locally:

```bash
./deploy migrate
```

This copies custom doctypes into the container, gracefully reloads gunicorn workers, runs `bench migrate`, and clears cache. No downtime.

## Production Safety

```bash
./deploy setup-prod
```

In production mode, `nuke` and `destroy` are disabled to prevent accidental data loss.

## Custom Additions

- Ukrainian translations (CSV + PO/MO)
- Workplace DocType (worker portal with barcode scanning)
- Manufacturing guide: see `docs/manufacturing-guide.md`
