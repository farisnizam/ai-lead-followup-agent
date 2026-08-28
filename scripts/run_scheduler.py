"""Polls for due follow-ups and fires the agent for each. Run this alongside
`uvicorn` in a separate process - it is deliberately not wired into the
FastAPI app's lifespan (see docs/dev-log.md, Milestone 3) so the test suite's
TestClient never starts a background poller.

Usage: python -m scripts.run_scheduler
"""

import logging
import time

from app.agent.client import get_agent_client
from app.agent.followups import process_due_followups
from app.config import settings
from app.db import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run() -> None:
    client = get_agent_client()
    logger.info("Scheduler started, polling every %ss", settings.scheduler_poll_interval_seconds)

    while True:
        db = SessionLocal()
        try:
            decisions = process_due_followups(db, client)
            if decisions:
                logger.info("Processed %d due followup(s)", len(decisions))
        except Exception:
            logger.exception("Scheduler iteration failed")
        finally:
            db.close()

        time.sleep(settings.scheduler_poll_interval_seconds)


if __name__ == "__main__":
    run()
