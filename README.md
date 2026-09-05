TRACK_ID=PS03

# RetailPulse AI

RetailPulse AI is a **Retail Sales & Inventory Copilot** for small retail store
managers. It helps them understand their sales and inventory data by answering
questions and surfacing what needs attention.

- The final system will provide **evidence-backed answers and recommendations**.
- AI responses will be **grounded in the application's own data**.
- Gemini (via `GEMINI_API_KEY`) is the only external API that will be used.

## Current Status

Current milestone: **Milestone 2 — Retail Data Layer**.

Implemented:

- A FastAPI backend serving the application on `http://localhost:8000`.
- A health endpoint at `GET /api/health`.
- A static frontend shell that reports backend status and retail data counts.
- A **local SQLite retail data layer** (`data/retailpulse.db`) with realistic,
  deterministic sample data for stores, products, daily sales, and inventory.
- JSON API endpoints to read stores, products, sales, and inventory.
- Deterministic data-generation and data-quality verification scripts.

Not implemented yet (later milestones):

- Gemini chat, intent extraction, embeddings, and RAG / evidence retrieval.
- Stock-out prediction, reorder / overstock / slow-mover detection.
- Sales anomalies, product performance, and store performance analytics.
- The final analytics + copilot dashboard.

The analytics layer in a later milestone MUST derive every conclusion from the
raw data — no analytical labels are stored in the database. The dataset
intentionally contains raw patterns (fast/slow movers, a seasonal product, a
declining product, a short sale spike, a short sale drop, thin stock on some
fast movers, high stock on some slow movers) that later milestones will need to
*discover* from the numbers.

## How to Run

```bash
pip install -r requirements.txt
```

```bash
python app.py
```

Then open:

```
http://localhost:8000
```

The server listens on `0.0.0.0:8000`. No frontend build step is required; the
frontend is served directly by the Python application. No manual database setup
or data-generation step is needed — the committed dataset is used as-is.

## Retail Data Model (Milestone 2)

The application stores raw retail data in a local **SQLite** database. No
external database server is required. The data layer is kept modular
(`src/database.py`, `src/repositories.py`, `src/schema.py`) so it can be
replaced later if necessary.

### Stores — `stores`

Fields: `store_id`, `store_name`, `city`, `region`, `active`.

Five realistic stores are included (e.g. Downtown Store, Central Mall,
Riverside Store, Market Street Store, Harbor Plaza).

### Products — `products`

Fields: `product_id`, `product_name`, `category`, `unit_price`, `active`.

36 products across 6 categories (Beverages, Snacks, Personal Care, Household,
Grocery, Electronics Accessories) with realistic unit prices. The schema has
**no cost / profit / margin fields**, so future profitability questions must be
unanswerable from the data layer — as intended.

### Sales — `sales`

Fields: `sale_id`, `sale_date`, `store_id`, `product_id`, `quantity_sold`,
`revenue`.

90 days of daily history (2025-11-03 to 2026-01-31). Revenue is always exactly
`quantity_sold * product.unit_price`; it is never generated independently.

### Inventory — `inventory`

Fields: `inventory_id`, `store_id`, `product_id`, `current_stock`,
`reorder_level`, `last_restock_date`.

Current on-hand stock and reorder level for every store/product combination,
including intentional low-stock and overstock situations. Stock figures are
non-negative and reference real stores and products.

## Committed Sample Data

- `data/retailpulse.db` — the generated SQLite database, committed to the
  repository. The application uses it immediately after a fresh clone.
- `data/generate_data.py` — regenerates the dataset deterministically:

  ```bash
  python data/generate_data.py
  ```

  Generation uses a fixed random seed, a fixed product/store catalog, and a
  fixed date range, so running it twice always yields the exact same dataset.
- `data/verify_data.py` — runs the Milestone 2 data-quality checks:

  ```bash
  python data/verify_data.py
  ```

  It verifies foreign keys, revenue consistency, non-negative quantities and
  stock, valid dates, store coverage, history depth, and the presence of the
  intended fast/slow mover and low/high stock patterns in the raw numbers.

On startup the application verifies the database; if it is ever missing or
unpopulated it is regenerated deterministically automatically.

## API Endpoints

| Endpoint                     | Description                                            |
| ---------------------------- | ------------------------------------------------------ |
| `GET /api/health`            | Service health and Gemini configuration status.        |
| `GET /api/stores`            | List stores. Filters: `store_id`.                      |
| `GET /api/products`          | List products. Filters: `product_id`, `category`.      |
| `GET /api/sales`             | List sales. Filters: `store_id`, `product_id`, `start_date`, `end_date`. |
| `GET /api/inventory`         | List inventory. Filters: `store_id`, `product_id`.     |
| `GET /api/data/summary`      | Record counts for stores, products, sales, inventory.  |

List endpoints support `limit` and `offset` pagination and return
`{items, total, limit, offset}`. Invalid parameters return useful HTTP errors
(`400`, `404`, `422`) with structured JSON messages; database failures return
`503`. No stack traces or secrets are exposed.

## Environment Variables

| Variable         | Required | Description                                                                            |
| ---------------- | -------- | -------------------------------------------------------------------------------------- |
| `GEMINI_API_KEY` | No       | Gemini API key (used by future LLM features). The app starts fine without it.          |

Read the key only from the `GEMINI_API_KEY` environment variable. Never commit
a real API key to the repository.

## Architecture

- **Python backend** — FastAPI application entry point is `app.py`; the server
  serves both the JSON API and the frontend.
- **Frontend** — A vanilla HTML/CSS/JS dashboard shell under `frontend/`
  (React/Vite may be introduced later, with the production build served by
  Python).
- **Data layer** — `src/schema.py` (schema), `src/database.py` (SQLite
  connections and startup bootstrap), `src/repositories.py` (data access),
  `src/datavalidation.py` (basic validation). Raw data lives under `data/`.
- **Gemini integration (planned)** — Future LLM calls and embeddings
  (`gemini-embedding-001`) for evidence-grounded answers.
- **Deterministic analytics (planned)** — Rule/statistics-based sales and
  inventory analytics, kept separate from LLM reasoning.

## Testing

Run the server with `python app.py`, then check:

- `GET http://localhost:8000/api/health` returns a JSON `status: "ok"`.
- `http://localhost:8000` loads the frontend and shows retail data counts.
- Store, product, sales, and inventory endpoints return structured JSON.

Automated verification:

```bash
python data/verify_data.py      # data-quality checks against the dataset
python tests/verify_api.py      # HTTP-level checks of every API endpoint
```