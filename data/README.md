# data/

This directory holds the local retail sales and inventory dataset for RetailPulse
AI.

- `retailpulse.db` — the committed SQLite database with the deterministic sample
  dataset (stores, products, sales, inventory). The application uses it
  immediately after a fresh clone.
- `generate_data.py` — regenerates `retailpulse.db` deterministically:
  `python data/generate_data.py`.
- `verify_data.py` — runs data-quality checks on `retailpulse.db`:
  `python data/verify_data.py`.

Data here is treated as input data, not application source code. The data
parsing and deterministic analytics stay in the backend (`src/`), separate from
any future Gemini-based reasoning.