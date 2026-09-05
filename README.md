TRACK_ID=PS03

# RetailPulse AI

RetailPulse AI is a **Retail Sales & Inventory Copilot** for small retail store
managers. It helps them understand their sales and inventory data by answering
questions and surfacing what needs attention.

- The final system will provide **evidence-backed answers and recommendations**.
- AI responses will be **grounded in the application's own data**.
- Gemini (via `GEMINI_API_KEY`) is the only external API that will be used.

## Current Status

This is the **initial foundation milestone**. It provides:

- A FastAPI backend serving the application on `http://localhost:8000`.
- A health endpoint at `GET /api/health`.
- A static frontend shell for the retail manager dashboard.

AI copilot features, retrieval (RAG), Gemini integration, embeddings, and
advanced analytics are **not implemented yet** and will be added in later
milestones.

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
frontend is served directly by the Python application.

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
- **Local data** — Raw datasets will live under `data/`.
- **Gemini integration (planned)** — Future LLM calls and embeddings
  (`gemini-embedding-001`) for evidence-grounded answers.
- **Deterministic analytics (planned)** — Rule/statistics-based sales and
  inventory analytics, kept separate from LLM reasoning.

## Testing

Run the server with `python app.py`, then check:

- `GET http://localhost:8000/api/health` returns a JSON `status: "ok"`.
- `http://localhost:8000` loads the frontend shell.