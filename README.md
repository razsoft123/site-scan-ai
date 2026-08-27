# site-scan-ai

## Backend setup

After installing the Python dependencies, install the Chromium runtime used by
the deterministic browser inspector:

```powershell
cd backend
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Set `GEMINI_API_KEY` in `backend/.env`. `GEMINI_MODEL` defaults to
`gemini-3.1-flash-lite` and can be overridden in the same file.

Start the API from the `backend` folder:

```powershell
uvicorn app.main:app --reload --port 8000
```

## Frontend setup

The frontend is a Vite-powered React and TypeScript application using Tailwind
CSS, Zod, and Zustand. Install and start it with:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

The application opens at `http://localhost:5173` and calls the FastAPI server at
`http://localhost:8000` by default. Change `VITE_API_URL` in `frontend/.env` if
the API runs elsewhere. For a deployed frontend, add its exact origin to
`CORS_ORIGINS` in `backend/.env` as a JSON array.
