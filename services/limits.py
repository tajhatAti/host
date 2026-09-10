"""Fingerprint- and IP-level resource limiting (master prompt §4).

Why not simply count rows in `jobs`?
------------------------------------
The `jobs` table has no `status` column — job state is owned by the runner
process, which knows what is actually alive. A previous implementation queried
`j.status IN ('running', ...)` and therefore raised
`OperationalError: no such column: j.status` on every job start that carried a
fingerprint, silently disabling the "primary defense" it claimed to provide.

So the count is computed by intersecting:
  * DB rows  — which account owns which runner job, and
  * runner   — which of those runner jobs are actually running right now.

Cluster membership
------------------
A device is identified by its fingerprint hash. Accounts belong to the same
cluster when they share that hash on `users.fingerprint` OR have ever logged in
from it (`sessions.fingerprint`) — so creating a second account via a different
auth method does not escape the limit.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("codenest.limits")

# §4: 3 concurrent jobs per DEVICE (not per account).
FINGERPRINT_JOB_LIMIT = int(os.getenv("FINGERPRINT_JOB_LIMIT", "3"))
# §4: a deliberately generous per-IP aggregate so shared households, offices,
# universities and CGNAT mobile networks are not punished, while obvious
# multi-device farming on one connection still trips.
IP_JOB_LIMIT = int(os.getenv("IP_JOB_LIMIT", "9"))

_ACTIVE_STATES = ("running", "starting", "installing", "restarting")


def running_runner_ids() -> set:
    """runner_job_ids the runner reports as currently alive.

    Returns an empty set when the runner is unreachable; callers then fall back
    to the per-account limit rather than blocking every user during an outage.
    """
    try:
        from services import runner_client
        # Fleet-wide: asking only worker #1 would miss every job placed on an
        # overflow worker, and an abuse limit that cannot see half the jobs is
        # not a limit.
        return {
            jid for jid, j in runner_client.fleet_jobs().items()
            if str(j.get("status", "")).lower() in _ACTIVE_STATES
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("limits: runner unreachable (%s) — skipping cluster check", exc)
        return set()


def cluster_user_ids(conn, fingerprint: str = "", ip: str = "") -> set:
    """Every account tied to this device fingerprint and/or IP."""
    ids = set()
    if fingerprint:
        for sql in (
            "SELECT id AS uid FROM users WHERE fingerprint = ?",
            "SELECT DISTINCT user_id AS uid FROM sessions WHERE fingerprint = ?",
        ):
            try:
                for r in conn.execute(sql, (fingerprint,)).fetchall():
                    ids.add(dict(r)["uid"])
            except Exception as exc:  # noqa: BLE001 — e.g. pre-migration sessions table
                logger.debug("cluster_user_ids: %s", exc)
    if ip:
        for sql in (
            "SELECT id AS uid FROM users WHERE last_ip = ?",
            "SELECT DISTINCT user_id AS uid FROM sessions WHERE ip_address = ?",
        ):
            try:
                for r in conn.execute(sql, (ip,)).fetchall():
                    ids.add(dict(r)["uid"])
            except Exception as exc:  # noqa: BLE001
                logger.debug("cluster_user_ids: %s", exc)
    ids.discard(None)
    return ids


def count_running_for_users(conn, user_ids: set, live_ids: set) -> int:
    """How many of `user_ids`' jobs are actually running right now."""
    if not user_ids or not live_ids:
        return 0
    placeholders = ",".join("?" for _ in user_ids)
    rows = conn.execute(
        f"SELECT runner_job_id FROM jobs WHERE user_id IN ({placeholders})",
        tuple(user_ids),
    ).fetchall()
    return sum(1 for r in rows if dict(r).get("runner_job_id") in live_ids)


def check_job_quota(conn, user_id: int, fingerprint: str, ip: str) -> None:
    """Raise HTTPException(429) when this device or network is at its cap.

    Enforced server-side on every job-start request; the client is never
    trusted to police itself.
    """
    from fastapi import HTTPException

    live = running_runner_ids()
    if not live:
        return  # runner down or nothing running — per-account limit still applies

    if fingerprint:
        device_users = cluster_user_ids(conn, fingerprint=fingerprint)
        device_users.add(user_id)
        used = count_running_for_users(conn, device_users, live)
        if used >= FINGERPRINT_JOB_LIMIT:
            extra = ""
            if len(device_users) > 1:
                extra = (f" This counts all {len(device_users)} accounts used on "
                         f"this device.")
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Your device already has the maximum number of RunSpace jobs "
                    f"running ({used}/{FINGERPRINT_JOB_LIMIT}) — stop one before "
                    f"starting another.{extra}"
                ),
            )

    if ip:
        ip_users = cluster_user_ids(conn, ip=ip)
        ip_users.add(user_id)
        used_ip = count_running_for_users(conn, ip_users, live)
        if used_ip >= IP_JOB_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"This network already has the maximum number of RunSpace jobs "
                    f"running ({used_ip}/{IP_JOB_LIMIT}) across all accounts on it — "
                    f"stop one before starting another."
                ),
            )
