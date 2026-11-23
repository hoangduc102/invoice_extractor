# Invoice Extractor – Web UI

Next.js 16 (App Router, TypeScript, Tailwind CSS 4) client for the FastAPI backend in `../api`.

- Upload a PDF/image → `POST /invoices/extract`, then shows the extracted fields, missing fields and retry count.
- Browse saved invoices → `GET /invoices` with vendor search, status filter and pagination; `GET /invoices/stats` for the header counters.
- Click a row for the full record and raw model output; delete with `DELETE /invoices/{id}`.

```bash
cp .env.example .env.local   # NEXT_PUBLIC_API_URL, default http://localhost:8000
npm install
npm run dev                  # http://localhost:3000 (start the API first: uvicorn api.main:app)
npm run lint && npm run build
```

The API must allow this origin via `CORS_ORIGINS` (default `http://localhost:3000`).
