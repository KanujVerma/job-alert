from __future__ import annotations
import time
import logging

logger = logging.getLogger(__name__)


def run_loop(run_fn, interval_minutes: int = 15) -> None:
    """Call run_fn() every interval_minutes. Blocks forever. Logs on exception."""
    while True:
        try:
            run_fn()
        except Exception as e:
            logger.error(f"Run cycle failed: {e}", exc_info=True)
        logger.info(f"Sleeping {interval_minutes}m until next cycle")
        time.sleep(interval_minutes * 60)
