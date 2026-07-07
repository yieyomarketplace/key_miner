# app/api/webhooks.py
"""
Telegram Webhook endpoint.
Receives updates, validates security, and offloads processing to the background.
"""
import logging
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException, status
from aiogram.types import Update

from app.telegram.bot import bot, dp
from app.core.security import verify_telegram_webhook

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/webhook", include_in_schema=False)
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives Telegram updates.
    1. Validates the webhook secret.
    2. Parses the update.
    3. Offloads processing to a background task to return 200 OK immediately.
    """
    # 1. Security Validation
    verify_telegram_webhook(request)
    
    # 2. Parse Update
    try:
        data = await request.json()
        update = Update(**data)
    except Exception as e:
        logger.error(f"Failed to parse Telegram update: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid update payload")

    # 3. Background Processing
    # We use a wrapper to catch exceptions so they don't crash the background worker silently
    async def process_update_safe():
        try:
            await dp.feed_update(bot, update)
        except Exception as e:
            logger.exception(f"Error processing update {update.update_id}: {e}")

    background_tasks.add_task(process_update_safe)
    
    # Return immediately to prevent Telegram timeouts
    return {"ok": True}