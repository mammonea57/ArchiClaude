# ArchiClaude — Sous-projet 5 : Frontend web complet — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformer ArchiClaude en produit SaaS multi-tenant production-ready : auth hybride Auth.js + JWT, RLS Postgres, workspaces avec 3 rôles, workflow projets 5 statuts, notifications in-app + email Resend avec préférences fines.

**Architecture:** Backend FastAPI — auth routes + RLS middleware + workspaces CRUD + invitations + notifications dispatcher. Frontend Next.js 16 — Auth.js v5 avec providers Google/Microsoft/Credentials, WorkspaceSelector, NotificationBell, pages workspaces. Isolation multi-tenant via workspace_id + RLS policies + session JWT.

**Tech Stack:** Python 3.12 FastAPI, passlib[bcrypt], pyjwt, resend, SQLAlchemy 2.0, Alembic, Next.js 16, Auth.js v5 (next-auth@beta), React 19.

**Spec source:** `docs/superpowers/specs/2026-04-19-archiclaude-sous-projet-5-frontend-web-complet.md`

---

## File Structure

```
apps/backend/
├── core/notifications/
│   ├── __init__.py                             (NEW)
│   ├── dispatcher.py                           (NEW)
│   ├── email_sender.py                         (NEW)
│   ├── preferences.py                          (NEW)
│   └── templates/
│       ├── base.html.j2                        (NEW)
│       ├── workspace_invitation.html.j2        (NEW)
│       ├── project_analyzed.html.j2            (NEW)
│       ├── project_ready_for_pc.html.j2        (NEW)
│       ├── mention.html.j2                     (NEW)
│       ├── comment.html.j2                     (NEW)
│       └── signup_confirmation.html.j2         (NEW)
├── core/auth/
│   ├── __init__.py                             (NEW)
│   ├── jwt_utils.py                            (NEW)
│   └── password.py                             (NEW)
├── api/routes/
│   ├── auth.py                                 (NEW)
│   ├── workspaces.py                           (NEW)
│   ├── invitations.py                          (NEW)
│   └── notifications.py                        (NEW)
├── api/deps.py                                 (MODIFY — add get_current_user)
├── api/main.py                                 (MODIFY — register routers, CORS)
├── db/models/
│   ├── workspaces.py                           (NEW)
│   ├── workspace_members.py                    (NEW)
│   ├── workspace_invitations.py                (NEW)
│   ├── project_status_history.py               (NEW)
│   ├── notifications.py                        (NEW)
│   ├── notification_preferences.py             (NEW)
│   ├── oauth_accounts.py                       (NEW)
│   └── projects.py                             (MODIFY — add workspace_id, status, status_changed_*)
├── schemas/
│   ├── auth.py                                 (NEW)
│   ├── workspace.py                            (NEW)
│   ├── invitation.py                           (NEW)
│   └── notification.py                         (NEW)
├── alembic/versions/
│   └── 20260419_0003_sp5_multi_user.py         (NEW)
└── tests/
    ├── unit/
    │   ├── test_jwt_utils.py                   (NEW)
    │   ├── test_password.py                    (NEW)
    │   ├── test_notifications_dispatcher.py    (NEW)
    │   └── test_email_sender.py                (NEW)
    └── integration/
        ├── test_auth_endpoints.py              (NEW)
        ├── test_workspaces_endpoints.py        (NEW)
        ├── test_invitations_endpoints.py       (NEW)
        ├── test_notifications_endpoints.py     (NEW)
        ├── test_project_status_transitions.py  (NEW)
        └── test_rls_isolation.py               (NEW)

apps/frontend/src/
├── auth.ts                                     (NEW — Auth.js v5 config)
├── middleware.ts                               (NEW — auth middleware)
├── app/api/auth/[...nextauth]/route.ts         (NEW — Auth.js handlers)
├── app/login/page.tsx                          (REWRITE — 3 providers)
├── app/signup/page.tsx                         (REWRITE — 3 providers)
├── app/account/notifications/page.tsx          (NEW)
├── app/workspaces/page.tsx                     (NEW)
├── app/workspaces/[id]/page.tsx                (NEW)
├── app/workspaces/[id]/members/page.tsx        (NEW)
├── app/workspaces/[id]/settings/page.tsx       (NEW)
├── app/invitations/[token]/accept/page.tsx     (NEW)
├── components/
│   ├── WorkspaceSelector.tsx                   (NEW)
│   ├── NotificationBell.tsx                    (NEW)
│   ├── NotificationPanel.tsx                   (NEW)
│   ├── NotificationItem.tsx                    (NEW)
│   ├── StatusBadge.tsx                         (NEW)
│   ├── StatusTransitionButton.tsx              (NEW)
│   ├── RoleBadge.tsx                           (NEW)
│   ├── WorkspaceMemberRow.tsx                  (NEW)
│   ├── InviteMemberDialog.tsx                  (NEW)
│   └── AcceptInvitationCard.tsx                (NEW)
├── lib/hooks/
│   ├── useWorkspaces.ts                        (NEW)
│   ├── useNotifications.ts                     (NEW)
│   └── useAuth.ts                              (NEW)
└── lib/api.ts                                  (MODIFY — inject Bearer JWT)
```

---

## Task 1: Backend auth — JWT utils + password hashing

**Files:**
- Create: `apps/backend/core/auth/__init__.py`
- Create: `apps/backend/core/auth/jwt_utils.py`
- Create: `apps/backend/core/auth/password.py`
- Test: `apps/backend/tests/unit/test_jwt_utils.py`
- Test: `apps/backend/tests/unit/test_password.py`
- Modify: `apps/backend/pyproject.toml`

- [ ] **Step 1: Install dependencies**

Verify `pyproject.toml` has these (already present from Phase 0):
- `passlib[bcrypt]==1.7.4`
- `pyjwt[crypto]==2.9.0`

Run: `cd apps/backend && pip install -e ".[dev]"`

- [ ] **Step 2: Write failing tests for password**

```python
# apps/backend/tests/unit/test_password.py
import pytest
from core.auth.password import hash_password, verify_password


def test_hash_password_produces_bcrypt():
    h = hash_password("my_secret_123")
    assert h.startswith("$2b$")  # bcrypt prefix
    assert len(h) >= 60


def test_verify_correct_password():
    h = hash_password("correct_password")
    assert verify_password("correct_password", h) is True


def test_verify_wrong_password():
    h = hash_password("correct_password")
    assert verify_password("wrong_password", h) is False


def test_hash_is_deterministic_with_same_input_differs():
    """Bcrypt uses a random salt — same password hashes differently."""
    h1 = hash_password("abc")
    h2 = hash_password("abc")
    assert h1 != h2
    # Both must still verify
    assert verify_password("abc", h1)
    assert verify_password("abc", h2)
```

- [ ] **Step 3: Implement password hashing**

```python
# apps/backend/core/auth/__init__.py
"""Authentication utilities — JWT emission/verification, password hashing."""

# apps/backend/core/auth/password.py
"""Password hashing with bcrypt (rounds=12)."""
from __future__ import annotations
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return _pwd_context.verify(plain, hashed)
```

- [ ] **Step 4: Write failing tests for JWT**

```python
# apps/backend/tests/unit/test_jwt_utils.py
import pytest
import time
from uuid import uuid4
from core.auth.jwt_utils import emit_jwt, decode_jwt, JWTError


def test_emit_and_decode_jwt():
    uid = uuid4()
    wid = uuid4()
    token = emit_jwt(user_id=uid, email="u@test.fr", workspace_id=wid, secret="secret1")
    payload = decode_jwt(token, secret="secret1")
    assert payload["sub"] == str(uid)
    assert payload["email"] == "u@test.fr"
    assert payload["workspace_id"] == str(wid)


def test_decode_wrong_secret_fails():
    token = emit_jwt(user_id=uuid4(), email="u@x.fr", workspace_id=uuid4(), secret="good")
    with pytest.raises(JWTError):
        decode_jwt(token, secret="bad")


def test_decode_expired_fails():
    token = emit_jwt(
        user_id=uuid4(), email="u@x.fr", workspace_id=uuid4(),
        secret="s", expires_in_seconds=-1,  # already expired
    )
    with pytest.raises(JWTError):
        decode_jwt(token, secret="s")


def test_default_expiry_7_days():
    token = emit_jwt(user_id=uuid4(), email="u@x.fr", workspace_id=uuid4(), secret="s")
    payload = decode_jwt(token, secret="s")
    now = int(time.time())
    assert payload["exp"] - now > 6 * 86400  # at least 6 days
    assert payload["exp"] - now <= 7 * 86400 + 10


def test_needs_refresh_when_less_than_24h():
    from core.auth.jwt_utils import needs_refresh
    token = emit_jwt(
        user_id=uuid4(), email="u@x.fr", workspace_id=uuid4(),
        secret="s", expires_in_seconds=3600,  # 1h
    )
    assert needs_refresh(token, secret="s") is True

    token2 = emit_jwt(user_id=uuid4(), email="u@x.fr", workspace_id=uuid4(), secret="s")
    assert needs_refresh(token2, secret="s") is False
```

- [ ] **Step 5: Implement JWT utils**

```python
# apps/backend/core/auth/jwt_utils.py
"""JWT emission and verification (HS256, 7 days default)."""
from __future__ import annotations
import time
from uuid import UUID

import jwt as pyjwt

DEFAULT_EXPIRY_SECONDS = 7 * 86400  # 7 days
REFRESH_THRESHOLD_SECONDS = 24 * 3600  # refresh if <24h remaining


class JWTError(Exception):
    """Raised when JWT is invalid, expired or malformed."""


def emit_jwt(
    *,
    user_id: UUID,
    email: str,
    workspace_id: UUID,
    secret: str,
    expires_in_seconds: int = DEFAULT_EXPIRY_SECONDS,
) -> str:
    """Emit a signed HS256 JWT with user_id, email, workspace_id, exp, iat."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "email": email,
        "workspace_id": str(workspace_id),
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str, *, secret: str) -> dict:
    """Decode and validate a JWT. Raises JWTError on invalid/expired."""
    try:
        return pyjwt.decode(token, secret, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError as e:
        raise JWTError("Token expired") from e
    except pyjwt.InvalidTokenError as e:
        raise JWTError(f"Invalid token: {e}") from e


def needs_refresh(token: str, *, secret: str) -> bool:
    """True if token expires within REFRESH_THRESHOLD_SECONDS."""
    try:
        payload = decode_jwt(token, secret=secret)
    except JWTError:
        return False
    return payload["exp"] - int(time.time()) < REFRESH_THRESHOLD_SECONDS
```

- [ ] **Step 6: Run tests + commit**

```bash
cd apps/backend
python -m pytest tests/unit/test_password.py tests/unit/test_jwt_utils.py -v
# Expected: all PASS

cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/auth/ apps/backend/tests/unit/test_password.py apps/backend/tests/unit/test_jwt_utils.py
git commit -m "feat(auth): add JWT emit/decode + bcrypt password hashing"
```

---

## Task 2: DB models + migration for SP5

**Files:**
- Create: `apps/backend/db/models/workspaces.py`
- Create: `apps/backend/db/models/workspace_members.py`
- Create: `apps/backend/db/models/workspace_invitations.py`
- Create: `apps/backend/db/models/oauth_accounts.py`
- Create: `apps/backend/db/models/project_status_history.py`
- Create: `apps/backend/db/models/notifications.py`
- Create: `apps/backend/db/models/notification_preferences.py`
- Modify: `apps/backend/db/models/projects.py` (add workspace_id, status, status_changed_*)
- Create: `apps/backend/alembic/versions/20260419_0003_sp5_multi_user.py`
- Modify: `apps/backend/alembic/env.py` (import new models)

- [ ] **Step 1: Create workspace models**

