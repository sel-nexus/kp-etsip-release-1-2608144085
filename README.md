# KP ETSIP — Release 1 Platform Foundation

Internal portfolio and application inventory with local JWT sessions, six-role authorization, profile preferences, administration, searchable audits, executive metrics and CSV reports. Built with FastAPI/Python/Pydantic v2 and PyMongo AsyncMongoClient, plus Vite/React/TypeScript/Tailwind. The Vital Integrity design tokens and Public Sans are shared centrally.

## Run locally

Requires Python 3.12, Node 22+, and a running MongoDB 8-compatible endpoint. MongoDB is external; the application never substitutes process-local state.

1. Copy `backend/.env.example` to `backend/.env`. Configure `MONGODB_URI` without a database path and select `MONGODB_DB` separately. Replace `JWT_SECRET` with a generated signing key of at least 32 characters; sample keys are rejected. Set actual `SEED_ADMIN_PASSWORD` and `SEED_DEMO_PASSWORD` through your secure environment. Example passwords are deliberately rejected.
2. Create a virtual environment outside this repository: `python3 -m venv --copies "$HOME/venvs/app"`. Install: `"$HOME/venvs/app/bin/python" -m pip install -r backend/requirements.txt`.
3. In `backend/`, initialize demo data: `"$HOME/venvs/app/bin/python" -m api.seed.runner`. Alternatively enable `SEED_ON_STARTUP=true` with valid seed credentials. Defaults leave startup seeding disabled. Index initialization occurs in lifespan and the CLI; failures prevent readiness.
4. In `backend/`, start `"$HOME/venvs/app/bin/python" -m uvicorn api.main:app --host 0.0.0.0 --port 8000`. Supply deployment host/port via your process command or `API_HOST`/`API_PORT` for the container entrypoint.
5. Copy `frontend/.env.example` to `frontend/.env`. In `frontend/`, run `npm ci --no-bin-links`, then `node node_modules/vite/bin/vite.js --host 0.0.0.0`. The development proxy targets the configured API; the deployed SPA uses same-origin `/api`.

The seed creates six users, six roles, three portfolios and ten linked applications. Administrator email is `admin@ketsip.local`; other local demo emails are `executive`, `leader`, `engineer`, `auditor`, and `readonly` at `ketsip.local`. Passwords are the operator-configured seed values, never printed or shipped as defaults. The seeded administrator must change password before protected inventory use. Repeated seed preserves existing hashes, gate state, role edits and inventory.

## Containers and deployment

`docker-compose.yml` builds independent backend and nginx frontend images. Supply an external secured MongoDB endpoint with `MONGODB_URI`; local Compose defaults to `host.docker.internal:27017` via host-gateway, not container-local localhost. For local-only verification a guest Mongo listener on port 27029 was used:

`MONGODB_URI=mongodb://host.docker.internal:27029 docker compose up --build -d`

That command passed; API service was healthy, frontend `/` served successfully, and frontend `/api/health` returned `{"status":"ok"}`. A host-local Mongo listener must be reachable from the bridge; production should use a secured provider/network endpoint instead. Keep real secrets in per-tier environment files or secure runtime configuration, never in git/images/frontend bundles. The API image runs as a non-root user. Nginx uses history fallback for deep links and proxies `/api` to `API_UPSTREAM` (Compose service name backend). Backend readiness route is `/api/health`; it is an operational public exception and returns non-2xx when its required DB is unavailable. OpenAPI is available at `/docs` and `/openapi.json`.

AWS ECS/ECR/ALB/CloudFront deployment is downstream, not executed by this Development stage. MongoDB provisioning, TLS/network access, backups, retention and recovery ownership are external prerequisites. No availability, HA/DR or multi-region promise is made.

## Permission and data rules

| Role | Maximum permissions | Portfolio visibility |
|---|---|---|
| Administrator | all six actions; inventory/user/role management | empty assignment means all |
| Executive | view/export | empty assignment means all |
| Portfolio Leader | view/export, application create/edit | assigned only; empty means none |
| Engineer | application view/create/edit/export | assigned only; empty means none |
| Auditor | view/audit/export, no administration/mutation | empty assignment means all |
| Read Only | view only | assigned only; empty means none |

