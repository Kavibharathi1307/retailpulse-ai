TRACK_ID=PS03

# RetailPulse AI

RetailPulse AI is a **Retail Sales & Inventory Copilot** for small retail store
managers. It helps them understand their sales and inventory data by answering
questions and surfacing what needs attention.

- The final system will provide **evidence-backed answers and recommendations**.
- AI responses will be **grounded in the application's own data**.
- Gemini (via `GEMINI_API_KEY`) is the only external API that will be used.

## Current Status

Current milestone: **Milestone 4 — Gemini Grounded Copilot**.

Implemented:

- A FastAPI backend serving the application on `http://localhost:8000`.
- A health endpoint at `GET /api/health`.
- A static frontend shell that reports backend status and retail data counts.
- A **local SQLite retail data layer** (`data/retailpulse.db`) with realistic,
  deterministic sample data for stores, products, daily sales, and inventory.
- JSON API endpoints to read stores, products, sales, and inventory.
- A **deterministic analytics engine** (`src/analytics/`) with **no AI**: pure,
  rule-based stock-out risk, overstock and slow-mover detection, sales
  spike/drop detection, product and store performance, plus a severity-sorted
  attention summary with explicit evidence for every finding.
- Analytics API endpoints under `/api/analytics`.
- A **grounded natural-language copilot** (`src/gemini/` + `/api/copilot/query`)
  that answers retail questions with Google Gemini, where Gemini may only use
  evidence produced by the deterministic analytics engine.
- Automated analytics unit tests and HTTP-level API verification plus a fully
  mocked M4 test suite (no API key required to run the tests).

Not implemented yet (future milestones):

- Embeddings and RAG / vector-database evidence retrieval.
- The final analytics + copilot dashboard.

The analytics layer derives every conclusion from the raw numbers — no
analytical labels are stored in the database. The dataset intentionally
contains raw patterns (fast/slow movers, a seasonal product, a declining
product, a short sale spike, a short sale drop, thin stock on some fast
movers, high stock on some slow movers) that the engine *discovers* from the
data.

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

## Deterministic Analytics Engine (Milestone 3)

The engine in `src/analytics/` is **pure and deterministic**: identical inputs
always produce identical outputs, and no AI/Gemini call is made anywhere in it.
Every insight is derived from documented formulas and carries an `evidence`
block (the raw numbers that produced it) plus an `explanation` in plain text —
this is what a future AI layer will rely on for grounded answers.

**Analysis date.** By default every endpoint is evaluated **as of the latest
sale date in the dataset** (`2026-01-31`), never the real-world calendar date.
The chosen date is echoed back as `analysis_date` in every response. An
`as_of_date` outside the dataset range is rejected with `400`.

**Windows (configured in `src/analytics/config.py`).**

| Window | Days | Used for |
| ------ | ---: | -------- |
| Demand window | 28 | Stock-out risk, overstock, slow movers |
| Performance period | 28 | Product / store performance vs previous period |
| Anomaly scan | 90 | Sales spike / drop detection |
| Anomaly recent | 7 | The window compared against the baseline |
| Anomaly baseline | 28 | Window immediately before the recent window |

**Formulas and rules.**

- `average_daily_sales = units in demand window / demand window days`.
- **Stock-out risk**: `days_of_stock = current_stock / average_daily_sales`
  with status `CRITICAL` (≤ 7 days), `HIGH` (≤ 14), `MEDIUM` (≤ 30),
  else `LOW`. `estimated_stock_out_date` is only emitted when demand exists.
- **Overstock**: `stock_cover_days = current_stock / average_daily_sales`;
  `OVERSTOCK` when cover ≥ 60 days.
- **Slow movers**: `SLOW_MOVER` when `average_daily_sales` ≤ 0.5 units/day
  **and** the product sold on ≥ 5 distinct days in the window (avoids
  false positives from thin history).
- **Sales anomalies**: a rolling scan compares the recent 7-day daily rate with
  the preceding 28-day baseline rate:
  `change_pct = (recent_daily_rate − baseline_daily_rate) / baseline_daily_rate × 100`.
  `SPIKE` when `change_pct ≥ +100%`; `DROP` when `change_pct ≤ −50%`. Volume
  safeguards: the baseline window must total ≥ 30 units and the absolute change
  must be ≥ 10 units. The strongest qualifying event per store/product is
  reported.
- **Performance**: units, revenue, averages, period-over-period change `%`, and
  a first-half vs second-half **trend** (`UP` / `DOWN` / `STABLE`). The engine
  reports measurements; it never invents advice.

**Honest unknowns.** When there is not enough history or no observed demand the
engine returns `data_status: "INSUFFICIENT_DATA"` (or `UNKNOWN` for stock-out
risk) and **does not fabricate** a stock-out date, a trend, or an anomaly
label. A product with zero sales is never called a slow mover just because it
did not sell.

**No profitability claims.** The schema stores no cost/profit/margin fields, so
the engine reports units and revenue only and never computes or asserts
profitability.

