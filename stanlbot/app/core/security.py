# app/core/security.py
"""
Security utilities, specifically for validating Telegram Webhook requests
using HMAC SHA256 to prevent unauthorized webhook triggers.
"""
import hmac
import logging
from fastapi import Request, HTTPException, status
from app.core.config import get_settings

logger = logging.getLogger(__name__)

def verify_telegram_webhook(request: Request) -> None:
    """
    Validates the X-Telegram-Bot-Api-Secret-Token header.
    Raises HTTPException 403 if the token is missing or invalid.
    Uses hmac.compare_digest to prevent timing attacks.
    """
    settings = get_settings()
    secret_token_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    
    if not secret_token_header:
        logger.warning("Webhook request missing secret token header.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Missing webhook secret token"
        )
        
    expected_secret = settings.TELEGRAM_WEBHOOK_SECRET.get_secret_value()
    
    if not hmac.compare_digest(secret_token_header, expected_secret):
        logger.warning("Webhook request has invalid secret token.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Invalid webhook secret token"
        )