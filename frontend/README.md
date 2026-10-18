# TradeGuard AI

A runnable React frontend for reviewing trade documents before customs submission. Built with Vite, TypeScript, Tailwind, shadcn-style Radix components, React Router, Axios, TanStack Query, React-PDF, Recharts, and jsPDF.

## Run locally

Tested with Node.js 24 and npm 10.

```powershell
cd frontend
npm ci
npm run dev
```

Open the address printed by Vite, normally http://localhost:5173.

No backend or API key is needed for the demo.

## Try the complete demo

1. Open the first shipment to compare three sample documents: 100 / 95 / 100 units and 500 / 480 / 500 kg.
2. Select a table value to inspect its evidence or finding.
3. Review findings. Overrides need a reason of at least 10 characters.
4. Open the report. Finalisation remains disabled until every finding has a decision.
5. Finalise and export a PDF, or print the report.
6. To start fresh, choose New Shipment, enter two different countries, and use the three sample PDFs or your own files.

Draft shipments can be reopened from the dashboard. Failed shipments support retry. Document removal and replacement are available before validation; remove the old file and add its replacement.

## What the demo does

- Shipment metadata, results, and decisions persist in localStorage, the browser's small settings store.
- Original uploaded files persist in IndexedDB, the browser's local file database.
- Processing follows saved timestamps, so navigation or a reload does not stop it.
- Results use the predefined steel-pipes example. Your files are **not analysed** and their names do not determine document type.
- Seeded documents open as generated sample PDFs. Their highlights line up with the recorded sample evidence. Uploaded originals remain available, but fabricated highlights are never placed on them.
- Missing values cannot appear as verified matches. A field needs at least two readable sources for a cross-document match. Summary counts come from the displayed fields.
- Reviewing an issue records a decision; it does not erase a discrepancy. Finalisation locks the review and does not mean the goods are cleared or corrections have been completed.
- Request Correction records a local decision. It sends no message to the shipper.
- The settings page can reset demo shipment records. Browser storage is local to this browser and origin (address plus port).
- PDF, PNG, JPG, and XLSX files are accepted, up to 20 MB each. XLSX originals can be downloaded; spreadsheet cell rendering is not included.

## Backend connection status

The existing backend is in [`../backend/`](../backend/), with its interface described in [`../contracts/openapi.yaml`](../contracts/openapi.yaml). These existing folders have not been changed.

This frontend runs in demo mode by default (`VITE_USE_MOCK=true`). Its HTTP adapter still follows the original frontend brief and has not yet been connected to this repository's backend. Switching the flag alone will not connect the two.

A later frontend-only integration needs to adapt signed-URL uploads, `/analyze`, `/matrix`, `/discrepancies`, decision submission, and report endpoints. See the backend's [frontend notes](../backend/README.md#notes-for-the-frontend). The backend's documented local port is 8080.

`.env.example` contains the original connection settings for reference. Variables starting with VITE_ are public browser configuration; put no secret keys in them.

## Checks

```powershell
npm run build
npm run lint
npm test
```

The automated tests cover file rules, source IDs, coverage totals, processing, retry, review reasons, blocked finalisation, locked reports, and the HTTP adapter.

A complete browser walkthrough is included. Start the frontend first; on Windows with Edge installed, run:

```powershell
npm run test:browser
```

It uses a temporary browser profile and saves screenshots and an exported report in `artifacts/`. It does not change the data in your normal browser. To use a different server address, set TRADEGUARD_URL before running it. For Chromium instead of Edge, run `npx playwright install chromium` and set TRADEGUARD_BROWSER=chromium.

## Code map

- `src/pages/`: the six main screens, document library, settings, and help.
- `src/components/`: shared layout, controls, PDF/image viewer, and status badges.
- `src/hooks/useShipments.ts`: cached requests and changes shared between screens.
- `src/services/`: backend connection, local demo repository, file storage, and sample PDF generation.
- `src/mocks/`: predefined examples, kept separate from interface code.
- `src/lib/`: formatting, result summaries, report data, and PDF export.
- `src/types/`: the data shapes shared with the backend.

Use `npm run build` to create `dist/`, then `npm run preview` to inspect it. A web host must serve index.html for application routes such as /shipments/shp-001/results.
