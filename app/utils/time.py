from datetime import datetime, timezone


def utcnow():
    """Naive UTC for portable MariaDB DATETIME storage; convert at boundaries."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