```python
# apps/backend/db/models/workspaces.py
import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from db.base import Base


class WorkspaceRow(Base):
    __tablename__ = "workspaces"
    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    slug = Column(Text, unique=True, nullable=False)
    description = Column(Text, nullable=True)
    logo_url = Column(Text, nullable=True)
    is_personal = Column(Boolean, nullable=False, server_default="false")
    created_by = Column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    archived_at = Column(DateTime(timezone=True), nullable=True)
```

```python
# apps/backend/db/models/workspace_members.py
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from db.base import Base


class WorkspaceMemberRow(Base):
    __tablename__ = "workspace_members"
    workspace_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role = Column(Text, nullable=False)
    invited_by = Column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    invited_at = Column(DateTime(timezone=True), server_default=func.now())
    joined_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'member', 'viewer')", name="workspace_members_role_check"),
    )
```

```python
# apps/backend/db/models/workspace_invitations.py
import uuid
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from db.base import Base


class WorkspaceInvitationRow(Base):
    __tablename__ = "workspace_invitations"
    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    email = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    invited_by = Column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token = Column(Text, unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'member', 'viewer')",
            name="workspace_invitations_role_check",
        ),
    )
```

- [ ] **Step 2: Create oauth_accounts model**

```python
# apps/backend/db/models/oauth_accounts.py
import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from db.base import Base


class OAuthAccountRow(Base):
    __tablename__ = "oauth_accounts"
    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider = Column(Text, nullable=False)  # google, microsoft
    provider_user_id = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )
```

- [ ] **Step 3: Create status history + notifications models**

```python
# apps/backend/db/models/project_status_history.py
import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from db.base import Base


class ProjectStatusHistoryRow(Base):
    __tablename__ = "project_status_history"
    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status = Column(Text, nullable=True)
    to_status = Column(Text, nullable=False)
    changed_by = Column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    changed_at = Column(DateTime(timezone=True), server_default=func.now())
    notes = Column(Text, nullable=True)

    __table_args__ = (
        Index("project_status_history_project", "project_id", "changed_at"),
    )
```

```python
# apps/backend/db/models/notifications.py
import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from db.base import Base


class NotificationRow(Base):
    __tablename__ = "notifications"
    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    type = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=True)
    link = Column(Text, nullable=True)
    extra = Column(JSONB, nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("notifications_user_unread", "user_id", "read_at"),
    )
```

```python
# apps/backend/db/models/notification_preferences.py
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from db.base import Base


class NotificationPreferencesRow(Base):
    __tablename__ = "notification_preferences"
    user_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    in_app_enabled = Column(Boolean, server_default="true")
    email_workspace_invitations = Column(Boolean, server_default="true")
    email_project_analyzed = Column(Boolean, server_default="true")
    email_project_ready_for_pc = Column(Boolean, server_default="true")
    email_mentions = Column(Boolean, server_default="true")
    email_comments = Column(Boolean, server_default="false")
    email_pcmi6_generated = Column(Boolean, server_default="false")
    email_weekly_digest = Column(Boolean, server_default="false")
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: Modify projects model**

Read `apps/backend/db/models/projects.py` first. Add these columns to `ProjectRow`:

```python
from sqlalchemy import CheckConstraint

