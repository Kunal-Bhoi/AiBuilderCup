# TradeGuard frontend

React, Vite, and TypeScript frontend connected to the existing backend in ../backend. Backend source and shared contracts are unchanged.

## Run against the backend

Start the backend on port 8080 using its [run instructions](../backend/README.md#run-locally-no-docker).

In a separate terminal, from the repository root:

```powershell
cd frontend
npm ci
npm run dev
```

Open the address printed by Vite, normally http://localhost:5173.

The default is connected mode. Vite forwards /api requests to http://localhost:8080, so no frontend environment file is required for local development. The connection check and session settings are under Settings.

The backend's local defaults use development identity and simulated model processing. Connecting this frontend does not change the backend's model-service configuration.

## Workflow

1. Create a shipment using its reference. The existing backend does not store extra country or duty fields on shipment creation; those can be extracted from the uploaded documents.
2. Add up to 20 documents, each up to 50 MB. Files upload to the temporary storage links returned by the backend, then register with the shipment.
3. Correct document types if necessary and start validation. The processing screen follows the backend's current run.
4. Review the document matrix, missing documents, uncertain values, and fields outside coverage.
5. Record a decision for every finding. Accept a suggestion, override a value using a selected document or corrected value, flag for follow-up, or dismiss with a reason.
6. If someone else changed a finding, review the refreshed values before retrying. The frontend sends the current record version with each decision.
7. Issue the report when the backend marks the review complete. The server generates and signs the PDF; the frontend downloads it from the returned temporary link.

Document previews use the backend's rendered page images. This works for supported PDFs, images, and spreadsheets after ingestion. Original-file download is not exposed by this backend, so the connected viewer does not claim to download original files.

Re-analysis is available before a report is issued. Issued reports lock document and decision changes according to the backend's rules.

## Connection and identity

Copy .env.example to .env only if you need to override settings.

| Setting | Purpose |
|---|---|
| VITE_USE_MOCK | false connects to the backend; true runs the standalone demo |
| VITE_API_BASE_URL | /api/v1 locally, or the full backend address ending in /api/v1 |
| VITE_PROXY_TARGET | Backend address for the development proxy; defaults to http://localhost:8080 |

Restart Vite after changing environment variables.

There is no sign-in. The app is usable immediately as the workspace user. Settings has a **Review role** choice (Approver, Owner or Viewer) that is sent to the server as `X-Dev-Role`; the server enforces it, so a viewer cannot record decisions or issue reports.

The frontend never forwards its identity headers to temporary file-storage links.

For a production build, configure VITE_API_BASE_URL to the deployed backend, or configure the web host to forward /api to it. Vite's development proxy is not included in production builds. The backend and storage service must allow the frontend's browser origin. All VITE_ variables are public; they must contain no secret model or service keys.

## Standalone demo

To run the sample data without a backend:

```powershell
$env:VITE_USE_MOCK='true'
npm run dev
```

The demo keeps metadata in localStorage and original files in IndexedDB, the browser's local file database. Values come from predefined examples and do not analyse the contents of your files.

## Checks

```powershell
npm run check:api
npm run build
npm run lint
npm test
```

API types in src/types/backend.generated.ts are generated from ../contracts/openapi.yaml. After an intentional backend contract update, run npm run generate:api.

The unit tests cover real backend response shapes, all shipment states, signed uploads, coverage, uncertain cells, source coordinates, review versions, report downloads, and demo state.

For browser tests against backend-model-validated response fixtures, start connected mode on port 5175:

```powershell
npm run dev -- --port 5175
```

In another terminal:

```powershell
npm run test:browser:backend
```

This test intercepts server responses in a temporary browser profile. It exercises the whole interface without a database, including concurrent review errors and report issue/download. It is a contract test, not proof that a deployed backend is available. Screenshots, the downloaded PDF, and captured request bodies are saved in artifacts/.

The fixture responses and captured requests can also be validated by the actual backend data models, using a Python environment with the backend dependencies installed:

```powershell
python scripts/validate-backend-contract.py artifacts/backend-browser-requests.json
```

For the standalone demo walkthrough, start a demo server and run npm run test:browser. Set TRADEGUARD_URL if the test server is not on its script's default port. Browser tests use Edge on Windows. For Chromium, install it with npx playwright install chromium and set TRADEGUARD_BROWSER=chromium.

## Source map

- src/services/shipmentService.ts: backend requests, upload flow, report issue and download.
- src/services/backendAdapter.ts: converts server data into screen data while preserving uncertainty.
- src/services/session.ts: workspace identity and the selected review role (no sign-in).
- src/types/backend.generated.ts: generated server contract.
- src/components/documents/: rendered-page viewer and manual type correction.
- src/components/validation/: coverage and missing-document details.
- src/pages/: shipment, review, report, document library, analytics, and settings screens.

npm run build creates dist/. A web host must serve index.html for application routes such as /shipments/shp_123/results.
