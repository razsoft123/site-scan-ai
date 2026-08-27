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
`gemini-3.7-flash` and can be overridden in the same file.