**Attention summary.** Aggregates the riskiest findings — stock-out risks
(CRITICAL and HIGH only), overstock, slow movers, sales spikes and drops — into
one severity-sorted list with counts. This summary is the single evidence
source a future copilot will summarize.

**Thresholds.** All thresholds live in one frozen `AnalyticsConfig`
(`src/analytics/config.py`) and can be tuned in a single place.

## Gemini Grounded Copilot (Milestone 4)

Users can now ask natural-language retail questions ("What needs my
attention today?", "Which products are at risk of stock-out?") through the
Copilot panel in the frontend or directly via `POST /api/copilot/query`.
The answer is **grounded**: Gemini may only use evidence supplied by the
deterministic analytics engine, never external knowledge.

**Architecture — evidence first, language second.**

1. **Deterministic intent classification** (`src/gemini/intents.py`) routes the
   question to one supported retail intent using keyword rules. No model call is
   involved, and off-topic questions are detected before anything else.
2. **Evidence retrieval** (`src/gemini/evidence.py`) runs the relevant analytics
   engine operation (stock-out risk, overstock, slow movers, spikes/drops,
   product/store performance, attention summary) and returns the top records
   with their raw numbers — this is the only source of facts.
3. **Grounded prompting** (`src/gemini/prompts.py`) sends the evidence as a
   JSON block to Gemini. The system instruction is the hallucination barrier:
   Gemini may use **only** the supplied evidence, must ignore any numbers or
   product claims that appear only in the question, must never invent data, and
   must treat `FACT` vs `ESTIMATE` distinctions strictly.
4. **Deterministic fallback** (`src/gemini/service.py`): if the evidence is
   empty, unsupported questions are never sent to Gemini, and if the API key is
   missing or any Gemini call fails, the service returns an engine-only
   summary (grounded answer, `ai_status` explains why).

**Supported question intents.** `stockout`, `reorder`, `overstock`,
`slow_movers`, `spike`, `drop`, `product_performance`, `store_performance`,
`attention`, and `unsupported` (gracefully refused where the data cannot
answer or the topic is outside the retail data).

**Response shape** (for every question):

```json
{
  "question": "...",
  "answer": "...",
  "intent": "stockout",
  "analysis_date": "2026-01-31",
  "data_status": "SUFFICIENT",
  "evidence": [ { "type": "STOCK_OUT_RISK", "category": "FACT", "severity": "CRITICAL",
                  "store_name": "...", "product_name": "...", "metric": "days_of_stock",
                  "value": 2.2, "threshold": "CRITICAL<=7 days", "analysis_date": "2026-01-31" } ],
  "assumptions": [ "...", "..." ],
  "grounded": true,
  "ai_status": "AVAILABLE",
  "model": "gemini-2.5-flash"
}
```

`data_status` is `SUFFICIENT`, `INSUFFICIENT_DATA`, or `UNSUPPORTED`.
`ai_status` is `AVAILABLE`, `NOT_CONFIGURED`, `UNAVAILABLE`, or `SKIPPED`.

**Safety and safeguards.**

- The Gemini API key is read only from the `GEMINI_API_KEY` environment
  variable and is **never** exposed to the frontend, in API responses, in
  logs, or in the codebase. The app starts fine without the key.
- Off-topic and unsupported questions never reach Gemini.
- Empty deterministic evidence means the answer explicitly says the data
  cannot determine it — Gemini is skipped.
- The question is capped at 500 characters; empty or over-length questions are
  rejected at the API (`400`/`422`).
- User questions are treated as **untrusted text**: the evidence block is built
  only from the analytics engine (numbers or products mentioned only in the
  question cannot enter the evidence), and Gemini's output is rendered in the
  frontend as plain text, so no HTML/script injection is possible.
- No `eval`, `exec`, or dynamic code execution anywhere in the pipeline.

## API Endpoints

| Endpoint                     | Description                                            |
| ---------------------------- | ------------------------------------------------------ |
| `GET /api/health`            | Service health and Gemini configuration status.        |
| `GET /api/stores`            | List stores. Filters: `store_id`.                      |
| `GET /api/products`          | List products. Filters: `product_id`, `category`.      |
| `GET /api/sales`             | List sales. Filters: `store_id`, `product_id`, `start_date`, `end_date`. |
| `GET /api/inventory`         | List inventory. Filters: `store_id`, `product_id`.     |
| `GET /api/data/summary`      | Record counts for stores, products, sales, inventory.  |
| `GET /api/analytics/attention-summary` | Severity-sorted attention list with counts. Filters: `store_id`, `product_id`, `as_of_date`. |
| `GET /api/analytics/stock-out-risks` | Stock-out risk per store/product. Filters: `store_id`, `product_id`, `as_of_date`. |
| `GET /api/analytics/overstock`       | Overstock detection. Filters: `store_id`, `product_id`, `as_of_date`. |
| `GET /api/analytics/slow-movers`     | Slow-mover detection. Filters: `store_id`, `product_id`, `as_of_date`. |
| `GET /api/analytics/sales-anomalies` | Sales spikes/drops. Filters: `store_id`, `product_id`, `as_of_date`, `start_date`, `end_date`. |
| `GET /api/analytics/product-performance` | Per-product performance. Filters: `product_id`, `as_of_date`, `start_date`, `end_date`. |
| `GET /api/analytics/store-performance`   | Per-store performance. Filters: `store_id`, `as_of_date`, `start_date`, `end_date`. |
| `POST /api/copilot/query` | Natural-language retail query. Body: `{ "question": "..." }`. Returns the grounded answer, intent, evidence, assumptions, data status, and AI status. |

Data endpoints return `{items, total, limit, offset}`. Analytics list endpoints
return the same envelope alongside `analysis_date` (and the relevant window
boundaries). Every analytics row includes `analysis_date`, `store_id` /
`product_id` (with names), `explanation`, `evidence`, and `data_status`.
The copilot endpoint always returns HTTP `200` for answered or gracefully
refused questions; invalid requests return `400`/`422`.
Invalid parameters return useful HTTP errors (`400`, `404`, `422`) with
structured JSON messages; database failures return `503`. No stack traces or
secrets are exposed.

## Environment Variables

| Variable                    | Required | Description                                                                                 |
| --------------------------- | -------- | ------------------------------------------------------------------------------------------- |
| `GEMINI_API_KEY`            | No       | Gemini API key for the grounded copilot. The app and all tests work fine without it.        |
| `GEMINI_MODEL`              | No       | Gemini model id. Default: `gemini-2.5-flash`.                                               |
| `GEMINI_MAX_OUTPUT_TOKENS`  | No       | Max tokens for copilot answers. Default: `800`.                                             |

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
- **Analytics engine** — `src/analytics/` is a pure, deterministic, no-AI layer
  split into `config.py` (all thresholds), `data.py` (all SQL reads),
  `metrics.py` (shared numeric helpers), and one module per category
  (`performance.py`, `stock.py`, `velocity.py`, `anomalies.py`,
  `attention.py`) orchestrated by `engine.py` and exposed by
  `src/analytics_api.py`. Calculation modules never touch the database; SQL
  lives only in `data.py`. The `attention` module emits the evidence the
  copilot relies on.
- **Grounded copilot** — `src/gemini/` holds the no-AI routing glue:
  `intents.py` (deterministic keyword classification), `evidence.py` (runs the
  analytics engine and builds the fact block independent of Gemini),
  `config.py` + `client.py` (google-genai SDK wrapper with timeouts and error
  mapping), `prompts.py` (grounding system instruction and prompt assembly),
  and `service.py` (orchestration plus the deterministic fallback). It is
  exposed by `src/copilot_api.py` and consumes the engine via
  `src/analytics/engine.py` only. No embeddings or vector store are used in
  this milestone.

## Testing

Run the server with `python app.py`, then check:

- `GET http://localhost:8000/api/health` returns a JSON `status: "ok"`.
- `http://localhost:8000` loads the frontend and shows retail data counts plus
  the analytics attention summary (analysis date and stock-out / overstock /
  slow-mover / anomaly counts).
- Store, product, sales, and inventory endpoints return structured JSON.
- `/api/analytics/*` endpoints return `analysis_date`, the envelope, and rows
  with `evidence` and `explanation`.

Automated verification (all deterministic, no network needed — the copilot
tests use a mocked Gemini client):

```bash
python data/verify_data.py            # data-quality checks against the dataset
python tests/verify_api.py            # HTTP-level checks of the data endpoints
python -m unittest tests.test_analytics -v   # analytics engine unit tests
python tests/verify_analytics_api.py  # HTTP-level checks of the analytics APIs
python -m unittest tests.test_copilot -v     # copilot unit tests (mocked Gemini)
python tests/verify_copilot_api.py    # HTTP-level checks of the copilot + frontend
```

The unit tests build a tiny synthetic retail database with controlled patterns
(zero-sales product, slow mover, overstock, a spike, a drop, short history) and
assert the exact statuses, numbers, and `INSUFFICIENT_DATA` behavior the engine
must produce. The copilot tests additionally verify intent routing,
evidence-based grounding, the no-fabrication contract, every Gemini failure
mode's fallback, and the security checks (key never in frontend/responses, no
`eval`/`exec`, Gemini output rendered as untrusted text).

**Using the copilot.** Ask questions in the Copilot panel (suggestion chips are
provided) or call:

```bash
curl -X POST http://localhost:8000/api/copilot/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Which products are at risk of stock-out?"}'
```

If `GEMINI_API_KEY` is set, answers are phrased by Gemini but constrained to
the engine's evidence. Without a key (or on any Gemini failure) the endpoint
still answers with a deterministic engine-only summary so the app never stalls
or hallucinates.