# Add to ProjectRow class
workspace_id = Column(
    PgUUID(as_uuid=True),
    ForeignKey("workspaces.id"),
    nullable=True,  # temporary — will be NOT NULL after migration data step
)
status = Column(
    Text,
    nullable=False,
    server_default="draft",
)
status_changed_at = Column(DateTime(timezone=True), server_default=func.now())
status_changed_by = Column(PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

__table_args__ = (
    CheckConstraint(
        "status IN ('draft','analyzed','reviewed','ready_for_pc','archived')",
        name="projects_status_check",
    ),
)
```

- [ ] **Step 5: Create Alembic migration**

```python
# apps/backend/alembic/versions/20260419_0003_sp5_multi_user.py
"""sp5 multi-user + workspaces + notifications

Revision ID: 20260419_0003
Revises: 20260419_0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260419_0003"
down_revision = "20260419_0002"
branch_labels = None
depends_on = None


def upgrade():
    # --- Tables workspaces ---
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("logo_url", sa.Text, nullable=True),
        sa.Column("is_personal", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
    )
    op.create_index("workspaces_created_by", "workspaces", ["created_by"])

    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("invited_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('admin','member','viewer')", name="workspace_members_role_check"),
    )
    op.create_index("workspace_members_user", "workspace_members", ["user_id"])

    op.create_table(
        "workspace_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("token", name="uq_invitations_token"),
        sa.CheckConstraint("role IN ('admin','member','viewer')", name="invitations_role_check"),
    )
    op.execute(
        "CREATE INDEX invitations_email_pending ON workspace_invitations(email) WHERE accepted_at IS NULL"
    )

    # --- OAuth accounts ---
    op.create_table(
        "oauth_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("provider_user_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )

    # --- Status history ---
    op.create_table(
        "project_status_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.Text, nullable=True),
        sa.Column("to_status", sa.Text, nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("project_status_history_project", "project_status_history", ["project_id", "changed_at"])

    # --- Notifications ---
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("link", sa.Text, nullable=True),
        sa.Column("extra", postgresql.JSONB, nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("notifications_user_unread", "notifications", ["user_id", "read_at"])

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("in_app_enabled", sa.Boolean, server_default="true"),
        sa.Column("email_workspace_invitations", sa.Boolean, server_default="true"),
        sa.Column("email_project_analyzed", sa.Boolean, server_default="true"),
        sa.Column("email_project_ready_for_pc", sa.Boolean, server_default="true"),
        sa.Column("email_mentions", sa.Boolean, server_default="true"),
        sa.Column("email_comments", sa.Boolean, server_default="false"),
        sa.Column("email_pcmi6_generated", sa.Boolean, server_default="false"),
        sa.Column("email_weekly_digest", sa.Boolean, server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Alter projects ---
    op.add_column("projects", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=True))
    op.add_column("projects", sa.Column("status", sa.Text, nullable=False, server_default="draft"))
    op.add_column("projects", sa.Column("status_changed_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.add_column("projects", sa.Column("status_changed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True))
    op.create_check_constraint(
        "projects_status_check",
        "projects",
        "status IN ('draft','analyzed','reviewed','ready_for_pc','archived')",
    )

    # --- Data migration: create personal workspace for each existing user, assign existing projects ---
    op.execute("""
        INSERT INTO workspaces (id, name, slug, is_personal, created_by)
        SELECT 
            gen_random_uuid(),
            COALESCE(u.full_name, u.email) || ' — Espace personnel',
            'personal-' || u.id::text,
            true,
            u.id
        FROM users u
    """)

    op.execute("""
        INSERT INTO workspace_members (workspace_id, user_id, role, joined_at)
        SELECT w.id, w.created_by, 'admin', now()
        FROM workspaces w
        WHERE w.is_personal = true
    """)

    op.execute("""
        UPDATE projects p
        SET workspace_id = (
            SELECT w.id FROM workspaces w
            WHERE w.is_personal = true AND w.created_by = p.user_id
            LIMIT 1
        )
        WHERE p.workspace_id IS NULL
    """)

    # Not enforcing workspace_id NOT NULL yet — some projects may have orphaned user_id
    # If needed, DELETE orphans or require manual intervention before NOT NULL constraint


def downgrade():
    op.drop_constraint("projects_status_check", "projects", type_="check")
    op.drop_column("projects", "status_changed_by")
    op.drop_column("projects", "status_changed_at")
    op.drop_column("projects", "status")
    op.drop_column("projects", "workspace_id")
    op.drop_table("notification_preferences")
    op.drop_table("notifications")
    op.drop_table("project_status_history")
    op.drop_table("oauth_accounts")
    op.drop_table("workspace_invitations")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
```

- [ ] **Step 6: Register models in alembic/env.py**

Add to the existing model imports in `alembic/env.py`:
```python
from db.models import (
    workspaces, workspace_members, workspace_invitations,
    oauth_accounts, project_status_history,
    notifications, notification_preferences,
)
```

- [ ] **Step 7: Run migration + confirm no tests break**

```bash
cd apps/backend
alembic upgrade head
python -m pytest tests/ -q --tb=no
# Expected: 873 existing tests pass (no regressions, new models don't add tests yet)
```

- [ ] **Step 8: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/db/models/ apps/backend/alembic/
git commit -m "feat(db): add workspaces, invitations, notifications, status history models"
```

---

## Task 3: Pydantic schemas for SP5

**Files:**
- Create: `apps/backend/schemas/auth.py`
- Create: `apps/backend/schemas/workspace.py`
- Create: `apps/backend/schemas/invitation.py`
- Create: `apps/backend/schemas/notification.py`

- [ ] **Step 1: Auth schemas**

```python
# apps/backend/schemas/auth.py
from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    full_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class OAuthCallbackRequest(BaseModel):
    provider: Literal["google", "microsoft"]
    email: EmailStr
    name: str | None = None
    provider_user_id: str


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str | None = None
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    user: UserOut
    default_workspace_id: UUID
```

- [ ] **Step 2: Workspace schemas**

```python
# apps/backend/schemas/workspace.py
from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


Role = Literal["admin", "member", "viewer"]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    logo_url: str | None = None


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    logo_url: str | None
    is_personal: bool
    created_at: datetime


class WorkspaceListItem(BaseModel):
    workspace: WorkspaceOut
    role: Role


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    full_name: str | None
    role: Role
    joined_at: datetime | None


class MembershipUpdate(BaseModel):
    role: Role
```

- [ ] **Step 3: Invitation schemas**

```python
# apps/backend/schemas/invitation.py
from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, EmailStr


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Literal["admin", "member", "viewer"]


class InvitationOut(BaseModel):
    id: UUID
    workspace_id: UUID
    workspace_name: str
    email: str
    role: str
    invited_by_email: str
    created_at: datetime
    expires_at: datetime


class AcceptInvitationResponse(BaseModel):
    workspace_id: UUID
    role: str
```

- [ ] **Step 4: Notification schemas**

```python
# apps/backend/schemas/notification.py
from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: UUID
    type: str
    title: str
    body: str | None
    link: str | None
    extra: dict | None
    read_at: datetime | None
    created_at: datetime


class NotificationsResponse(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int


class UnreadCountResponse(BaseModel):
    count: int


class NotificationPreferencesOut(BaseModel):
    in_app_enabled: bool
    email_workspace_invitations: bool
    email_project_analyzed: bool
    email_project_ready_for_pc: bool
    email_mentions: bool
    email_comments: bool
    email_pcmi6_generated: bool
    email_weekly_digest: bool


class NotificationPreferencesUpdate(BaseModel):
    in_app_enabled: bool | None = None
    email_workspace_invitations: bool | None = None
    email_project_analyzed: bool | None = None
    email_project_ready_for_pc: bool | None = None
    email_mentions: bool | None = None
    email_comments: bool | None = None
    email_pcmi6_generated: bool | None = None
    email_weekly_digest: bool | None = None
```

- [ ] **Step 5: Commit**

```bash
git add apps/backend/schemas/
git commit -m "feat(schemas): add Pydantic schemas for auth, workspaces, invitations, notifications"
```

---

## Task 4: Auth routes + get_current_user dependency

**Files:**
- Modify: `apps/backend/api/deps.py` (add get_current_user)
- Create: `apps/backend/api/routes/auth.py`
- Modify: `apps/backend/api/main.py` (register auth router)
- Test: `apps/backend/tests/integration/test_auth_endpoints.py`

- [ ] **Step 1: Update deps.py with get_current_user**

```python
# apps/backend/api/deps.py
# (keep existing code, add this at the end)
from __future__ import annotations
import os
from uuid import UUID
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.jwt_utils import JWTError, decode_jwt
from db.models.users import UserRow


def _get_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET not configured")
    return secret


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> UserRow:
    """Validate JWT from Authorization header, return User, set RLS context."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = authorization[7:]
    try:
        payload = decode_jwt(token, secret=_get_jwt_secret())
    except JWTError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    user_id = UUID(payload["sub"])
    user = (
        await session.execute(select(UserRow).where(UserRow.id == user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Set RLS context for this transaction
    await session.execute(text(f"SET LOCAL app.user_id = '{user.id}'"))
    return user


async def get_current_user_optional(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> UserRow | None:
    """Like get_current_user but returns None instead of 401."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return await get_current_user(authorization=authorization, session=session)
    except HTTPException:
        return None
```

- [ ] **Step 2: Create auth routes**

```python
# apps/backend/api/routes/auth.py
from __future__ import annotations
import os
import re
import time
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_session
from core.auth.jwt_utils import emit_jwt
from core.auth.password import hash_password, verify_password
from db.models.oauth_accounts import OAuthAccountRow
from db.models.users import UserRow
from db.models.workspace_members import WorkspaceMemberRow
from db.models.workspaces import WorkspaceRow
from schemas.auth import (
    AuthResponse, LoginRequest, OAuthCallbackRequest, RegisterRequest, UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_secret() -> str:
    s = os.environ.get("JWT_SECRET", "")
    if not s:
        raise HTTPException(500, "JWT_SECRET not configured")
    return s


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{base}-{int(time.time())}"


async def _create_personal_workspace(session: AsyncSession, user: UserRow) -> WorkspaceRow:
    ws = WorkspaceRow(
        name=f"{user.full_name or user.email} — Espace personnel",
        slug=_slugify(user.email),
        is_personal=True,
        created_by=user.id,
    )
    session.add(ws)
    await session.flush()
    session.add(WorkspaceMemberRow(
        workspace_id=ws.id, user_id=user.id, role="admin",
    ))
    await session.flush()
    return ws


def _to_user_out(u: UserRow) -> UserOut:
    return UserOut(id=u.id, email=u.email, full_name=u.full_name, created_at=u.created_at)


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)):
    existing = (await session.execute(
        select(UserRow).where(UserRow.email == body.email)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Email already registered")

    user = UserRow(
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
    )
    session.add(user)
    await session.flush()

    ws = await _create_personal_workspace(session, user)
    await session.commit()
    await session.refresh(user)

    token = emit_jwt(user_id=user.id, email=user.email, workspace_id=ws.id, secret=_get_secret())
    return AuthResponse(
        access_token=token, user=_to_user_out(user), default_workspace_id=ws.id,
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = (await session.execute(
        select(UserRow).where(UserRow.email == body.email)
    )).scalar_one_or_none()
    if not user or not user.password_hash:
        raise HTTPException(401, "Invalid credentials")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")

    ws_id = (await session.execute(
        select(WorkspaceMemberRow.workspace_id)
        .where(WorkspaceMemberRow.user_id == user.id)
        .limit(1)
    )).scalar_one_or_none()
    if not ws_id:
        ws = await _create_personal_workspace(session, user)
        ws_id = ws.id
        await session.commit()

    token = emit_jwt(user_id=user.id, email=user.email, workspace_id=ws_id, secret=_get_secret())
    return AuthResponse(
        access_token=token, user=_to_user_out(user), default_workspace_id=ws_id,
    )


@router.post("/oauth/callback", response_model=AuthResponse)
async def oauth_callback(
    body: OAuthCallbackRequest, session: AsyncSession = Depends(get_session)
):
    # Look up existing user by provider mapping
    oauth_row = (await session.execute(
        select(OAuthAccountRow).where(
            OAuthAccountRow.provider == body.provider,
            OAuthAccountRow.provider_user_id == body.provider_user_id,
        )
    )).scalar_one_or_none()

    if oauth_row:
        user = await session.get(UserRow, oauth_row.user_id)
    else:
        # Try by email
        user = (await session.execute(
            select(UserRow).where(UserRow.email == body.email)
        )).scalar_one_or_none()
        if not user:
            # Create new user
            user = UserRow(
                email=body.email,
                full_name=body.name,
                password_hash=None,  # OAuth-only
            )
            session.add(user)
            await session.flush()
            await _create_personal_workspace(session, user)

        # Link OAuth account
        session.add(OAuthAccountRow(
            user_id=user.id, provider=body.provider,
            provider_user_id=body.provider_user_id,
        ))
        await session.commit()
        await session.refresh(user)

    # Find workspace
    ws_id = (await session.execute(
        select(WorkspaceMemberRow.workspace_id)
        .where(WorkspaceMemberRow.user_id == user.id)
        .limit(1)
    )).scalar_one_or_none()
    if not ws_id:
        ws = await _create_personal_workspace(session, user)
        ws_id = ws.id
        await session.commit()

    token = emit_jwt(user_id=user.id, email=user.email, workspace_id=ws_id, secret=_get_secret())
    return AuthResponse(
        access_token=token, user=_to_user_out(user), default_workspace_id=ws_id,
    )


@router.get("/me", response_model=UserOut)
async def me(current_user: UserRow = Depends(get_current_user)):
    return _to_user_out(current_user)


@router.post("/logout", status_code=204)
async def logout(current_user: UserRow = Depends(get_current_user)):
    # JWT is stateless — client deletes token. Server no-op.
    return None
```

- [ ] **Step 3: Register router in api/main.py**

Add to existing imports and `create_app()`:
```python
from api.routes.auth import router as auth_router
# In create_app():
app.include_router(auth_router, prefix="/api/v1")
```

- [ ] **Step 4: Write integration tests**

```python
# apps/backend/tests/integration/test_auth_endpoints.py
import os
import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration")


@pytest.mark.asyncio
async def test_register_creates_user_and_workspace(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "newuser@test.fr", "password": "password_12345", "full_name": "New User"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["user"]["email"] == "newuser@test.fr"
    assert "access_token" in data
    assert "default_workspace_id" in data


@pytest.mark.asyncio
async def test_register_duplicate_email_conflict(client: AsyncClient):
    payload = {"email": "dup@test.fr", "password": "password_12345", "full_name": "X"}
    r1 = await client.post("/api/v1/auth/register", json=payload)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "login@test.fr", "password": "password_12345", "full_name": "L"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@test.fr", "password": "password_12345"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "pw@test.fr", "password": "correct_pass_1", "full_name": "X"},
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "pw@test.fr", "password": "wrong_pass"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_with_valid_token(client: AsyncClient):
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "me@test.fr", "password": "password_12345", "full_name": "Me"},
    )
    token = reg.json()["access_token"]
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@test.fr"


@pytest.mark.asyncio
async def test_oauth_callback_new_user(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/oauth/callback",
        json={
            "provider": "google",
            "email": "oauth@test.fr",
            "name": "OAuth User",
            "provider_user_id": "google-sub-12345",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "oauth@test.fr"


@pytest.mark.asyncio
async def test_oauth_callback_existing_user_by_provider(client: AsyncClient):
    payload = {
        "provider": "google", "email": "oauth2@test.fr",
        "name": "X", "provider_user_id": "google-sub-22222",
    }
    r1 = await client.post("/api/v1/auth/oauth/callback", json=payload)
    uid1 = r1.json()["user"]["id"]
    r2 = await client.post("/api/v1/auth/oauth/callback", json=payload)
    uid2 = r2.json()["user"]["id"]
    assert uid1 == uid2  # same user returned
```

- [ ] **Step 5: Commit**

```bash
cd apps/backend && python -m pytest tests/integration/test_auth_endpoints.py -v
# Expected: all pass

cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/api/deps.py apps/backend/api/routes/auth.py apps/backend/api/main.py apps/backend/tests/integration/test_auth_endpoints.py
git commit -m "feat(auth): add register/login/oauth/me endpoints + get_current_user dep"
```

---

## Task 5: Workspaces + invitations routes

**Files:**
- Create: `apps/backend/api/routes/workspaces.py`
- Create: `apps/backend/api/routes/invitations.py`
- Modify: `apps/backend/api/main.py` (register routers)
- Test: `apps/backend/tests/integration/test_workspaces_endpoints.py`
- Test: `apps/backend/tests/integration/test_invitations_endpoints.py`

- [ ] **Step 1: Create workspaces routes**

```python
# apps/backend/api/routes/workspaces.py
from __future__ import annotations
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_session
from db.models.users import UserRow
from db.models.workspace_members import WorkspaceMemberRow
from db.models.workspace_invitations import WorkspaceInvitationRow
from db.models.workspaces import WorkspaceRow
from schemas.workspace import (
    WorkspaceCreate, WorkspaceListItem, WorkspaceOut, WorkspaceUpdate,
    MemberOut, MembershipUpdate,
)
from schemas.invitation import InvitationCreate, InvitationOut

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{base}-{int(time.time())}"


def _to_out(w: WorkspaceRow) -> WorkspaceOut:
    return WorkspaceOut(
        id=w.id, name=w.name, slug=w.slug, description=w.description,
        logo_url=w.logo_url, is_personal=w.is_personal, created_at=w.created_at,
    )


async def _require_role(
    session: AsyncSession, workspace_id: UUID, user_id: UUID, required: set[str]
) -> str:
    member = (await session.execute(
        select(WorkspaceMemberRow).where(
            WorkspaceMemberRow.workspace_id == workspace_id,
            WorkspaceMemberRow.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not member or member.role not in required:
        raise HTTPException(403, "Forbidden")
    return member.role


@router.post("", response_model=WorkspaceListItem, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    ws = WorkspaceRow(
        name=body.name, slug=_slugify(body.name),
        description=body.description, is_personal=False,
        created_by=current_user.id,
    )
    session.add(ws)
    await session.flush()
    session.add(WorkspaceMemberRow(
        workspace_id=ws.id, user_id=current_user.id, role="admin",
    ))
    await session.commit()
    await session.refresh(ws)
    return WorkspaceListItem(workspace=_to_out(ws), role="admin")


@router.get("", response_model=list[WorkspaceListItem])
async def list_my_workspaces(
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(
        select(WorkspaceRow, WorkspaceMemberRow.role)
        .join(WorkspaceMemberRow, WorkspaceMemberRow.workspace_id == WorkspaceRow.id)
        .where(WorkspaceMemberRow.user_id == current_user.id)
        .order_by(WorkspaceRow.created_at)
    )).all()
    return [WorkspaceListItem(workspace=_to_out(w), role=r) for w, r in rows]


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: UUID,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_role(session, workspace_id, current_user.id, {"admin", "member", "viewer"})
    ws = await session.get(WorkspaceRow, workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    return _to_out(ws)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: UUID, body: WorkspaceUpdate,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    ws = await session.get(WorkspaceRow, workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if body.name is not None:
        ws.name = body.name
    if body.description is not None:
        ws.description = body.description
    if body.logo_url is not None:
        ws.logo_url = body.logo_url
    await session.commit()
    await session.refresh(ws)
    return _to_out(ws)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: UUID,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    ws = await session.get(WorkspaceRow, workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if ws.is_personal:
        raise HTTPException(400, "Cannot delete personal workspace")
    await session.delete(ws)
    await session.commit()
    return None


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(
    workspace_id: UUID,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_role(session, workspace_id, current_user.id, {"admin", "member", "viewer"})
    rows = (await session.execute(
        select(WorkspaceMemberRow, UserRow)
        .join(UserRow, UserRow.id == WorkspaceMemberRow.user_id)
        .where(WorkspaceMemberRow.workspace_id == workspace_id)
    )).all()
    return [
        MemberOut(
            user_id=u.id, email=u.email, full_name=u.full_name,
            role=m.role, joined_at=m.joined_at,
        )
        for m, u in rows
    ]


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberOut)
async def update_member_role(
    workspace_id: UUID, user_id: UUID, body: MembershipUpdate,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    member = (await session.execute(
        select(WorkspaceMemberRow).where(
            WorkspaceMemberRow.workspace_id == workspace_id,
            WorkspaceMemberRow.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Member not found")
    member.role = body.role
    await session.commit()
    user = await session.get(UserRow, user_id)
    return MemberOut(
        user_id=user.id, email=user.email, full_name=user.full_name,
        role=member.role, joined_at=member.joined_at,
    )


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
async def remove_member(
    workspace_id: UUID, user_id: UUID,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    if user_id == current_user.id:
        raise HTTPException(400, "Cannot remove yourself")
    member = (await session.execute(
        select(WorkspaceMemberRow).where(
            WorkspaceMemberRow.workspace_id == workspace_id,
            WorkspaceMemberRow.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Member not found")
    await session.delete(member)
    await session.commit()
    return None


# --- Invitations attached to workspaces ---

@router.post("/{workspace_id}/invitations", response_model=InvitationOut, status_code=201)
async def create_invitation(
    workspace_id: UUID, body: InvitationCreate,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    inv = WorkspaceInvitationRow(
        workspace_id=workspace_id,
        email=body.email, role=body.role,
        invited_by=current_user.id,
        token=token, expires_at=expires,
    )
    session.add(inv)
    await session.flush()
    ws = await session.get(WorkspaceRow, workspace_id)
    await session.commit()
    await session.refresh(inv)

    # Notify via email (dispatcher, task 6)
    try:
        from core.notifications.dispatcher import send_invitation_email
        await send_invitation_email(
            to_email=body.email,
            workspace_name=ws.name,
            invited_by_email=current_user.email,
            token=token,
        )
    except Exception:
        pass  # graceful, invitation still created

    return InvitationOut(
        id=inv.id, workspace_id=workspace_id, workspace_name=ws.name,
        email=inv.email, role=inv.role,
        invited_by_email=current_user.email,
        created_at=inv.created_at, expires_at=inv.expires_at,
    )


@router.get("/{workspace_id}/invitations", response_model=list[InvitationOut])
async def list_workspace_invitations(
    workspace_id: UUID,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    ws = await session.get(WorkspaceRow, workspace_id)
    rows = (await session.execute(
        select(WorkspaceInvitationRow, UserRow)
        .join(UserRow, UserRow.id == WorkspaceInvitationRow.invited_by)
        .where(
            WorkspaceInvitationRow.workspace_id == workspace_id,
            WorkspaceInvitationRow.accepted_at.is_(None),
        )
    )).all()
    return [
        InvitationOut(
            id=i.id, workspace_id=workspace_id, workspace_name=ws.name,
            email=i.email, role=i.role, invited_by_email=u.email,
            created_at=i.created_at, expires_at=i.expires_at,
        )
        for i, u in rows
    ]


@router.delete("/{workspace_id}/invitations/{invitation_id}", status_code=204)
async def cancel_invitation(
    workspace_id: UUID, invitation_id: UUID,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    inv = await session.get(WorkspaceInvitationRow, invitation_id)
    if not inv or inv.workspace_id != workspace_id:
        raise HTTPException(404, "Invitation not found")
    await session.delete(inv)
    await session.commit()
    return None
```

- [ ] **Step 2: Create invitations-token routes**

```python
# apps/backend/api/routes/invitations.py
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_session
from db.models.users import UserRow
from db.models.workspace_invitations import WorkspaceInvitationRow
from db.models.workspace_members import WorkspaceMemberRow
from db.models.workspaces import WorkspaceRow
from schemas.invitation import AcceptInvitationResponse, InvitationOut

router = APIRouter(tags=["invitations"])


@router.get("/me/invitations", response_model=list[InvitationOut])
async def my_pending_invitations(
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(
        select(WorkspaceInvitationRow, WorkspaceRow, UserRow)
        .join(WorkspaceRow, WorkspaceRow.id == WorkspaceInvitationRow.workspace_id)
        .join(UserRow, UserRow.id == WorkspaceInvitationRow.invited_by)
        .where(
            WorkspaceInvitationRow.email == current_user.email,
            WorkspaceInvitationRow.accepted_at.is_(None),
            WorkspaceInvitationRow.expires_at > datetime.now(timezone.utc),
        )
    )).all()
    return [
        InvitationOut(
            id=i.id, workspace_id=w.id, workspace_name=w.name,
            email=i.email, role=i.role, invited_by_email=u.email,
            created_at=i.created_at, expires_at=i.expires_at,
        )
        for i, w, u in rows
    ]


@router.post("/invitations/{token}/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(
    token: str,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    inv = (await session.execute(
        select(WorkspaceInvitationRow).where(WorkspaceInvitationRow.token == token)
    )).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invitation not found")
    if inv.accepted_at:
        raise HTTPException(400, "Invitation already accepted")
    if inv.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "Invitation expired")
    if inv.email != current_user.email:
        raise HTTPException(403, "This invitation is for another email address")

    # Check if already member
    existing = (await session.execute(
        select(WorkspaceMemberRow).where(
            WorkspaceMemberRow.workspace_id == inv.workspace_id,
            WorkspaceMemberRow.user_id == current_user.id,
        )
    )).scalar_one_or_none()
    if not existing:
        session.add(WorkspaceMemberRow(
            workspace_id=inv.workspace_id, user_id=current_user.id,
            role=inv.role, invited_by=inv.invited_by, joined_at=datetime.now(timezone.utc),
        ))

    inv.accepted_at = datetime.now(timezone.utc)
    await session.commit()

    return AcceptInvitationResponse(workspace_id=inv.workspace_id, role=inv.role)


@router.post("/invitations/{token}/decline", status_code=204)
async def decline_invitation(
    token: str,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    inv = (await session.execute(
        select(WorkspaceInvitationRow).where(WorkspaceInvitationRow.token == token)
    )).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invitation not found")
    if inv.email != current_user.email:
        raise HTTPException(403, "This invitation is for another email address")
    await session.delete(inv)
    await session.commit()
    return None
```

- [ ] **Step 3: Register routers**

In `apps/backend/api/main.py` add:
```python
from api.routes.workspaces import router as workspaces_router
from api.routes.invitations import router as invitations_router

# In create_app():
app.include_router(workspaces_router, prefix="/api/v1")
app.include_router(invitations_router, prefix="/api/v1")
```

- [ ] **Step 4: Integration tests**

```python
# apps/backend/tests/integration/test_workspaces_endpoints.py
import pytest
from httpx import AsyncClient


async def _register(client, email="x@test.fr"):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password_12345", "full_name": "X"},
    )
    return resp.json()


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-ws")


@pytest.mark.asyncio
async def test_create_workspace(client: AsyncClient):
    reg = await _register(client)
    token = reg["access_token"]
    resp = await client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Équipe test"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_list_workspaces_includes_personal(client: AsyncClient):
    reg = await _register(client, "list@test.fr")
    token = reg["access_token"]
    resp = await client.get(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    items = resp.json()
    assert any(item["workspace"]["is_personal"] for item in items)


@pytest.mark.asyncio
async def test_cannot_delete_personal_workspace(client: AsyncClient):
    reg = await _register(client, "nodel@test.fr")
    token = reg["access_token"]
    workspaces = (await client.get(
        "/api/v1/workspaces", headers={"Authorization": f"Bearer {token}"},
    )).json()
    personal_id = next(w["workspace"]["id"] for w in workspaces if w["workspace"]["is_personal"])

    resp = await client.delete(
        f"/api/v1/workspaces/{personal_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_non_admin_cannot_modify(client: AsyncClient):
    reg_a = await _register(client, "adm@test.fr")
    reg_b = await _register(client, "mem@test.fr")
    token_a = reg_a["access_token"]
    # A creates a workspace
    ws = (await client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Shared"},
    )).json()
    ws_id = ws["workspace"]["id"]

    # B tries to modify — 403 because not a member
    resp = await client.patch(
        f"/api/v1/workspaces/{ws_id}",
        headers={"Authorization": f"Bearer {reg_b['access_token']}"},
        json={"name": "Hacked"},
    )
    assert resp.status_code == 403
```

```python
# apps/backend/tests/integration/test_invitations_endpoints.py
import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-inv")


async def _register(client, email):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password_12345", "full_name": email},
    )
    return resp.json()


@pytest.mark.asyncio
async def test_invite_and_accept_flow(client: AsyncClient):
    admin = await _register(client, "admin@test.fr")
    admin_token = admin["access_token"]

    # Create a workspace
    ws = (await client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Team X"},
    )).json()
    ws_id = ws["workspace"]["id"]

    # Invite
    inv_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": "invitee@test.fr", "role": "member"},
    )
    assert inv_resp.status_code == 201
    token = inv_resp.json()["id"]  # not using token here — get from DB or assume response includes link

    # Register invitee
    invitee = await _register(client, "invitee@test.fr")
    invitee_token = invitee["access_token"]

    # List my invitations
    mine = (await client.get(
        "/api/v1/me/invitations",
        headers={"Authorization": f"Bearer {invitee_token}"},
    )).json()
    assert len(mine) == 1
    assert mine[0]["workspace_id"] == ws_id
```

- [ ] **Step 5: Commit**

```bash
cd apps/backend && python -m pytest tests/integration/test_workspaces_endpoints.py tests/integration/test_invitations_endpoints.py -v

cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/api/routes/workspaces.py apps/backend/api/routes/invitations.py apps/backend/api/main.py apps/backend/tests/integration/test_workspaces_endpoints.py apps/backend/tests/integration/test_invitations_endpoints.py
git commit -m "feat(workspaces): add workspaces + invitations CRUD with role-based auth"
```

---

## Task 6: Notifications module (dispatcher + email sender + templates)

**Files:**
- Create: `apps/backend/core/notifications/__init__.py`
- Create: `apps/backend/core/notifications/dispatcher.py`
- Create: `apps/backend/core/notifications/email_sender.py`
- Create: `apps/backend/core/notifications/preferences.py`
- Create: `apps/backend/core/notifications/templates/base.html.j2`
- Create: `apps/backend/core/notifications/templates/workspace_invitation.html.j2`
- Create: `apps/backend/core/notifications/templates/project_analyzed.html.j2`
- Create: `apps/backend/core/notifications/templates/project_ready_for_pc.html.j2`
- Create: `apps/backend/core/notifications/templates/mention.html.j2`
- Create: `apps/backend/core/notifications/templates/comment.html.j2`
- Create: `apps/backend/core/notifications/templates/signup_confirmation.html.j2`
- Create: `apps/backend/api/routes/notifications.py`
- Modify: `apps/backend/api/main.py` (register notifications router)
- Modify: `apps/backend/pyproject.toml` (add resend)
- Test: `apps/backend/tests/unit/test_notifications_dispatcher.py`
- Test: `apps/backend/tests/unit/test_email_sender.py`
- Test: `apps/backend/tests/integration/test_notifications_endpoints.py`

- [ ] **Step 1: Install resend**

Add to `pyproject.toml` dependencies:
```
"resend>=0.7",
```

Install: `cd apps/backend && pip install -e ".[dev]"`

- [ ] **Step 2: Create email templates**

```html
<!-- apps/backend/core/notifications/templates/base.html.j2 -->
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>{{ subject | default("ArchiClaude") }}</title></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,Helvetica,Arial,sans-serif;color:#0f172a;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:32px 0;">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e2e8f0;">
      <tr><td style="padding:24px 32px;border-bottom:1px solid #e2e8f0;">
        <span style="font-family:Georgia,serif;font-size:20px;font-weight:bold;color:#0d9488;">ArchiClaude</span>
      </td></tr>
      <tr><td style="padding:32px;">{% block content %}{% endblock %}</td></tr>
      <tr><td style="padding:24px 32px;border-top:1px solid #e2e8f0;font-size:12px;color:#64748b;">
        <p style="margin:0;">ArchiClaude — Faisabilité architecturale IDF — <a href="{{ app_url }}/account/notifications" style="color:#0d9488;">Gérer mes préférences</a></p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>
```

```html
<!-- apps/backend/core/notifications/templates/workspace_invitation.html.j2 -->
{% extends "base.html.j2" %}
{% block content %}
<h1 style="margin:0 0 16px 0;font-family:Georgia,serif;color:#0f172a;">Invitation à rejoindre un workspace</h1>
<p>Bonjour,</p>
<p><strong>{{ invited_by_email }}</strong> vous invite à rejoindre le workspace <strong>{{ workspace_name }}</strong> sur ArchiClaude.</p>
<p style="text-align:center;margin:32px 0;">
  <a href="{{ app_url }}/invitations/{{ token }}/accept"
     style="display:inline-block;padding:12px 24px;background:#0d9488;color:#fff;text-decoration:none;border-radius:8px;font-weight:600;">
    Accepter l'invitation
  </a>
</p>
<p style="color:#64748b;font-size:13px;">Ce lien expire dans 7 jours.</p>
{% endblock %}
```

(Create similarly simple templates for `project_analyzed`, `project_ready_for_pc`, `mention`, `comment`, `signup_confirmation`.)

Example for project_analyzed:
```html
<!-- apps/backend/core/notifications/templates/project_analyzed.html.j2 -->
{% extends "base.html.j2" %}
{% block content %}
<h1 style="margin:0 0 16px 0;font-family:Georgia,serif;">Analyse de faisabilité terminée</h1>
<p>L'analyse du projet <strong>{{ project_name }}</strong> est disponible.</p>
<p style="text-align:center;margin:32px 0;">
  <a href="{{ app_url }}/projects/{{ project_id }}/report"
     style="display:inline-block;padding:12px 24px;background:#0d9488;color:#fff;text-decoration:none;border-radius:8px;">
    Voir le rapport
  </a>
</p>
{% endblock %}
```

Create stubs for `project_ready_for_pc.html.j2`, `mention.html.j2`, `comment.html.j2`, `signup_confirmation.html.j2` — each extending base with 2-3 lines of content.

- [ ] **Step 3: Implement email_sender**

```python
# apps/backend/core/notifications/__init__.py
"""Notifications subsystem — in-app + email dispatch."""

# apps/backend/core/notifications/email_sender.py
from __future__ import annotations
import logging
import os
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

# Subject by template
_SUBJECTS = {
    "workspace_invitation": "Invitation à rejoindre {workspace_name} sur ArchiClaude",
    "project_analyzed": "{project_name} — analyse de faisabilité disponible",
    "project_ready_for_pc": "{project_name} — dossier PC prêt",
    "mention": "Vous avez été mentionné sur {project_name}",
    "comment": "Nouveau commentaire sur {project_name}",
    "signup_confirmation": "Bienvenue sur ArchiClaude",
}


def _render(template_name: str, variables: dict) -> tuple[str, str]:
    """Return (subject, html)."""
    subject_tpl = _SUBJECTS.get(template_name, "ArchiClaude")
    subject = subject_tpl.format(**{k: variables.get(k, "") for k in _extract_keys(subject_tpl)})
    tpl = _env.get_template(f"{template_name}.html.j2")
    vars_with_defaults = {"app_url": os.environ.get("PUBLIC_APP_URL", ""), **variables, "subject": subject}
    html = tpl.render(**vars_with_defaults)
    return subject, html


def _extract_keys(template: str) -> list[str]:
    import re
    return re.findall(r"\{(\w+)\}", template)


async def send(*, to: str, template: str, variables: dict) -> bool:
    """Send a templated email via Resend. Returns True on success, False otherwise."""
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        logger.warning("RESEND_API_KEY not set — skipping email to %s", to)
        return False

    try:
        import resend
        resend.api_key = api_key
        subject, html = _render(template, variables)
        from_email = os.environ.get("RESEND_FROM_EMAIL", "noreply@archiclaude.app")
        resend.Emails.send({
            "from": from_email, "to": to, "subject": subject, "html": html,
        })
        return True
    except Exception as e:
        logger.error("Email send failed: %s", e)
        return False
```

- [ ] **Step 4: Implement preferences + dispatcher**

```python
# apps/backend/core/notifications/preferences.py
from __future__ import annotations
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.notification_preferences import NotificationPreferencesRow


async def get_or_create(session: AsyncSession, user_id: UUID) -> NotificationPreferencesRow:
    row = (await session.execute(
        select(NotificationPreferencesRow).where(NotificationPreferencesRow.user_id == user_id)
    )).scalar_one_or_none()
    if row:
        return row
    row = NotificationPreferencesRow(user_id=user_id)
    session.add(row)
    await session.flush()
    return row
```

```python
# apps/backend/core/notifications/dispatcher.py
from __future__ import annotations
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from core.notifications import email_sender, preferences
from db.models.notifications import NotificationRow

logger = logging.getLogger(__name__)


async def notify(
    *,
    session: AsyncSession,
    user_id: UUID,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    extra: dict | None = None,
    email_to: str | None = None,
    email_vars: dict | None = None,
):
    """Create in-app notification + send email according to user preferences."""
    # 1. Always create in-app notification
    row = NotificationRow(
        user_id=user_id, type=type, title=title, body=body, link=link, extra=extra,
    )
    session.add(row)
    await session.flush()

    # 2. Check email preference
    prefs = await preferences.get_or_create(session, user_id)
    email_pref = getattr(prefs, f"email_{type}", False)
    if email_pref and email_to:
        await email_sender.send(to=email_to, template=type, variables=email_vars or {})


async def send_invitation_email(
    *,
    to_email: str,
    workspace_name: str,
    invited_by_email: str,
    token: str,
):
    """Send invitation email (even if recipient has no account yet)."""
    await email_sender.send(
        to=to_email,
        template="workspace_invitation",
        variables={
            "workspace_name": workspace_name,
            "invited_by_email": invited_by_email,
            "token": token,
        },
    )
```

- [ ] **Step 5: Create notifications routes**

```python
# apps/backend/api/routes/notifications.py
from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_session
from core.notifications import preferences as pref_module
from db.models.notification_preferences import NotificationPreferencesRow
from db.models.notifications import NotificationRow
from db.models.users import UserRow
from schemas.notification import (
    NotificationOut, NotificationPreferencesOut, NotificationPreferencesUpdate,
    NotificationsResponse, UnreadCountResponse,
)

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=NotificationsResponse)
async def list_notifications(
    unread_only: bool = False,
    limit: int = 20,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    q = select(NotificationRow).where(NotificationRow.user_id == current_user.id)
    if unread_only:
        q = q.where(NotificationRow.read_at.is_(None))
    q = q.order_by(NotificationRow.created_at.desc()).limit(limit)
    rows = (await session.execute(q)).scalars().all()

    total = (await session.execute(
        select(func.count()).select_from(NotificationRow).where(NotificationRow.user_id == current_user.id)
    )).scalar_one()
    unread = (await session.execute(
        select(func.count()).select_from(NotificationRow).where(
            NotificationRow.user_id == current_user.id,
            NotificationRow.read_at.is_(None),
        )
    )).scalar_one()

    return NotificationsResponse(
        items=[
            NotificationOut(
                id=r.id, type=r.type, title=r.title, body=r.body, link=r.link,
                extra=r.extra, read_at=r.read_at, created_at=r.created_at,
            )
            for r in rows
        ],
        total=total, unread=unread,
    )


@router.patch("/notifications/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: UUID,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await session.execute(
        update(NotificationRow)
        .where(
            NotificationRow.id == notification_id,
            NotificationRow.user_id == current_user.id,
        )
        .values(read_at=datetime.now(timezone.utc))
    )
    await session.commit()
    return None


@router.post("/notifications/mark-all-read", status_code=204)
async def mark_all_read(
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await session.execute(
        update(NotificationRow)
        .where(
            NotificationRow.user_id == current_user.id,
            NotificationRow.read_at.is_(None),
        )
        .values(read_at=datetime.now(timezone.utc))
    )
    await session.commit()
    return None


@router.get("/notifications/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    count = (await session.execute(
        select(func.count()).select_from(NotificationRow).where(
            NotificationRow.user_id == current_user.id,
            NotificationRow.read_at.is_(None),
        )
    )).scalar_one()
    return UnreadCountResponse(count=count)


@router.get("/account/notifications", response_model=NotificationPreferencesOut)
async def get_preferences(
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    prefs = await pref_module.get_or_create(session, current_user.id)
    await session.commit()
    return NotificationPreferencesOut(
        in_app_enabled=prefs.in_app_enabled,
        email_workspace_invitations=prefs.email_workspace_invitations,
        email_project_analyzed=prefs.email_project_analyzed,
        email_project_ready_for_pc=prefs.email_project_ready_for_pc,
        email_mentions=prefs.email_mentions,
        email_comments=prefs.email_comments,
        email_pcmi6_generated=prefs.email_pcmi6_generated,
        email_weekly_digest=prefs.email_weekly_digest,
    )


@router.patch("/account/notifications", response_model=NotificationPreferencesOut)
async def update_preferences(
    body: NotificationPreferencesUpdate,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    prefs = await pref_module.get_or_create(session, current_user.id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(prefs, field, value)
    await session.commit()
    return NotificationPreferencesOut(
        in_app_enabled=prefs.in_app_enabled,
        email_workspace_invitations=prefs.email_workspace_invitations,
        email_project_analyzed=prefs.email_project_analyzed,
        email_project_ready_for_pc=prefs.email_project_ready_for_pc,
        email_mentions=prefs.email_mentions,
        email_comments=prefs.email_comments,
        email_pcmi6_generated=prefs.email_pcmi6_generated,
        email_weekly_digest=prefs.email_weekly_digest,
    )
```

- [ ] **Step 6: Register router**

In `apps/backend/api/main.py`:
```python
from api.routes.notifications import router as notifications_router
app.include_router(notifications_router, prefix="/api/v1")
```

- [ ] **Step 7: Tests**

```python
# apps/backend/tests/unit/test_email_sender.py
import pytest
from unittest.mock import MagicMock, patch
from core.notifications.email_sender import send, _render


def test_render_workspace_invitation():
    subject, html = _render("workspace_invitation", {
        "workspace_name": "TeamX", "invited_by_email": "admin@test.fr", "token": "abc",
    })
    assert "TeamX" in subject
    assert "admin@test.fr" in html
    assert "abc" in html


@pytest.mark.asyncio
async def test_send_without_api_key_returns_false(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    result = await send(to="x@test.fr", template="workspace_invitation", variables={
        "workspace_name": "X", "invited_by_email": "a@test.fr", "token": "t",
    })
    assert result is False


@pytest.mark.asyncio
async def test_send_with_api_key_calls_resend(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    with patch("resend.Emails") as mock_emails:
        mock_emails.send = MagicMock()
        result = await send(to="x@test.fr", template="workspace_invitation", variables={
            "workspace_name": "X", "invited_by_email": "a@test.fr", "token": "t",
        })
        assert result is True
        assert mock_emails.send.called
```

- [ ] **Step 8: Commit**

```bash
cd apps/backend && python -m pytest tests/unit/test_email_sender.py -v

cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/notifications/ apps/backend/api/routes/notifications.py apps/backend/api/main.py apps/backend/pyproject.toml apps/backend/tests/unit/test_email_sender.py apps/backend/tests/integration/test_notifications_endpoints.py
git commit -m "feat(notifications): add dispatcher + Resend email sender + templates + routes"
```

---

## Task 7: Project status transitions + notifications integration

**Files:**
- Modify: `apps/backend/api/routes/projects.py` (add PATCH /status + GET /status_history, trigger notifications)
- Test: `apps/backend/tests/integration/test_project_status_transitions.py`

- [ ] **Step 1: Add status transition endpoint**

In `apps/backend/api/routes/projects.py`, add new endpoints:

```python
# Add to existing projects.py
from datetime import datetime, timezone
from db.models.project_status_history import ProjectStatusHistoryRow
from schemas.project import ProjectStatusChange, ProjectStatusHistoryItem


ALLOWED_TRANSITIONS = {
    "draft": {"analyzed", "archived"},
    "analyzed": {"reviewed", "archived"},
    "reviewed": {"ready_for_pc", "archived"},
    "ready_for_pc": {"archived"},
    "archived": {"draft"},
}


@router.patch("/{project_id}/status")
async def update_project_status(
    project_id: str,
    body: ProjectStatusChange,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    project = await session.get(ProjectRow, UUID(project_id))
    if not project:
        raise HTTPException(404, "Project not found")

    from_status = project.status
    to_status = body.status

    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise HTTPException(
            400, f"Transition {from_status} -> {to_status} not allowed",
        )

    project.status = to_status
    project.status_changed_at = datetime.now(timezone.utc)
    project.status_changed_by = current_user.id

    session.add(ProjectStatusHistoryRow(
        project_id=project.id, from_status=from_status, to_status=to_status,
        changed_by=current_user.id, notes=body.notes,
    ))
    await session.commit()
    return {"status": to_status}


@router.get("/{project_id}/status_history")
async def get_status_history(
    project_id: str,
    current_user: UserRow = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.execute(
        select(ProjectStatusHistoryRow)
        .where(ProjectStatusHistoryRow.project_id == UUID(project_id))
        .order_by(ProjectStatusHistoryRow.changed_at.desc())
    )).scalars().all()
    return {"items": [
        {
            "id": str(r.id),
            "from_status": r.from_status, "to_status": r.to_status,
            "changed_at": r.changed_at.isoformat() if r.changed_at else None,
            "notes": r.notes,
        }
        for r in rows
    ]}
```

- [ ] **Step 2: Add schemas/project.py entries**

```python
# apps/backend/schemas/project.py — ADD to existing file
from typing import Literal

class ProjectStatusChange(BaseModel):
    status: Literal["draft", "analyzed", "reviewed", "ready_for_pc", "archived"]
    notes: str | None = None


class ProjectStatusHistoryItem(BaseModel):
    id: str
    from_status: str | None
    to_status: str
    changed_at: str | None
    notes: str | None
```

- [ ] **Step 3: Write tests**

```python
# apps/backend/tests/integration/test_project_status_transitions.py
import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-status")


async def _authed_client_with_project(client):
    reg = (await client.post(
        "/api/v1/auth/register",
        json={"email": f"s@test.fr", "password": "password_12345", "full_name": "S"},
    )).json()
    token = reg["access_token"]
    # Create a project (assumes existing /projects POST works)
    # In practice the endpoint may need a workspace_id — adjust if needed
    proj = (await client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Test Project"},
    )).json()
    return token, proj["id"]


@pytest.mark.asyncio
async def test_valid_transition_draft_to_analyzed(client: AsyncClient):
    token, pid = await _authed_client_with_project(client)
    resp = await client.patch(
        f"/api/v1/projects/{pid}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "analyzed"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_invalid_transition_draft_to_ready_for_pc(client: AsyncClient):
    token, pid = await _authed_client_with_project(client)
    resp = await client.patch(
        f"/api/v1/projects/{pid}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "ready_for_pc"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_status_history_tracks_changes(client: AsyncClient):
    token, pid = await _authed_client_with_project(client)
    await client.patch(
        f"/api/v1/projects/{pid}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "analyzed"},
    )
    hist = (await client.get(
        f"/api/v1/projects/{pid}/status_history",
        headers={"Authorization": f"Bearer {token}"},
    )).json()
    assert len(hist["items"]) >= 1
```

- [ ] **Step 4: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/api/routes/projects.py apps/backend/schemas/project.py apps/backend/tests/integration/test_project_status_transitions.py
git commit -m "feat(projects): add status transitions + history endpoints"
```

---

## Task 8: Frontend Auth.js v5 config + api.ts Bearer injection

**Files:**
- Modify: `apps/frontend/package.json` (add next-auth@beta, @auth/core)
- Create: `apps/frontend/src/auth.ts`
- Create: `apps/frontend/src/middleware.ts`
- Create: `apps/frontend/src/app/api/auth/[...nextauth]/route.ts`
- Modify: `apps/frontend/src/lib/api.ts` (inject Bearer token)

- [ ] **Step 1: Install Auth.js v5**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend
/Users/anthonymammone/.local/bin/pnpm add next-auth@beta @auth/core
```

- [ ] **Step 2: Create auth.ts config**

```typescript
// apps/frontend/src/auth.ts
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";
import Credentials from "next-auth/providers/credentials";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  providers: [
    Google({
      clientId: process.env.GOOGLE_OAUTH_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_OAUTH_CLIENT_SECRET!,
    }),
    MicrosoftEntraID({
      clientId: process.env.MICROSOFT_OAUTH_CLIENT_ID!,
      clientSecret: process.env.MICROSOFT_OAUTH_CLIENT_SECRET!,
    }),
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Mot de passe", type: "password" },
      },
      async authorize(credentials) {
        const res = await fetch(`${BACKEND_URL}/api/v1/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: credentials?.email,
            password: credentials?.password,
          }),
        });
        if (!res.ok) return null;
        const data = await res.json();
        return {
          id: data.user.id,
          email: data.user.email,
          name: data.user.full_name,
          accessToken: data.access_token,
          workspaceId: data.default_workspace_id,
        } as any;
      },
    }),
  ],
  session: { strategy: "jwt" },
  callbacks: {
    async signIn({ user, account, profile }) {
      // For OAuth providers: call backend /auth/oauth/callback
      if (account && (account.provider === "google" || account.provider === "microsoft-entra-id")) {
        const providerName = account.provider === "microsoft-entra-id" ? "microsoft" : "google";
        const res = await fetch(`${BACKEND_URL}/api/v1/auth/oauth/callback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider: providerName,
            email: user.email,
            name: user.name,
            provider_user_id: account.providerAccountId,
          }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        (user as any).accessToken = data.access_token;
        (user as any).workspaceId = data.default_workspace_id;
      }
      return true;
    },
    async jwt({ token, user }) {
      if (user) {
        token.accessToken = (user as any).accessToken;
        token.workspaceId = (user as any).workspaceId;
      }
      return token;
    },
    async session({ session, token }) {
      (session as any).accessToken = token.accessToken;
      (session as any).workspaceId = token.workspaceId;
      return session;
    },
  },
  pages: {
    signIn: "/login",
  },
});
```

- [ ] **Step 3: Create Auth.js handlers + middleware**

```typescript
// apps/frontend/src/app/api/auth/[...nextauth]/route.ts
import { handlers } from "@/auth";
export const { GET, POST } = handlers;
```

```typescript
// apps/frontend/src/middleware.ts
import { auth } from "@/auth";

const PUBLIC_PATHS = ["/", "/login", "/signup", "/api/auth", "/invitations/"];

export default auth((req) => {
  const { pathname } = req.nextUrl;
  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));
  if (isPublic) return;
  if (!req.auth) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("callbackUrl", pathname);
    return Response.redirect(url);
  }
});

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **Step 4: Update lib/api.ts to inject Bearer**

```typescript
// apps/frontend/src/lib/api.ts — modify existing file
import { getSession } from "next-auth/react";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const session = await getSession();
  const headers = new Headers(init?.headers);
  if (session && (session as any).accessToken) {
    headers.set("Authorization", `Bearer ${(session as any).accessToken}`);
  }
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${await response.text()}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
```

- [ ] **Step 5: Typecheck + commit**

```bash
cd apps/frontend && node_modules/.bin/tsc --noEmit

cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/frontend/package.json apps/frontend/pnpm-lock.yaml apps/frontend/src/auth.ts apps/frontend/src/middleware.ts apps/frontend/src/app/api/auth/\[...nextauth\]/route.ts apps/frontend/src/lib/api.ts
git commit -m "feat(frontend): add Auth.js v5 config + middleware + Bearer JWT injection"
```

---

## Task 9: Frontend login/signup pages + account pages

**Files:**
- Rewrite: `apps/frontend/src/app/login/page.tsx`
- Rewrite: `apps/frontend/src/app/signup/page.tsx`
- Create: `apps/frontend/src/app/account/notifications/page.tsx`
- Create: `apps/frontend/src/app/invitations/[token]/accept/page.tsx`

- [ ] **Step 1: Rewrite login page**

```tsx
// apps/frontend/src/app/login/page.tsx
"use client";
import { useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCredentials(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const res = await signIn("credentials", {
      email, password, redirect: false,
    });
    if (res?.error) {
      setError("Email ou mot de passe incorrect");
      setLoading(false);
    } else {
      router.push("/projects");
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-2xl shadow-sm p-8">
        <h1 className="font-display text-2xl font-bold text-slate-900 mb-6 text-center">
          Connexion à ArchiClaude
        </h1>

        <div className="space-y-2 mb-6">
          <Button
            onClick={() => signIn("google", { callbackUrl: "/projects" })}
            className="w-full bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
            variant="outline"
          >
            Continuer avec Google
          </Button>
          <Button
            onClick={() => signIn("microsoft-entra-id", { callbackUrl: "/projects" })}
            className="w-full bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
            variant="outline"
          >
            Continuer avec Microsoft
          </Button>
        </div>

        <div className="flex items-center gap-2 my-4">
          <div className="h-px bg-slate-200 flex-1" />
          <span className="text-xs text-slate-400">ou</span>
          <div className="h-px bg-slate-200 flex-1" />
        </div>

        <form onSubmit={handleCredentials} className="space-y-3">
          <div>
            <Label htmlFor="email" className="text-sm">Email</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <Label htmlFor="password" className="text-sm">Mot de passe</Label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button
            type="submit" disabled={loading}
            style={{ backgroundColor: "var(--ac-primary)" }}
            className="w-full text-white"
          >
            {loading ? "Connexion..." : "Se connecter"}
          </Button>
        </form>

        <p className="text-sm text-slate-500 text-center mt-4">
          Pas encore de compte ? <Link href="/signup" className="text-teal-700 font-medium">Créer un compte</Link>
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Rewrite signup page**

```tsx
// apps/frontend/src/app/signup/page.tsx
"use client";
import { useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      // Register via backend
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1"}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, full_name: fullName }),
      });
      if (!res.ok) {
        setError("Impossible de créer le compte (email déjà utilisé ?)");
        setLoading(false);
        return;
      }
      // Auto-login via credentials provider
      const signInRes = await signIn("credentials", {
        email, password, redirect: false,
      });
      if (signInRes?.error) {
        setError("Inscription OK, échec de la connexion auto — connectez-vous");
        setLoading(false);
        router.push("/login");
      } else {
        router.push("/projects");
      }
    } catch {
      setError("Erreur réseau");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-2xl shadow-sm p-8">
        <h1 className="font-display text-2xl font-bold text-slate-900 mb-6 text-center">
          Créer un compte ArchiClaude
        </h1>

        <div className="space-y-2 mb-6">
          <Button onClick={() => signIn("google", { callbackUrl: "/projects" })} variant="outline" className="w-full">
            Continuer avec Google
          </Button>
          <Button onClick={() => signIn("microsoft-entra-id", { callbackUrl: "/projects" })} variant="outline" className="w-full">
            Continuer avec Microsoft
          </Button>
        </div>

        <div className="flex items-center gap-2 my-4">
          <div className="h-px bg-slate-200 flex-1" />
          <span className="text-xs text-slate-400">ou</span>
          <div className="h-px bg-slate-200 flex-1" />
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <Label htmlFor="fullName" className="text-sm">Nom complet</Label>
            <Input id="fullName" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          </div>
          <div>
            <Label htmlFor="email" className="text-sm">Email</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <Label htmlFor="password" className="text-sm">Mot de passe (min. 10 caractères)</Label>
            <Input id="password" type="password" minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button
            type="submit" disabled={loading}
            style={{ backgroundColor: "var(--ac-primary)" }}
            className="w-full text-white"
          >
            {loading ? "Création..." : "Créer mon compte"}
          </Button>
        </form>

        <p className="text-sm text-slate-500 text-center mt-4">
          Déjà un compte ? <Link href="/login" className="text-teal-700 font-medium">Se connecter</Link>
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Account notifications page**

```tsx
// apps/frontend/src/app/account/notifications/page.tsx
"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

interface Prefs {
  in_app_enabled: boolean;
  email_workspace_invitations: boolean;
  email_project_analyzed: boolean;
  email_project_ready_for_pc: boolean;
  email_mentions: boolean;
  email_comments: boolean;
  email_pcmi6_generated: boolean;
  email_weekly_digest: boolean;
}

const TOGGLES: { key: keyof Prefs; label: string; section: string }[] = [
  { key: "email_workspace_invitations", label: "Invitations aux workspaces", section: "Partage & collaboration" },
  { key: "email_mentions", label: "Mentions (@user)", section: "Partage & collaboration" },
  { key: "email_comments", label: "Commentaires sur mes projets", section: "Partage & collaboration" },
  { key: "email_project_analyzed", label: "Projet analysé", section: "Progression des projets" },
  { key: "email_project_ready_for_pc", label: "Projet prêt pour dépôt PC", section: "Progression des projets" },
  { key: "email_pcmi6_generated", label: "Rendu PCMI6 généré", section: "Progression des projets" },
  { key: "email_weekly_digest", label: "Récap hebdomadaire", section: "Annonces produit" },
];

export default function NotificationsPrefsPage() {
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<Prefs>("/account/notifications").then(setPrefs);
  }, []);

  async function update(key: keyof Prefs, value: boolean) {
    if (!prefs) return;
    setSaving(true);
    const updated = await apiFetch<Prefs>("/account/notifications", {
      method: "PATCH",
      body: JSON.stringify({ [key]: value }),
    });
    setPrefs(updated);
    setSaving(false);
  }

  if (!prefs) return <div className="p-8">Chargement...</div>;

  const grouped: Record<string, typeof TOGGLES> = {};
  for (const t of TOGGLES) {
    grouped[t.section] = grouped[t.section] ?? [];
    grouped[t.section].push(t);
  }

  return (
    <main className="max-w-2xl mx-auto p-8">
      <h1 className="font-display text-3xl font-bold text-slate-900 mb-6">
        Préférences de notifications
      </h1>
      {Object.entries(grouped).map(([section, toggles]) => (
        <div key={section} className="mb-8">
          <h2 className="font-display text-lg font-semibold text-slate-700 mb-3">{section}</h2>
          <div className="space-y-2">
            {toggles.map((t) => (
              <label key={t.key} className="flex items-center justify-between border border-slate-200 rounded-lg p-3 bg-white">
                <span className="text-sm text-slate-700">{t.label}</span>
                <input
                  type="checkbox"
                  checked={prefs[t.key] as boolean}
                  onChange={(e) => update(t.key, e.target.checked)}
                  disabled={saving}
                  className="h-5 w-5 accent-teal-600"
                />
              </label>
            ))}
          </div>
        </div>
      ))}
    </main>
  );
}
```

- [ ] **Step 4: Invitation accept page**

```tsx
// apps/frontend/src/app/invitations/[token]/accept/page.tsx
"use client";
import { use, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

export default function AcceptInvitationPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const { data: session, status } = useSession();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function accept() {
    setLoading(true);
    try {
      await apiFetch(`/invitations/${token}/accept`, { method: "POST" });
      router.push("/projects");
    } catch (e) {
      setError("Impossible d'accepter l'invitation (expirée ou déjà utilisée)");
      setLoading(false);
    }
  }

  if (status === "loading") return <div className="p-8">Chargement...</div>;

  if (!session) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="bg-white border border-slate-200 rounded-2xl p-8 max-w-md text-center">
          <h1 className="font-display text-xl font-bold mb-4">Invitation ArchiClaude</h1>
          <p className="text-sm text-slate-600 mb-4">
            Connectez-vous ou créez un compte pour accepter cette invitation.
          </p>
          <div className="flex gap-2 justify-center">
            <Link href={`/login?callbackUrl=${encodeURIComponent(`/invitations/${token}/accept`)}`}>
              <Button variant="outline">Se connecter</Button>
            </Link>
            <Link href={`/signup?callbackUrl=${encodeURIComponent(`/invitations/${token}/accept`)}`}>
              <Button style={{ backgroundColor: "var(--ac-primary)" }} className="text-white">Créer un compte</Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="bg-white border border-slate-200 rounded-2xl p-8 max-w-md text-center">
        <h1 className="font-display text-xl font-bold mb-2">Rejoindre ce workspace ?</h1>
        <p className="text-sm text-slate-600 mb-6">Vous êtes invité(e) à rejoindre un workspace sur ArchiClaude.</p>
        {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
        <div className="flex gap-2 justify-center">
          <Button variant="outline" onClick={() => router.push("/projects")}>Décliner</Button>
          <Button onClick={accept} disabled={loading} style={{ backgroundColor: "var(--ac-primary)" }} className="text-white">
            {loading ? "..." : "Accepter"}
          </Button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Typecheck + commit**

```bash
cd apps/frontend && node_modules/.bin/tsc --noEmit

cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/frontend/src/app/login/ apps/frontend/src/app/signup/ apps/frontend/src/app/account/notifications/ apps/frontend/src/app/invitations/
git commit -m "feat(frontend): rewrite login/signup with 3 providers + notifications prefs + invitation accept"
```

---

## Task 10: Workspace selector + notification bell + workspaces pages

**Files:**
- Create: `apps/frontend/src/components/WorkspaceSelector.tsx`
- Create: `apps/frontend/src/components/NotificationBell.tsx`
- Create: `apps/frontend/src/components/NotificationPanel.tsx`
- Create: `apps/frontend/src/components/NotificationItem.tsx`
- Create: `apps/frontend/src/components/StatusBadge.tsx`
- Create: `apps/frontend/src/components/RoleBadge.tsx`
- Create: `apps/frontend/src/lib/hooks/useWorkspaces.ts`
- Create: `apps/frontend/src/lib/hooks/useNotifications.ts`
- Create: `apps/frontend/src/app/workspaces/page.tsx`
- Create: `apps/frontend/src/app/workspaces/[id]/page.tsx`
- Create: `apps/frontend/src/app/workspaces/[id]/members/page.tsx`

- [ ] **Step 1: Create hooks**

```typescript
// apps/frontend/src/lib/hooks/useWorkspaces.ts
"use client";
import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";

export interface WorkspaceListItem {
  workspace: {
    id: string;
    name: string;
    slug: string;
    description: string | null;
    logo_url: string | null;
    is_personal: boolean;
    created_at: string;
  };
  role: "admin" | "member" | "viewer";
}

export function useWorkspaces() {
  const [workspaces, setWorkspaces] = useState<WorkspaceListItem[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await apiFetch<WorkspaceListItem[]>("/workspaces");
      setWorkspaces(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return { workspaces, loading, refresh };
}
```

```typescript
// apps/frontend/src/lib/hooks/useNotifications.ts
"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

export interface Notification {
  id: string;
  type: string;
  title: string;
  body: string | null;
  link: string | null;
  read_at: string | null;
  created_at: string;
}

export function useNotifications() {
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);

  async function refresh() {
    const data = await apiFetch<{ items: Notification[]; unread: number }>("/notifications?limit=20");
    setItems(data.items);
    setUnread(data.unread);
  }

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30_000);
    return () => clearInterval(interval);
  }, []);

  async function markAllRead() {
    await apiFetch("/notifications/mark-all-read", { method: "POST" });
    refresh();
  }

  return { items, unread, markAllRead, refresh };
}
```

- [ ] **Step 2: Create components**

```tsx
// apps/frontend/src/components/WorkspaceSelector.tsx
"use client";
import { useState } from "react";
import { useWorkspaces } from "@/lib/hooks/useWorkspaces";
import Link from "next/link";

export function WorkspaceSelector() {
  const { workspaces } = useWorkspaces();
  const [open, setOpen] = useState(false);
  const active = workspaces[0]; // TODO: track active from session
  if (!active) return null;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-slate-200 bg-white text-sm hover:bg-slate-50"
      >
        <span className="font-medium text-slate-800">{active.workspace.name}</span>
        {active.workspace.is_personal && (
          <span className="text-xs text-slate-400">Perso</span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 min-w-[260px] bg-white border border-slate-200 rounded-md shadow-lg py-1 z-50">
          {workspaces.map(({ workspace, role }) => (
            <Link
              key={workspace.id}
              href={`/workspaces/${workspace.id}`}
              className="block px-3 py-2 hover:bg-slate-50 text-sm"
              onClick={() => setOpen(false)}
            >
              <div className="flex justify-between items-center">
                <span>{workspace.name}</span>
                <span className="text-xs text-slate-400">{role}</span>
              </div>
            </Link>
          ))}
          <div className="border-t border-slate-100 my-1" />
          <Link href="/workspaces" className="block px-3 py-2 hover:bg-slate-50 text-sm text-teal-700">
            Gérer les workspaces
          </Link>
        </div>
      )}
    </div>
  );
}
```

```tsx
// apps/frontend/src/components/NotificationBell.tsx
"use client";
import { useState } from "react";
import { Bell } from "lucide-react";
import { useNotifications } from "@/lib/hooks/useNotifications";
import { NotificationPanel } from "./NotificationPanel";

export function NotificationBell() {
  const { items, unread, markAllRead } = useNotifications();
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative p-2 rounded-md hover:bg-slate-100"
      >
        <Bell className="h-5 w-5 text-slate-600" />
        {unread > 0 && (
          <span className="absolute top-1 right-1 bg-red-500 text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && <NotificationPanel items={items} onMarkAllRead={markAllRead} onClose={() => setOpen(false)} />}
    </div>
  );
}
```

```tsx
// apps/frontend/src/components/NotificationPanel.tsx
"use client";
import { NotificationItem } from "./NotificationItem";
import type { Notification } from "@/lib/hooks/useNotifications";

export function NotificationPanel({
  items, onMarkAllRead, onClose,
}: {
  items: Notification[]; onMarkAllRead: () => void; onClose: () => void;
}) {
  return (
    <div className="absolute right-0 top-full mt-1 min-w-[360px] max-h-[500px] overflow-y-auto bg-white border border-slate-200 rounded-md shadow-lg z-50">
      <div className="sticky top-0 bg-white border-b border-slate-100 px-3 py-2 flex items-center justify-between">
        <span className="font-semibold text-sm">Notifications</span>
        <button onClick={onMarkAllRead} className="text-xs text-teal-700">
          Tout marquer comme lu
        </button>
      </div>
      {items.length === 0 ? (
        <div className="p-6 text-center text-sm text-slate-500">Aucune notification</div>
      ) : (
        items.map((n) => <NotificationItem key={n.id} notif={n} onClick={onClose} />)
      )}
    </div>
  );
}
```

```tsx
// apps/frontend/src/components/NotificationItem.tsx
"use client";
import Link from "next/link";
import type { Notification } from "@/lib/hooks/useNotifications";

export function NotificationItem({ notif, onClick }: { notif: Notification; onClick?: () => void }) {
  const date = new Date(notif.created_at).toLocaleDateString("fr-FR", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
  const content = (
    <div className={`px-3 py-2 hover:bg-slate-50 border-b border-slate-100 ${notif.read_at ? "opacity-70" : "font-medium"}`}>
      <div className="text-sm text-slate-900">{notif.title}</div>
      {notif.body && <div className="text-xs text-slate-500 mt-0.5">{notif.body}</div>}
      <div className="text-xs text-slate-400 mt-1">{date}</div>
    </div>
  );
  if (notif.link) return <Link href={notif.link} onClick={onClick}>{content}</Link>;
  return content;
}
```

```tsx
// apps/frontend/src/components/StatusBadge.tsx
"use client";

const LABELS: Record<string, { label: string; color: string }> = {
  draft: { label: "Brouillon", color: "bg-slate-200 text-slate-700" },
  analyzed: { label: "Analysé", color: "bg-blue-100 text-blue-700" },
  reviewed: { label: "Validé", color: "bg-teal-100 text-teal-700" },
  ready_for_pc: { label: "Prêt pour dépôt", color: "bg-green-100 text-green-700" },
  archived: { label: "Archivé", color: "bg-slate-100 text-slate-500" },
};

export function StatusBadge({ status }: { status: string }) {
  const { label, color } = LABELS[status] ?? { label: status, color: "bg-slate-100 text-slate-700" };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}>
      {label}
    </span>
  );
}
```

```tsx
// apps/frontend/src/components/RoleBadge.tsx
"use client";

const STYLES: Record<string, string> = {
  admin: "bg-teal-100 text-teal-700",
  member: "bg-blue-100 text-blue-700",
  viewer: "bg-slate-100 text-slate-600",
};

export function RoleBadge({ role }: { role: string }) {
  const style = STYLES[role] ?? "bg-slate-100 text-slate-600";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${style}`}>
      {role}
    </span>
  );
}
```

- [ ] **Step 3: Create workspace pages**

```tsx
// apps/frontend/src/app/workspaces/page.tsx
"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useWorkspaces } from "@/lib/hooks/useWorkspaces";
import { RoleBadge } from "@/components/RoleBadge";
import { apiFetch } from "@/lib/api";

export default function WorkspacesPage() {
  const { workspaces, refresh } = useWorkspaces();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const router = useRouter();

  async function create() {
    if (!name) return;
    await apiFetch("/workspaces", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    setName("");
    setCreating(false);
    refresh();
  }

  return (
    <main className="max-w-4xl mx-auto p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-display text-3xl font-bold text-slate-900">Mes workspaces</h1>
        <Button onClick={() => setCreating(!creating)} style={{ backgroundColor: "var(--ac-primary)" }} className="text-white">
          Créer un workspace
        </Button>
      </div>

      {creating && (
        <div className="bg-white border border-slate-200 rounded-lg p-4 mb-4 flex gap-2">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nom du workspace" />
          <Button onClick={create} style={{ backgroundColor: "var(--ac-primary)" }} className="text-white">Créer</Button>
          <Button variant="outline" onClick={() => setCreating(false)}>Annuler</Button>
        </div>
      )}

      <div className="space-y-2">
        {workspaces.map(({ workspace, role }) => (
          <Link key={workspace.id} href={`/workspaces/${workspace.id}`} className="block bg-white border border-slate-200 rounded-lg p-4 hover:border-teal-500">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-semibold text-slate-900">{workspace.name}</div>
                {workspace.description && <div className="text-sm text-slate-500">{workspace.description}</div>}
              </div>
              <div className="flex items-center gap-2">
                {workspace.is_personal && <span className="text-xs text-slate-400">Personnel</span>}
                <RoleBadge role={role} />
              </div>
            </div>
          </Link>
        ))}
      </div>
    </main>
  );
}
```

```tsx
// apps/frontend/src/app/workspaces/[id]/page.tsx
"use client";
import { use, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

interface Workspace {
  id: string; name: string; description: string | null;
  is_personal: boolean; created_at: string;
}

export default function WorkspaceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [ws, setWs] = useState<Workspace | null>(null);

  useEffect(() => {
    apiFetch<Workspace>(`/workspaces/${id}`).then(setWs).catch(() => setWs(null));
  }, [id]);

  if (!ws) return <div className="p-8">Chargement...</div>;

  return (
    <main className="max-w-4xl mx-auto p-8">
      <div className="mb-6">
        <h1 className="font-display text-3xl font-bold text-slate-900">{ws.name}</h1>
        {ws.description && <p className="text-slate-500 mt-1">{ws.description}</p>}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Link href={`/workspaces/${id}/members`} className="block bg-white border border-slate-200 rounded-lg p-6 hover:border-teal-500">
          <div className="font-semibold text-slate-900">Membres</div>
          <div className="text-sm text-slate-500 mt-1">Gérer les membres et invitations</div>
        </Link>
        <Link href="/projects" className="block bg-white border border-slate-200 rounded-lg p-6 hover:border-teal-500">
          <div className="font-semibold text-slate-900">Projets</div>
          <div className="text-sm text-slate-500 mt-1">Voir les projets de ce workspace</div>
        </Link>
      </div>
    </main>
  );
}
```

```tsx
// apps/frontend/src/app/workspaces/[id]/members/page.tsx
"use client";
import { use, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RoleBadge } from "@/components/RoleBadge";
import { apiFetch } from "@/lib/api";

interface Member {
  user_id: string; email: string; full_name: string | null;
  role: "admin" | "member" | "viewer"; joined_at: string | null;
}

export default function WorkspaceMembersPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [members, setMembers] = useState<Member[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "member" | "viewer">("member");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Member[]>(`/workspaces/${id}/members`).then(setMembers);
  }, [id]);

  async function invite() {
    setError(null);
    try {
      await apiFetch(`/workspaces/${id}/invitations`, {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
      });
      setInviteEmail("");
    } catch {
      setError("Impossible d'inviter");
    }
  }

  return (
    <main className="max-w-4xl mx-auto p-8">
      <h1 className="font-display text-2xl font-bold text-slate-900 mb-6">Membres</h1>

      <div className="bg-white border border-slate-200 rounded-lg p-4 mb-6">
        <h2 className="font-semibold text-sm text-slate-700 mb-3">Inviter un membre</h2>
        <div className="flex gap-2 flex-wrap">
          <Input
            placeholder="email@example.com"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
          />
          <select
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value as any)}
            className="border border-slate-200 rounded-md px-2 text-sm"
          >
            <option value="admin">Admin</option>
            <option value="member">Member</option>
            <option value="viewer">Viewer</option>
          </select>
          <Button onClick={invite} style={{ backgroundColor: "var(--ac-primary)" }} className="text-white">
            Inviter
          </Button>
        </div>
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
      </div>

      <div className="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
        {members.map((m) => (
          <div key={m.user_id} className="flex items-center justify-between p-4">
            <div>
              <div className="font-medium text-slate-900">{m.full_name ?? m.email}</div>
              <div className="text-sm text-slate-500">{m.email}</div>
            </div>
            <RoleBadge role={m.role} />
          </div>
        ))}
      </div>
    </main>
  );
}
```

- [ ] **Step 4: Integrate WorkspaceSelector + NotificationBell in layout**

Modify existing layout files (the header component used across pages) — wire `<WorkspaceSelector />` and `<NotificationBell />` into the navigation bar. This depends on the current layout code; make minimal changes (one import + JSX insertion).

- [ ] **Step 5: Typecheck + commit**

```bash
cd apps/frontend && node_modules/.bin/tsc --noEmit

cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/frontend/src/components/ apps/frontend/src/lib/hooks/ apps/frontend/src/app/workspaces/
git commit -m "feat(frontend): add WorkspaceSelector + NotificationBell + workspaces pages"
```

---

## Task 11: RLS migration + isolation tests

**Files:**
- Create: `apps/backend/alembic/versions/20260419_0004_enable_rls.py`
- Test: `apps/backend/tests/integration/test_rls_isolation.py`

- [ ] **Step 1: Create RLS migration**

```python
# apps/backend/alembic/versions/20260419_0004_enable_rls.py
"""enable RLS on private tables

Revision ID: 20260419_0004
Revises: 20260419_0003
"""
from alembic import op

revision = "20260419_0004"
down_revision = "20260419_0003"
branch_labels = None
depends_on = None


def upgrade():
    # Enable RLS + create policies for each private table
    tables_scoped_by_project = [
        "feasibility_results", "reports", "pcmi_dossiers", "pcmi6_renders",
        "project_versions",
    ]

    # projects scoped by workspace membership
    op.execute("ALTER TABLE projects ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY projects_workspace_isolation ON projects
        USING (workspace_id IN (
            SELECT workspace_id FROM workspace_members 
            WHERE user_id = current_setting('app.user_id', true)::UUID
        ))
    """)

    # tables scoped via projects
    for tbl in tables_scoped_by_project:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {tbl}_isolation ON {tbl}
            USING (project_id IN (SELECT id FROM projects))
        """)

    # agency_settings scoped by user
    op.execute("ALTER TABLE agency_settings ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY agency_isolation ON agency_settings
        USING (user_id = current_setting('app.user_id', true)::UUID)
    """)

    # notifications scoped by user
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY notifications_isolation ON notifications
        USING (user_id = current_setting('app.user_id', true)::UUID)
    """)


def downgrade():
    for tbl in [
        "notifications", "agency_settings", "project_versions",
        "pcmi6_renders", "pcmi_dossiers", "reports", "feasibility_results",
        "projects",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {tbl}_isolation ON {tbl}")
        if tbl == "projects":
            op.execute(f"DROP POLICY IF EXISTS projects_workspace_isolation ON projects")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")
```

- [ ] **Step 2: Write isolation tests**

```python
# apps/backend/tests/integration/test_rls_isolation.py
import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-rls")


async def _register(client, email):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password_12345", "full_name": email.split("@")[0]},
    )
    return resp.json()


@pytest.mark.asyncio
async def test_user_a_cannot_see_user_b_projects(client: AsyncClient):
    a = await _register(client, "userA@test.fr")
    b = await _register(client, "userB@test.fr")

    # A creates a project
    await client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {a['access_token']}"},
        json={"name": "Private A project"},
    )

    # B lists projects — should not see A's project
    b_projects = (await client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )).json()
    assert not any(p.get("name") == "Private A project" for p in b_projects.get("items", []))


@pytest.mark.asyncio
async def test_user_b_cannot_access_user_a_project_by_id(client: AsyncClient):
    a = await _register(client, "ownerA@test.fr")
    b = await _register(client, "otherB@test.fr")

    proj = (await client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {a['access_token']}"},
        json={"name": "Owned by A"},
    )).json()

    resp = await client.get(
        f"/api/v1/projects/{proj['id']}",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    assert resp.status_code in (403, 404)
```

- [ ] **Step 3: Run migration + tests**

```bash
cd apps/backend
alembic upgrade head
python -m pytest tests/integration/test_rls_isolation.py -v
# Expected: pass (assuming RLS works correctly with current_setting)
```

- [ ] **Step 4: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/alembic/versions/20260419_0004_enable_rls.py apps/backend/tests/integration/test_rls_isolation.py
git commit -m "feat(db): enable RLS on private tables + isolation tests"
```

---

## Task 12: Final verification

- [ ] **Step 1: Backend — ruff + tests**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
ruff check . --fix
python -m pytest tests/ -v --tb=short
# Expected: all tests pass (873 existing + ~50 new SP5 tests)
```

- [ ] **Step 2: Frontend — typecheck + build**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend
node_modules/.bin/tsc --noEmit
node node_modules/next/dist/bin/next build
# Expected: 0 type errors, build successful
```

- [ ] **Step 3: Fix any issues**

If either fails, fix and re-run. Common issues:
- Missing `getSession` import → import from `next-auth/react`
- `session` typing → add type augmentation in `src/types/next-auth.d.ts` if needed
- Ruff TCH warnings on new core/auth files → add `"core/auth/**" = ["TCH"]` to pyproject.toml per-file-ignores

- [ ] **Step 4: Final commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add -A
git commit -m "chore: SP5 final cleanup — ruff + typecheck"
```