Stored permissions can be reduced/restored only within immutable role ceilings. Current account status, role permissions and assignments are reloaded per protected request, not trusted from stale token claims. Lists, direct IDs, dashboard and CSV apply Mongo scope predicates. Hidden direct resources return 404. User deletion deactivates. Portfolio deletion rejects application/user references; application deletion is Administrator-only. Roles are a closed set; ensure creates only a missing supported baseline and does not reset edited permissions.

Passwords use off-thread passlib bcrypt with pinned bcrypt 4.0.1. JWTs expire in approximately eight hours. Logout discards browser session state but does not implement server token revocation. Browser localStorage token handling follows the specified release contract; operational CSP/TLS controls and XSS defense remain important.

Body validation uses strict DTOs and forbids extras. Responses expose safe allowlists, not hashes. Field errors expose declared field names and generic messages, never submitted secrets. Unknown-account failed login events use null userId/entityId and `Unknown account`; incomplete known accounts retain their real ID and a safe actor snapshot.

Sensitive writes and exports require durable audit evidence before success. On standalone Mongo an entity write may precede audit failure: `AUDIT_WRITE_FAILED` returns 503 with correlation information and does **not** claim rollback. Operators must reconcile that persisted partial action. Mongo-backed reference reservations and deletion intents prevent racing application/user assignment writes from orphaning portfolios. Crashed or ambiguous operations retain conservative `_applicationReservations` or `_applicationDeleting` blockers; inspect actual records and audit evidence before manually clearing only the affected operation's blockers. They never expire automatically.

## Metrics and exports

Quality, health and automation metrics are arithmetic means rounded half-up for nonnegative scores. Empty averages are null; counts/sums are zero. Critical defects sum stored counts; applications at risk count `High`. `totalApplications` uses filtered visible applications. The approved `totalPortfolios` counts **all visible portfolio documents independently of every dashboard filter**, including empty portfolios. Comparisons represent only filtered visible application groups. Portfolio quality/count are derived, never stored.

CSV is the only export format. Application inventory/reports and portfolio/audit reports use equivalent authorized filters, export all matching rows rather than just the current page, quote commas/quotes/newlines, render null as empty and prefix spreadsheet formula-leading cells with a single quote. Generation uses bounded Mongo batches and transient spooling; no download is released if its required audit fails.

## Tests and evidence

- Backend: in `backend/`, `PYTHONPATH=. "$HOME/venvs/app/bin/python" -m pytest -q`. Uses unique disposable real Mongo databases; ensure your configured DB endpoint is running. All 774 tests passed, including three cross-feature chains and two measured/negative load cases. A later targeted application API run after the final message correction passed 28 tests.
- Frontend: in `frontend/`, `node node_modules/vitest/vitest.mjs run`: 141 passed.
- Build: `npm run build` uses direct Node TypeScript and Vite entrypoints; passed. The independent Docker production build also passed.
- Browser: `node node_modules/@playwright/test/cli.js test`. Configure `E2E_MONGODB_URI` and a disposable `E2E_MONGODB_DB` beginning `etsip_e2e_`; the frontend env example names all browser URLs. Playwright installs Chromium using its Node CLI. The config starts real backend/frontend servers and serializes workers. All 48 desktop/mobile journeys have passing final results: initial 40 passed; targeted corrections passed application/users; final report suite passed all twelve. Passing unaffected specs were not rerun.
- Independent test critic: final round 4 PASS, score 1.00, 52 checks, zero high failures.
- `test_report.yaml`, `ui-preflight.txt`, screenshots and `backend/performance-evidence.json` contain Development evidence. The 300-row, twenty-reader in-process list/dashboard pair measured p50 0.178s and p95 0.188s with zero errors and an indexed plan. This is not an external HTTP throughput/SLA result. The proposed 30-minute steady and 2x stress load were **not executed**.

Known maintenance warnings: passlib's deprecated crypt import; two moderate React Router 6 advisories (SSR hydration/redirect scenarios), no SSR or untrusted navigation destinations used here; development-mode bundle-size warning over 500kB. Container production bundle was approximately 239kB. Dependency upgrades require a reviewed compatibility change, not automatic `npm audit fix --force`.

Release scope excludes SSO, synchronization, test execution/repositories, release governance, AI, notifications, non-CSV exports and production infrastructure monitoring.
