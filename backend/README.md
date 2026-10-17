# TradeCheck backend: api-service and worker-service

FastAPI on Cloud Run. Implements the frozen contract in [BACKEND-SPEC.md](../BACKEND-SPEC.md) §5–7. The generated contract is in [contracts/openapi.yaml](../contracts/openapi.yaml).

**The system never files anything.** It produces findings. A licensed human decides on each one, and every decision is written to a hash-chained audit trail. A signed report can only be issued once every finding has a decision.

## Architecture

```
React SPA ──HTTPS──► api-service (Cloud Run, public)          ──► Cloud SQL Postgres 16
   │  PUT via signed URL           │ enqueue one task per stage    Cloud Storage (originals, page PNGs, reports)
   └──────────► Cloud Storage      ▼                               Cloud KMS (report signing, EC P-256)
                              Cloud Tasks ──OIDC──► worker-service (Cloud Run, internal)
                                                        │ OIDC
                                                        ▼
                                                   ai-service (AI teammate: Gemini / Gemma)
```

The pipeline runs `INGEST → CLASSIFY → EXTRACT → RECONCILE → EXPLAIN → READY`, one Cloud Task per stage:
- Each delivery is idempotent (the `job_runs` idempotency key), so a duplicate delivery does nothing.
- Partial success counts as success. A corrupt or password-protected file is recorded on that document, and the rest of the shipment is still checked.

### Deviations from BACKEND-SPEC §9+ (the contract is unchanged)

| Spec | Here | Why |
|---|---|---|
| Memorystore Redis for SSE fan-out | Postgres `LISTEN/NOTIFY`, plus a `pipeline_events` table for `Last-Event-ID` replay | Needs no VPC and adds no cost. Events are delivered to every api instance when the transaction commits. |
| PyMuPDF | pypdfium2 + pypdf | PyMuPDF is AGPL, and the contest licence grant rules out GPL/AGPL. |
| LibreOffice, Dockerfile | openpyxl + reportlab for XLSX; Cloud Run **source deploy** with buildpacks | No Docker is used anywhere. DOCX is not supported. |
| WeasyPrint | reportlab | Needs no system libraries under buildpacks. |
| Cloud SQL IAM database auth | Built-in DB user, with its password in Secret Manager | IAM users need a superuser grant step, which we skipped for time. |
| api timeout 60 s | 900 s | Keeps SSE streams from being cut. Clients still reconnect and poll. |
| api / worker as two codebases | One image, `SERVICE_ROLE=api\|worker` | Two services, one build. |

## Run locally (no Docker)

```bash
brew install postgresql@16 && brew services start postgresql@16
psql -d postgres -c "CREATE ROLE tradecheck LOGIN PASSWORD 'tradecheck' CREATEDB;"
psql -d postgres -c "CREATE DATABASE tradecheck OWNER tradecheck;" -c "CREATE DATABASE tradecheck_test OWNER tradecheck;"

cd backend
uv sync --python 3.12
uv run alembic upgrade head
uv run python samples/generate.py          # sample shipments in samples/out/
uv run uvicorn app.main:app --port 8080    # all dev modes are the defaults
uv run python scripts/smoke.py --scenario quantity_weight_conflict
uv run pytest                              # 28 tests against real Postgres
```

The defaults are all local modes: `AUTH_MODE=dev`, `AI_MODE=stub`, `TASKS_MODE=inline`, `STORAGE_MODE=local` and `SIGNING_MODE=local`. Production sets `firebase`, `http`, `cloudtasks`, `gcs` and `kms`. All settings are listed in [app/config.py](app/config.py).

## Deploy to GCP

```bash
PROJECT=tradeit-511910 ./infra/setup.sh     # once: APIs, service accounts, bucket+CORS, Cloud SQL, Tasks queue, KMS key
PROJECT=tradeit-511910 ./infra/deploy.sh    # worker → migrations job → api; prints the api URL
# when the AI service and Firebase are ready:
AI_MODE=http AI_SERVICE_URL=https://ai-service-....run.app AUTH_MODE=firebase \
  ALLOWED_ORIGINS=https://<frontend-origin> PROJECT=tradeit-511910 ./infra/deploy.sh
```

Grant the worker's service account `roles/run.invoker` on ai-service. Set `API_MIN_INSTANCES=1` on judging day so the first request doesn't hit a cold start.

## Notes for the frontend

- **Auth.** `AUTH_MODE=dev` needs no token. You can switch role with `X-Dev-Role: VIEWER|APPROVER|OWNER`. With Firebase, send `Authorization: Bearer <ID token>`. The `org_id` and `role` custom claims are set by `scripts/seed_org.py`.
- **Uploads.** `POST /upload-urls`, then `PUT` each file to `signed_url` with the returned `headers`, then `POST /documents` with `{"upload_ids": [...]}`.
- **SSE.** `GET /shipments/{id}/events` needs the Authorization header, which browser `EventSource` can't send. Use a fetch-based client such as `@microsoft/fetch-event-source`. It replays the current run's events on connect and honours `Last-Event-ID`. `GET /shipments/{id}` is the polling fallback.
- **Snippets.** `GET /documents/{id}/pages/{n}/crop?bbox=x0,y0,x1,y1` returns `image/png` and needs the token, so fetch it as a blob. `/image` returns JSON with a 5-minute signed URL.
- **Discrepancies.** `GET /shipments/{id}/discrepancies` returns only open (undecided) findings. Add `?include_decided=true` for all of them.
- **Health.** Use `/health`. Cloud Run's front end can intercept paths ending in `z`, so `/healthz` may not reach the app there.

## Notes for the AI service

Only `/ai/v1/extract` is pinned by the spec. The classify, reconcile and explain shapes the backend sends and parses are drafts, defined in [app/schemas/ai.py](app/schemas/ai.py). Example request/response pairs are in [contracts/fixtures/ai/examples/](../contracts/fixtures/ai/examples/); regenerate them with `scripts/export_ai_fixtures.py`. Errors should use the §7 envelope, because the worker maps the `code` and `retryable` fields. [app/services/ai_stub.py](app/services/ai_stub.py) is a deterministic stand-in for the AI service:
- extract: a text-layer parser.
- reconcile: a faithful implementation of AI-SPEC §11.
- explain: a majority vote.

It reports `model: "stub"` and makes no LLM calls.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/smoke.py` | Runs the end-to-end flow against any base URL. |
| `scripts/export_openapi.py` | Regenerates `contracts/openapi.yaml`. |
| `scripts/export_ai_fixtures.py` | Regenerates the AI contract examples. |
| `scripts/seed_org.py` | Creates an org and sets a Firebase user's custom claims. |
| `scripts/verify_report.py` | Verifies a report signature with only the public key, so a third party can run it. |
