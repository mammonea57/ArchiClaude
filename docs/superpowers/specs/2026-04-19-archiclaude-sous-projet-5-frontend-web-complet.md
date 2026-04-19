# ArchiClaude — Sous-projet 5 : Frontend web complet

**Document de spécification — Design validé**
Date : 2026-04-19
Statut : validé par l'utilisateur, prêt pour génération du plan d'implémentation

---

## 1. Contexte et objectif

### 1.1 Objectif

Livrer la couche **auth + multi-user + workspaces + workflow de publication + notifications** par-dessus le frontend existant (SP1-SP4 construit ~17 pages et ~65 composants en mode stub/mono-user).

Le SP5 transforme ArchiClaude d'un prototype fonctionnel en un **produit SaaS multi-tenant production-ready**.

### 1.2 Périmètre

4 blocs indépendants mais complémentaires :

1. **Auth** — Auth.js v5 côté Next.js + JWT signé HS256 côté FastAPI, providers Google + Microsoft + Email/password
2. **Multi-user sécurisé** — RLS Postgres + filtres backend (ceinture et bretelles), isolation stricte des workspaces
3. **Workspaces** — équipes avec 3 rôles (admin/member/viewer), workspace perso auto à l'inscription, invitations par email
4. **Workflow + notifications** — 5 statuts de projet (draft/analyzed/reviewed/ready_for_pc/archived), notifications in-app + email via Resend avec préférences fines

### 1.3 État avant SP5

- Frontend : 17 pages fonctionnelles en mode stub, pas de vraie auth, projets mono-user via `user_id` placeholder
- Backend : 873 tests, ~50 endpoints API, tous acceptent un `project_id` ou `user_id` sans vérification identité

### 1.4 État après SP5

- Auth fonctionnelle (Google OAuth 1-clic, Microsoft, password)
- RLS Postgres actif sur 8 tables privées
- Workspaces opérationnels avec invitations email
- Notifications in-app + email avec préférences par catégorie
- Suite de tests d'isolation E2E garantissant l'absence de fuite de données

---

## 2. Architecture globale

```
┌────────────────────────────────────────────────────────┐
│ Auth (Auth.js v5 + JWT backend partagé)                │
│   - Google OAuth + Microsoft OAuth + Email/password    │
│   - Session côté Next.js via cookies httpOnly          │
│   - JWT signé HS256 pour appels backend FastAPI        │
└────────────────────┬───────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────┐
│ Multi-user sécurisé                                     │
│   - Filtres backend `WHERE workspace_id IN (...)`      │
│   - RLS Postgres (ceinture + bretelles)                │
│   - `SET LOCAL app.user_id` au début de chaque tx      │
└────────────────────┬───────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────┐
│ Workspaces (équipes)                                    │
│   - 3 rôles : admin / member / viewer                  │
│   - Projets appartiennent à un workspace               │
│   - Workspace perso auto créé à l'inscription          │
│   - Invitations par email avec acceptation in-app      │
└────────────────────┬───────────────────────────────────┘
                     │
┌────────────────────▼───────────────────────────────────┐
│ Workflow + Notifications                                │
│   - 5 statuts projets (draft/analyzed/reviewed/        │
│     ready_for_pc/archived)                             │
│   - Transitions explicites avec permissions            │
│   - Notifications in-app + email via Resend            │
│   - Préférences fines par catégorie                    │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Auth hybride (Auth.js + JWT backend)

### 3.1 Flow OAuth Google/Microsoft

```
1. User clique "Se connecter avec Google" sur /login
2. Auth.js redirige vers Google consent screen
3. Google redirige vers /api/auth/callback/google avec code
4. Auth.js échange code contre user_info Google
5. Auth.js POST /auth/oauth/callback (backend)
   body: {provider: "google", email, name, provider_user_id}
6. Backend :
   - Cherche user existant par email (ou par provider_user_id)
   - Si inexistant : crée user + workspace perso + workspace_member (admin)
   - Émet JWT HS256 signé avec JWT_SECRET
   - Retourne {access_token, user, default_workspace_id}
7. Auth.js stocke JWT dans session cookie httpOnly + secure + sameSite=lax
8. Frontend redirige vers /projects
```

### 3.2 Flow Email/Password

**Inscription** :
- Page `/signup` → formulaire email + password + full_name
- POST `/auth/register` → création user + workspace perso, envoi email de bienvenue, émission JWT
- Redirection auto `/projects`

**Connexion** :
- Page `/login` → email + password
- POST `/auth/login` → vérification bcrypt, émission JWT

### 3.3 Endpoints backend auth

```
POST /auth/register          body: {email, password, full_name}
                              → 201 {access_token, user, default_workspace_id}

