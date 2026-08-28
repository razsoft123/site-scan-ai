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

## Container images

The frontend image builds the React application with Node and serves only the
resulting static files from an unprivileged Nginx process on port `8080`. Node is
not present in the runtime image. The backend image runs one Uvicorn worker on
port `8000` and installs only Playwright's Chromium browser.

Build locally from the repository root:

```bash
docker build \
  --build-arg VITE_API_URL=https://api.example.com \
  --tag site-scan-frontend:latest \
  frontend

docker build --tag site-scan-backend:latest backend
```

`VITE_API_URL` is compiled into the frontend bundle. Rebuild the frontend image
when that URL changes.

Create a backend environment file outside the repository containing at least:

```dotenv
DB_USERNAME=site_scan
DB_PASSWORD=replace-me
DB_HOST=database-host
DB_PORT=5432
DB_NAME=site_scan
JWT_SECRET_KEY=replace-with-at-least-32-characters
GEMINI_API_KEY=replace-me
GEMINI_MODEL=gemini-3.1-flash-lite
CORS_ORIGINS=["https://app.example.com"]
```

Example low-memory runtime commands:

```bash
docker run -d \
  --name site-scan-backend \
  --restart unless-stopped \
  --env-file /opt/site-scan/backend.env \
  --memory 384m \
  --memory-swap 768m \
  --shm-size 64m \
  --publish 8000:8000 \
  --volume site-scan-artifacts:/app/artifacts \
  ghcr.io/OWNER/REPOSITORY-backend:latest

docker run -d \
  --name site-scan-frontend \
  --restart unless-stopped \
  --memory 32m \
  --memory-swap 64m \
  --publish 8080:8080 \
  ghcr.io/OWNER/REPOSITORY-frontend:latest
```

The backend will not start unless PostgreSQL is reachable. Its health endpoint
is `/health`; the frontend health endpoint is `/healthz`. Screenshots persist in
the named `site-scan-artifacts` volume.

### Manual GitHub builds

Create a repository Actions secret named `VITE_API_URL` containing the public
backend URL, such as `https://api.example.com`. Vite uses this value only while
the frontend image is built. Backend database credentials, JWT settings, and
Gemini credentials are not stored in GitHub; provide them from the server's
environment file when starting the backend container.

The two workflows are independent and have no inputs:

- **Build frontend image** publishes
  `ghcr.io/OWNER/REPOSITORY-frontend:latest`.
- **Build backend image** publishes
  `ghcr.io/OWNER/REPOSITORY-backend:latest`.

Run either one from its **Actions → workflow name → Run workflow** page. Both
use GitHub's built-in `GITHUB_TOKEN`, so no registry password secret is required.
If a package is private, authenticate the server with a GitHub token that has
`read:packages` before pulling it.

Because the Compose image references always remain on `:latest`, updating the
server does not require editing the Compose file. Docker still needs to pull the
new image before recreating the containers:

```bash
docker compose pull
docker compose up -d
```

### 512 MB server note

The static frontend has a small memory footprint and the API is deliberately
limited to one worker. Chromium is the variable part: a complex page can still
use several hundred MB during a browser audit. Keep the application's existing
one-browser-at-a-time limit, enable at least 1 GB of host swap, and monitor for
OOM kills. If the other applications leave substantially less than 350–400 MB
available, move browser audits to a larger worker instead of increasing
concurrency.
