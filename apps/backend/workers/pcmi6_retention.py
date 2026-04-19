"""ARQ cron worker for PCMI6 retention (purge after 365 days)."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

RETENTION_DAYS = 365


async def purge_old_renders(ctx):
    """Purge renders older than RETENTION_DAYS days where selected_for_pc = false.

    For v1 this is a stub — full impl requires R2 client + DB session.
    """
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    logger.info(f"PCMI6 retention purge: cutoff={cutoff.isoformat()}")
    return {"status": "done", "purged_count": 0}
