"""Tiny in-process background queue for slow side effects (emails).

Keeps slow third-party calls out of the request/response cycle. Jobs start
only after the surrounding DB transaction commits. For multi-server setups
with heavy volume, replace ``run_in_background`` with Celery/RQ — callers
stay the same.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections, transaction


logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dqd-bg")


def _run(func, args, kwargs):
    close_old_connections()
    try:
        func(*args, **kwargs)
    except Exception:
        logger.exception("Background job %s failed", getattr(func, "__name__", func))
    finally:
        close_old_connections()


def run_in_background(func, *args, **kwargs):
    transaction.on_commit(lambda: _executor.submit(_run, func, args, kwargs))
