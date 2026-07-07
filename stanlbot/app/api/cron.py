# app/api/cron.py
"""
Autonomous Cron endpoints.
Triggered by external services (e.g., Cron-job.org) to run background tasks.
Secured via a shared secret to prevent unauthorized execution.
"""
import logging
from fastapi import APIRouter, Request, HTTPException, status

from app.core.config import get_settings
from app.telegram.bot import bot
from app.services.crm_service import process_follow_ups
from app.services.finance_service import update_market_sentiment, check_market_alerts
from app.services.task_service import get_daily_brief
from app.core.database import db

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

def verify_cron_secret(request: Request):
    """Verifies the cron secret passed in the headers or query params."""
    # In production, use a dedicated CRON_SECRET. Here we reuse the webhook secret for simplicity,
    # but ideally, you'd add CRON_SECRET: SecretStr to your config.
    expected_secret = settings.TELEGRAM_WEBHOOK_SECRET.get_secret_value()
    
    # Check header first
    header_secret = request.headers.get("X-Cron-Secret")
    if header_secret and header_secret == expected_secret:
        return
        
    # Check query param as fallback
    query_secret = request.query_params.get("secret")
    if query_secret and query_secret == expected_secret:
        return
        
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, 
        detail="Invalid or missing cron secret"
    )

@router.get("/cron/morning_brief", include_in_schema=False)
async def morning_brief(request: Request):
    """Generates and sends the daily morning brief to all active users."""
    verify_cron_secret(request)
    logger.info("Executing morning brief cron job.")
    
    try:
        users = await db.execute("SELECT tg_id FROM users", fetch=True)
        sent_count = 0
        
        for user_row in users:
            user_id = user_row[0]
            try:
                brief_text = await get_daily_brief(user_id)
                await bot.send_message(user_id, brief_text)
                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send morning brief to user {user_id}: {e}")
                
        logger.info(f"Morning brief sent to {sent_count} users.")
        return {"status": "success", "users_notified": sent_count}
        
    except Exception as e:
        logger.exception("Error in morning brief cron job.")
        raise HTTPException(status_code=500, detail="Internal server error during brief generation")

@router.get("/cron/market_tick", include_in_schema=False)
async def market_tick(request: Request):
    """Updates market sentiment and checks for triggered alerts."""
    verify_cron_secret(request)
    logger.info("Executing market tick cron job.")
    
    try:
        # 1. Update sentiment scores
        await update_market_sentiment()
        
        # 2. Check for triggered alerts
        triggered_alerts = await check_market_alerts()
        
        # 3. Notify users of triggered alerts
        notified_users = set()
        for alert_msg in triggered_alerts:
            # Extract user_id from the message (assuming format: "Alert for User {user_id}: ...")
            # In a production system, return structured data from check_market_alerts instead of parsing strings.
            try:
                user_id = int(alert_msg.split("User ")[1].split(":")[0])
                await bot.send_message(user_id, alert_msg)
                notified_users.add(user_id)
            except (IndexError, ValueError) as e:
                logger.error(f"Failed to parse user ID from alert message: {alert_msg}")
                
        logger.info(f"Market tick completed. {len(triggered_alerts)} alerts triggered, {len(notified_users)} users notified.")
        return {"status": "success", "alerts_triggered": len(triggered_alerts)}
        
    except Exception as e:
        logger.exception("Error in market tick cron job.")
        raise HTTPException(status_code=500, detail="Internal server error during market update")

@router.get("/cron/follow_ups", include_in_schema=False)
async def follow_up_tick(request: Request):
    """Checks for overdue CRM follow-ups and notifies users."""
    verify_cron_secret(request)
    logger.info("Executing follow-up check cron job.")
    
    try:
        reminders = await process_follow_ups()
        
        notified_users = set()
        for reminder_msg in reminders:
            try:
                user_id = int(reminder_msg.split("User ")[1].split(":")[0])
                await bot.send_message(user_id, reminder_msg)
                notified_users.add(user_id)
            except (IndexError, ValueError) as e:
                logger.error(f"Failed to parse user ID from reminder message: {reminder_msg}")
                
        logger.info(f"Follow-up check completed. {len(reminders)} reminders sent.")
        return {"status": "success", "reminders_sent": len(reminders)}
        
    except Exception as e:
        logger.exception("Error in follow-up cron job.")
        raise HTTPException(status_code=500, detail="Internal server error during follow-up check")