"""Bounded retention for operational analytics and deployment history."""
from datetime import datetime, timedelta, timezone
import logging
import os

logger = logging.getLogger("codenest.retention")


def cleanup():
    from database import get_db_connection
    now = datetime.now(timezone.utc)
    bot_days = max(7, int(os.getenv("BOT_EVENT_RETENTION_DAYS", "180")))
    deploy_days = max(30, int(os.getenv("DEPLOY_EVENT_RETENTION_DAYS", "365")))
    conn = get_db_connection()
    try:
        a = conn.execute("DELETE FROM bot_events WHERE created_at < ?",
                         ((now - timedelta(days=bot_days)).strftime("%Y-%m-%d %H:%M:%S"),))
        b = conn.execute("DELETE FROM job_deploy_events WHERE created_at < ?",
                         ((now - timedelta(days=deploy_days)).strftime("%Y-%m-%d %H:%M:%S"),))
        conn.commit()
        removed = int(getattr(a, "rowcount", 0) or 0) + int(getattr(b, "rowcount", 0) or 0)
        if removed:
            logger.info("Removed %d expired analytics/deployment event(s)", removed)
        return removed
    finally:
        conn.close()
