# ArchiClaude

Plateforme web de faisabilité architecturale et de génération de dossiers PC pour promoteurs immobiliers en Île-de-France.

**Statut :** Phase 0 — setup infrastructure technique.

**Documentation :**
- Spec sous-projet 1 : [docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md](docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md)
- Plan Phase 0 : [docs/superpowers/plans/2026-04-16-archiclaude-phase-0-setup.md](docs/superpowers/plans/2026-04-16-archiclaude-phase-0-setup.md)

## Développement local

Prérequis : Node 20+, pnpm 9+, Python 3.12+, Docker Desktop.

```bash
pnpm install
docker compose up -d postgres redis
pnpm dev
```

Backend : http://localhost:8000/docs
Frontend : http://localhost:3001

> Port 3001 côté frontend pour ne pas entrer en conflit avec l'autre application Urbanisme (port 3000).
