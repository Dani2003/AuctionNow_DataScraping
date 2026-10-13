"""
Notification handlers for pipeline events.

Dispatches Slack webhook notifications on run completion (success or failure)
when a webhook URL is configured.
"""
from __future__ import annotations

import os

import httpx

from pipeline.logger import get_logger

logger = get_logger("pipeline.notifications")


def send_slack_notification(webhook_url: str | None, message: str) -> bool:
    """
    Send a message to a Slack incoming webhook.
    Returns True if sent, False if skipped or failed.
    Never raises an exception — notification failure must never crash the scrape run.
    """
    # Check config parameter first, fallback to environment variable
    url = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")
    if not url or not url.strip():
        logger.debug("No Slack webhook URL configured; skipping notification.")
        return False

    url = url.strip()
    payload = {"text": message}

    try:
        logger.info("Dispatching Slack notification to webhook...")
        resp = httpx.post(url, json=payload, timeout=10.0)
        if resp.status_code == 200:
            logger.info("Slack notification delivered successfully.")
            return True
        logger.warning("Slack notification returned non-200 status: %d (%s)", resp.status_code, resp.text)
        return False
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to send Slack notification: %s", e)
        return False
