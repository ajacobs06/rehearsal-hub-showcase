# Rehearsal Hub

Members-only web app for the University of Birmingham Barbershop Singing Society: per-part learning tracks, a "learned" tracker and a rehearsal schedule.

Built on Azure free tiers: App Service (F1) running a Python FastAPI backend that also serves the React front end, Cosmos DB free tier, Blob Storage.

- Planning doc: (private planning doc)
- Build spec and conventions: [CLAUDE.md](CLAUDE.md)

## Local development
Prerequisites: Node 20+, Python 3.11.

```bash
# API (terminal 1)
cd api
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn main:app --reload --port 8000

# Front end (terminal 2): http://localhost:5173, /api is proxied to :8000
cd app
npm install
npm run dev
```

Run API tests with `cd api && .venv/bin/pytest`.

## Deployment
Pushes to `main` build, test and deploy to Azure App Service via `.github/workflows/deploy.yml`.
Infrastructure lives in `infra/main.bicep`.

## Status
Milestones 0-4 deployed (foundations, sign-in & members, songs & tracks, learned tracker, rehearsal schedule). Next: Milestone 5 (pilot).