POST /auth/login             body: {email, password}
                              → 200 {access_token, user, default_workspace_id}

POST /auth/oauth/callback    body: {provider, email, name, provider_user_id}
                              → 200 {access_token, user, default_workspace_id}

GET  /auth/me                (auth required)
                              → 200 User

POST /auth/logout            → 204

POST /auth/refresh           (auth required, JWT expires <24h)
                              → 200 {access_token}
```

### 3.4 JWT payload

Signé HS256 avec `JWT_SECRET` (variable d'env partagée entre Next.js et FastAPI) :

```json
{
  "sub": "user_uuid",
  "email": "user@example.com",
  "workspace_id": "current_workspace_uuid",
  "exp": 1735689600,
  "iat": 1735083600
}
```

Durée par défaut : **7 jours**. Refresh glissant : chaque requête authentifiée réémet un JWT frais si expire dans <24h.

### 3.5 Middleware FastAPI

```python
# api/deps.py
async def get_current_user(
    authorization: str = Header(...),
    session: AsyncSession = Depends(get_session),
) -> UserRow:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid authorization header")
    token = authorization[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid or expired token")
    user = await session.get(UserRow, UUID(payload["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    # Set DB context for RLS
    await session.execute(text(f"SET LOCAL app.user_id = '{user.id}'"))
    return user
```

Tous les endpoints existants passent de :
```python
async def create_project(...):
    ...
```

à :
```python
async def create_project(..., current_user: UserRow = Depends(get_current_user)):
    ...
```

### 3.6 Providers Auth.js côté frontend

```typescript
// apps/frontend/src/auth.ts
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import Microsoft from "next-auth/providers/azure-ad";
import Credentials from "next-auth/providers/credentials";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Google({ clientId: GOOGLE_OAUTH_CLIENT_ID, clientSecret: GOOGLE_OAUTH_CLIENT_SECRET }),
    Microsoft({ clientId: MICROSOFT_OAUTH_CLIENT_ID, clientSecret: MICROSOFT_OAUTH_CLIENT_SECRET }),
    Credentials({ /* email/password via backend */ }),
  ],
  session: { strategy: "jwt" },
  callbacks: {
    async signIn({ user, account, profile }) {
      // Call backend /auth/oauth/callback to create/update user
      const response = await fetch(`${BACKEND_URL}/api/v1/auth/oauth/callback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: account.provider,
          email: user.email,
          name: user.name,
          provider_user_id: account.providerAccountId,
        }),
      });
      const data = await response.json();
      user.accessToken = data.access_token;
      user.workspaceId = data.default_workspace_id;
      return true;
    },
    async jwt({ token, user }) {
      if (user) {
        token.accessToken = user.accessToken;
        token.workspaceId = user.workspaceId;
      }
      return token;
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken;
      session.workspaceId = token.workspaceId;
      return session;
    },
  },
});
```

### 3.7 Variables d'env requises

```bash
# Shared
JWT_SECRET=<random_256bit_hex>
NEXTAUTH_SECRET=<same_as_JWT_SECRET>

# Backend
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
MICROSOFT_OAUTH_CLIENT_ID=
MICROSOFT_OAUTH_CLIENT_SECRET=
RESEND_API_KEY=
RESEND_FROM_EMAIL=noreply@archiclaude.app
PUBLIC_APP_URL=http://localhost:3010

# Frontend
NEXTAUTH_URL=http://localhost:3010
BACKEND_URL=http://localhost:8000
GOOGLE_OAUTH_CLIENT_ID=<same>
GOOGLE_OAUTH_CLIENT_SECRET=<same>
MICROSOFT_OAUTH_CLIENT_ID=<same>
MICROSOFT_OAUTH_CLIENT_SECRET=<same>
```

---

## 4. Multi-user sécurisé (RLS + filtres backend)

### 4.1 Filtres backend

Chaque query SQL ajoute un filtre sur `workspace_id` :

```python
# Avant
projects = (await session.execute(select(ProjectRow))).scalars().all()

# Après
user_workspace_ids = (await get_user_workspaces(user.id)).scalars().all()
projects = (await session.execute(
    select(ProjectRow).where(ProjectRow.workspace_id.in_(user_workspace_ids))
)).scalars().all()
```

### 4.2 RLS Postgres

Activé sur 8 tables privées :

```sql
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
CREATE POLICY projects_workspace_isolation ON projects
    USING (workspace_id IN (
        SELECT workspace_id FROM workspace_members 
        WHERE user_id = current_setting('app.user_id')::UUID
    ));

ALTER TABLE feasibility_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY feasibility_isolation ON feasibility_results
    USING (project_id IN (SELECT id FROM projects));

ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY reports_isolation ON reports
    USING (feasibility_result_id IN (SELECT id FROM feasibility_results));

ALTER TABLE pcmi_dossiers ENABLE ROW LEVEL SECURITY;
CREATE POLICY pcmi_isolation ON pcmi_dossiers
    USING (project_id IN (SELECT id FROM projects));

ALTER TABLE pcmi6_renders ENABLE ROW LEVEL SECURITY;
CREATE POLICY pcmi6_isolation ON pcmi6_renders
    USING (project_id IN (SELECT id FROM projects));

ALTER TABLE project_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY versions_isolation ON project_versions
    USING (project_id IN (SELECT id FROM projects));

ALTER TABLE agency_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY agency_isolation ON agency_settings
    USING (user_id = current_setting('app.user_id')::UUID);

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
CREATE POLICY notifications_isolation ON notifications
    USING (user_id = current_setting('app.user_id')::UUID);
```

### 4.3 Initialisation de `app.user_id`

Dans le middleware `get_current_user` (§3.5) au début de chaque transaction :
```python
await session.execute(text(f"SET LOCAL app.user_id = '{user.id}'"))
```

`SET LOCAL` garantit que la valeur est portée uniquement sur la transaction en cours.

### 4.4 Tables mutualisées (pas de RLS)

Cache public partagé :
- `users`, `workspaces`, `workspace_members`, `workspace_invitations` (gérées par auth)
- `parcels`, `plu_documents`, `plu_zones`, `servitudes`
- `zone_rules_text`, `zone_rules_numeric`
- `jurisprudences`, `recours_cases`
- `commune_sru`, `comparable_projects`

### 4.5 Tests d'isolation

Suite E2E `tests/integration/test_rls_isolation.py` :
- user A crée un projet dans workspace A → user B dans workspace B ne le voit pas (liste = 0)
- user B tente `GET /projects/{projet_A_id}` → 404
- user B tente `GET /feasibility/{result_A_id}` → 404
- user B tente `GET /pcmi6/renders/{render_A_id}` → 404
- Même suite pour pcmi_dossiers, project_versions, agency_settings, notifications

### 4.6 Migration de données existantes

Fichier `alembic/versions/20260419_0003_multi_user_migration.py` :
1. Crée tables `workspaces`, `workspace_members`, `workspace_invitations`
2. Pour chaque user existant, crée un workspace perso avec `is_personal = true`
3. Ajoute `workspace_id UUID` à `projects` (nullable temporaire)
4. Update : `projects.workspace_id = workspace perso de projects.user_id`
5. `projects.workspace_id` passe en NOT NULL
6. Active RLS sur les 8 tables
7. Crée les policies

---

## 5. Workspaces

### 5.1 Tables DB

```sql
CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    description TEXT,
    logo_url TEXT,
    is_personal BOOLEAN DEFAULT false,
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    archived_at TIMESTAMPTZ NULL
);
CREATE INDEX workspaces_created_by ON workspaces(created_by);

CREATE TABLE workspace_members (
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('admin', 'member', 'viewer')),
    invited_by UUID REFERENCES users(id),
    invited_at TIMESTAMPTZ DEFAULT now(),
    joined_at TIMESTAMPTZ,
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX workspace_members_user ON workspace_members(user_id);

CREATE TABLE workspace_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'member', 'viewer')),
    invited_by UUID NOT NULL REFERENCES users(id),
    token TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX invitations_email_pending ON workspace_invitations(email) 
    WHERE accepted_at IS NULL;

-- Modif table existante
ALTER TABLE projects ADD COLUMN workspace_id UUID REFERENCES workspaces(id);
```

### 5.2 Rôles et permissions

| Action | Admin | Member | Viewer |
|---|---|---|---|
| Voir tous les projets du workspace | ✓ | ✓ | ✓ |
| Créer un projet | ✓ | ✓ | ✗ |
| Modifier projet (brief, plans, etc.) | ✓ | ✓ | ✗ |
| Supprimer projet | ✓ | owner du projet seulement | ✗ |
| Gérer les membres | ✓ | ✗ | ✗ |
| Inviter un nouveau membre | ✓ | ✗ | ✗ |
| Modifier le workspace (nom, logo) | ✓ | ✗ | ✗ |
| Supprimer le workspace | ✓ (sauf personnel) | ✗ | ✗ |

### 5.3 Endpoints API

```
POST   /workspaces                          → 201 {workspace, role: "admin"}
GET    /workspaces                          → [{workspace, role}] (tous les workspaces de l'user)
GET    /workspaces/{id}                     → Workspace + membres
PATCH  /workspaces/{id}                     body: {name?, description?, logo_url?}
                                              → Workspace (admin only)
DELETE /workspaces/{id}                     → 204 (admin, pas workspace personnel)

GET    /workspaces/{id}/members             → [{user, role, joined_at}]
PATCH  /workspaces/{id}/members/{uid}       body: {role} → Member (admin only)
DELETE /workspaces/{id}/members/{uid}       → 204 (admin only, ne peut pas se retirer soi-même)

POST   /workspaces/{id}/invitations         body: {email, role}
                                              → 201 Invitation + email envoyé (admin only)
GET    /workspaces/{id}/invitations         → [Invitation] (pending, admin only)
DELETE /workspaces/{id}/invitations/{iid}   → 204 (admin only)

POST   /invitations/{token}/accept          → 200 {workspace_id, role}
POST   /invitations/{token}/decline         → 204
GET    /me/invitations                      → [Invitation] (reçues par l'user courant)
```

### 5.4 Workspace personnel

Créé automatiquement à l'inscription :
- `name = "{Prénom} — Espace personnel"` (ou `"{email}"` si pas de nom)
- `is_personal = true`
- User créé comme admin
- **Non supprimable** (empêche l'user de se retrouver sans workspace)
- Peut être renommé

### 5.5 Sélecteur workspace

**Header** : dropdown visible sur toutes les pages authentifiées.
- Affiche le workspace actif
- Liste tous les workspaces de l'user
- Bouton "Créer un workspace" en bas
- Badge "Perso" sur le workspace personnel

**Switch de workspace** :
- Clic sur un autre workspace → `PATCH /auth/workspace` avec `{workspace_id}` → backend émet nouveau JWT avec `workspace_id` mis à jour
- Auth.js rafraîchit la session

### 5.6 Invitations

**Flow admin invite** :
1. Admin va sur `/workspaces/{id}/members`
2. Clic sur "Inviter un membre" → modal demande email + rôle
3. POST `/workspaces/{id}/invitations` → backend :
   - Crée row `workspace_invitations` avec token UUID et expires_at = now() + 7 jours
   - Envoie email via Resend avec lien `{PUBLIC_APP_URL}/invitations/{token}/accept`

**Flow destinataire reçoit email** :
- Email avec bouton "Rejoindre {workspace_name}"
- Clic → `/invitations/{token}/accept`
- Si pas connecté : redirection vers `/signup?invitation={token}`
- Si connecté : page demande confirmation → POST `/invitations/{token}/accept` → ajouté au workspace, JWT mis à jour

**Dashboard invitations en attente** :
- L'user voit ses invitations pending dans le dashboard (`/projects` sidebar)
- Possibilité d'accepter ou décliner en 1 clic

---

## 6. Workflow de projets

### 6.1 Les 5 statuts

```
draft ──▶ analyzed ──▶ reviewed ──▶ ready_for_pc ──▶ archived
                                                           ▲
                                                           │
                                                   archived ◀── (admin)
                                                           │
                                                   draft ◀── (admin)
```

### 6.2 Transitions autorisées

| Transition | Trigger | Permissions |
|---|---|---|
| `draft → analyzed` | Auto après `/analyze` worker OK | Système |
| `analyzed → reviewed` | Bouton manuel "Valider l'analyse" | admin + member |
| `reviewed → ready_for_pc` | Auto après génération PCMI complète | Système |
| `ready_for_pc → archived` | Bouton "Archiver" | admin + member (owner projet) |
| `* → archived` | Bouton "Archiver" (force) | admin uniquement |
| `archived → draft` | Bouton "Restaurer" | admin uniquement |

Toute transition non listée → 403.

### 6.3 Tables DB

```sql
ALTER TABLE projects ADD COLUMN status TEXT NOT NULL DEFAULT 'draft' 
    CHECK (status IN ('draft', 'analyzed', 'reviewed', 'ready_for_pc', 'archived'));
ALTER TABLE projects ADD COLUMN status_changed_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE projects ADD COLUMN status_changed_by UUID REFERENCES users(id);

CREATE TABLE project_status_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    from_status TEXT,
    to_status TEXT NOT NULL,
    changed_by UUID REFERENCES users(id),
    changed_at TIMESTAMPTZ DEFAULT now(),
    notes TEXT
);
CREATE INDEX project_status_history_project ON project_status_history(project_id, changed_at DESC);
```

### 6.4 Endpoints

```
PATCH  /projects/{id}/status          body: {status, notes?} → Project
GET    /projects/{id}/status_history  → [StatusChange]
```

### 6.5 UI

**Badge par statut** (couleurs) :
- `draft` : gris clair (#94a3b8), "Brouillon"
- `analyzed` : bleu (#3b82f6), "Analysé"
- `reviewed` : teal (#0d9488), "Validé"
- `ready_for_pc` : vert (#16a34a), "Prêt pour dépôt" ✓
- `archived` : slate foncé (#475569), "Archivé"

**Page `/projects`** :
- Onglets filtrant par statut : Tous / Brouillons / Analysés / Validés / Prêts / Archivés
- Chaque projet affiche son badge
- Tri par `status_changed_at DESC`

**Page `/projects/[id]`** :
- Badge statut en haut à droite
- Bouton de transition contextuel :
  - Si `analyzed` et user a droit : "Valider l'analyse"
  - Si `ready_for_pc` et user a droit : "Archiver"
- Timeline des changements de statut dans la sidebar

---

## 7. Notifications (in-app + email + préférences fines)

### 7.1 Tables DB

```sql
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    link TEXT,
    metadata JSONB,
    read_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX notifications_user_unread ON notifications(user_id, read_at) 
    WHERE read_at IS NULL;

CREATE TABLE notification_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    in_app_enabled BOOLEAN DEFAULT true,
    email_workspace_invitations BOOLEAN DEFAULT true,
    email_project_analyzed BOOLEAN DEFAULT true,
    email_project_ready_for_pc BOOLEAN DEFAULT true,
    email_mentions BOOLEAN DEFAULT true,
    email_comments BOOLEAN DEFAULT false,
    email_pcmi6_generated BOOLEAN DEFAULT false,
    email_weekly_digest BOOLEAN DEFAULT false,
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

### 7.2 Module `core/notifications/`

```
apps/backend/core/notifications/
├── __init__.py
├── dispatcher.py              # notify(user_id, type, ...) 
├── email_sender.py            # Resend API wrapper
├── preferences.py             # get_user_preferences() + defaults
└── templates/
    ├── base.html.j2           # layout commun ArchiClaude
    ├── workspace_invitation.html.j2
    ├── project_analyzed.html.j2
    ├── project_ready_for_pc.html.j2
    ├── mention.html.j2
    ├── comment.html.j2
    └── signup_confirmation.html.j2
```

### 7.3 Dispatcher central

```python
# core/notifications/dispatcher.py
async def notify(
    *,
    user_id: UUID,
    type: str,
    title: str,
    body: str,
    link: str | None = None,
    metadata: dict | None = None,
    email_vars: dict | None = None,
):
    """Send notification in-app (always) + email (per preferences)."""
    # 1. Create in-app notification
    await _create_in_app_notification(user_id, type, title, body, link, metadata)
    
    # 2. Check user preferences
    prefs = await get_preferences(user_id)
    email_pref_key = f"email_{type}"
    if getattr(prefs, email_pref_key, False):
        user_email = await get_user_email(user_id)
        await email_sender.send(
            to=user_email,
            template=type,
            vars={"title": title, "body": body, "link": link, **(email_vars or {})},
        )
```

### 7.4 Service email : Resend

```python
# core/notifications/email_sender.py
import os
import resend

resend.api_key = os.environ.get("RESEND_API_KEY", "")

async def send(*, to: str, template: str, vars: dict) -> None:
    """Send templated email via Resend."""
    if not resend.api_key:
        logger.warning("RESEND_API_KEY not set — skipping email")
        return  # Graceful degradation
    
    # Render Jinja2 template
    html = _render_template(template, vars)
    subject = _get_subject(template, vars)
    
    try:
        resend.Emails.send({
            "from": os.environ.get("RESEND_FROM_EMAIL", "noreply@archiclaude.app"),
            "to": to,
            "subject": subject,
            "html": html,
        })
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
```

### 7.5 Endpoints API

```
GET    /notifications              ?unread_only=true&limit=20 → [Notification]
PATCH  /notifications/{id}/read    → 204
POST   /notifications/mark-all-read → 204
GET    /notifications/unread-count → {count: int}
GET    /account/notifications      → NotificationPreferences
PATCH  /account/notifications      body: {email_*: bool} → NotificationPreferences
```

### 7.6 Événements déclencheurs

| Événement | Type | Défaut email |
|---|---|---|
| Invitation à workspace reçue | `workspace_invitation` | ON |
| Invitation acceptée (pour admin qui invite) | `invitation_accepted` | ON |
| Projet analysé (créateur) | `project_analyzed` | ON |
| Projet passé en `ready_for_pc` | `project_ready_for_pc` | ON |
| `@mention` dans commentaire | `mention` | ON |
| Commentaire ajouté à un projet partagé | `comment` | OFF |
| Rendu PCMI6 généré | `pcmi6_generated` | OFF |
| Récap hebdomadaire | `weekly_digest` | OFF |

### 7.7 Frontend

**Header** : icône cloche avec badge `count` des non-lues. Clic ouvre panneau déroulant avec 50 dernières notifications (in-app).

**Page `/account/notifications`** : toggles organisés par catégorie :
- "Partage & collaboration" : workspace invitations, invitation acceptée, mentions, commentaires
- "Progression des projets" : projet analysé, projet prêt PC, rendu PCMI6
- "Annonces produit" : récap hebdomadaire

---

## 8. Pages et composants frontend

### 8.1 Pages nouvelles

- `/login` — refonte avec 3 providers
- `/signup` — refonte avec workspace perso auto
- `/account/notifications` — préférences
- `/workspaces` — liste + créer
- `/workspaces/{id}` — détails + stats
- `/workspaces/{id}/members` — gestion membres + invitations
- `/workspaces/{id}/settings` — nom, logo, suppression
- `/invitations/{token}/accept` — acceptation d'invitation

### 8.2 Composants nouveaux

- `<WorkspaceSelector>` — header dropdown
- `<NotificationBell>` — header cloche + badge
- `<NotificationPanel>` — dropdown avec liste des 50 dernières
- `<NotificationItem>` — item dans le panel
- `<StatusBadge>` — badge coloré par statut de projet
- `<StatusTransitionButton>` — bouton contextuel selon statut + permissions
- `<WorkspaceMemberRow>` — row dans la liste des membres
- `<InviteMemberDialog>` — modal envoi invitation
- `<AcceptInvitationCard>` — carte dans le dashboard si invitations en attente
- `<RoleBadge>` — badge admin/member/viewer

### 8.3 Composants modifiés

- `<NavHeader>` (tous les layouts) : ajout `<WorkspaceSelector>` + `<NotificationBell>` + menu utilisateur
- `<ProjectCard>` et `<ProjectList>` : affichage du `<StatusBadge>`
- `<LoginPage>` / `<SignupPage>` : refonte avec providers OAuth

---

## 9. Critères de succès

| Critère | Seuil |
|---|---|
| Auth Google 1-clic | ≤ 10 secondes du clic "Se connecter" à la redirection `/projects` |
| Auth Microsoft | Flow identique fonctionnel |
| Email/password | Inscription + connexion fonctionnels, bcrypt rounds=12 |
| JWT signing | HS256, 7 jours, refresh si <24h |
| RLS isolation | 0 fuite détectée sur suite de tests E2E (user A ne voit pas user B) |
| Workspace perso | Créé automatiquement à l'inscription, non supprimable |
| Invitations | Email reçu en <30s, lien token valide 7 jours |
| Notifications in-app | Temps réel (<1s après event) via polling ou SSE |
| Notifications email | Préférences respectées, templates Jinja2 corrects sur Gmail/Outlook/Apple Mail |
| Transitions statuts | Aucune transition non-autorisée ne passe (403 systématique) |
| Historique statuts | 100% des changements loggés |

---

## 10. Hors scope SP5

- **Facturation / abonnements** — SP6 (v2)
- **Partage projet par lien public** (token read-only) — v1.1
- **Permissions fines par projet** (au-delà du rôle workspace) — v1.1
- **2FA / MFA** — v1.2 (SMS ou TOTP)
- **SSO SAML** (grandes entreprises) — v2
- **Audit log complet** (qui a modifié quoi et quand) — v1.1
- **Mentions `@user` dans commentaires** — v1.1 (le système de notifications mention est prêt mais l'UI commentaires ne l'est pas encore)
- **Système de commentaires sur projets** — v1.1

---

## Fin du document
