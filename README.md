# site-scan-ai

## Backend setup

After installing the Python dependencies, install the Chromium runtime used by
the deterministic browser inspector:

```powershell
cd backend
python -m pip install -r requirements.txt
python -m playwright install chromium
```
