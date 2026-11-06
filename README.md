# mero (backend)

Realtime backend for mero, a small infinite-whiteboard app. FastAPI plus one
websocket per open board. The frontend is in `mero_frontend`.

- Accounts: username and password (scrypt hash), with a signed bearer token that lasts a year.
- Workspaces hold any number of boards. People join a workspace through its invite link.
- Live boards are held in memory. Strokes are relayed to the other clients as they arrive and written to the database in batches behind the scenes. The hot path never waits on the database.
- The protocol is documented at the top of [app/services/room_service.py](app/services/room_service.py).

**This app must run as exactly one process** (one uvicorn worker, one
replica), because a board's room lives in that process. The Dockerfile and
Deployment are already set up this way. The Deployment also uses `Recreate`,
so a rollout never runs two pods at once.

## Run locally

```bash
uv venv .venv && uv pip install -p .venv/bin/python -r requirements.txt
cp .env.example .env            # optional; SQLite + port 1184 by default
.venv/bin/python main.py        # http://localhost:1184
```

With no `DATABASE_URL` set, it uses `./mero.db` (SQLite).

## Layout

Same layout as the other backends:

```
main.py                     app, logging, lifespan, router registration
app/api/                    *_routes.py, dependencies.py (current user), schemas.py
app/db/database.py          async engine, session, init_db() (runs migrations)
app/db/models.py            tables
app/services/               auth, workspace, board; room_service.py (live boards and
                            the wire protocol), persist_service.py (write-behind)
app/enums.py                websocket close codes
alembic/                    migrations
```

The engine is async (asyncpg / aiosqlite). Routes use a session. Rooms and
the persister run plain statements on the engine, so a stroke never pays for
ORM bookkeeping.

## Migrations

The app runs `alembic upgrade head` on startup, so a deploy that adds a
migration applies it with no separate step. A database created before
migrations existed (tables, but no `alembic_version`) is stamped at `0001`
first, which matches that schema exactly.

```bash
.venv/bin/alembic revision --autogenerate -m "add something"   # after editing models.py
.venv/bin/alembic upgrade head                                  # or just start the app
.venv/bin/alembic check                                         # models and migrations agree?
```

Like the app, the CLI reads `DATABASE_URL` from the environment or `.env`.

## Deploy (Argo CD, same flow as the other apps)

1. **Database.** Create a `mero` database and user on the cluster Postgres. Migrations run on the first start.
2. **Vault.** Write the env to `apps/mero/mero/env`:
   ```bash
   vault kv put apps/mero/mero/env \
     DATABASE_URL="postgresql://mero:<password>@postgres.postgres.svc.cluster.local:5432/mero" \
     SECRET_KEY="$(openssl rand -hex 32)" \
     CORS_ORIGINS="*" \
     LOG_LEVEL=INFO
   ```
   A plain `postgresql://` URL is fine. The app switches it to asyncpg itself.
3. **Gitea secret.** The repo needs `REGISTRY_TOKEN`, as amarathon does. Each push to `main` builds the image, pushes it, and bumps `k8s/overlays/gitea/kustomization.yaml`.
4. **Argo.** `kubectl apply -f k8s/base/argocd-app.yaml` (once).
5. **DNS.** Point `mero.krishnarajthadesar.in` at NodePort **32050**. Leave it off API Get Away: the browser talks to this host directly, websocket included. Cloudflare proxies websockets without any setup. The client pings every 5 s, so Cloudflare's 100 s idle timeout never fires.

Health: `/health`, `/ready`.
