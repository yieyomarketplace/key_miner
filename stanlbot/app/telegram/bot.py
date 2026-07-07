# app/telegram/bot.py
"""
Bot and Dispatcher initialization.
"""
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

bot = Bot(
    token=settings.TELEGRAM_BOT_TOKEN.get_secret_value(),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# Import handlers AFTER bot and dp are defined to break circular imports
from app.telegram.handlers import start, messages, documents, callbacks, workflows, student

# Register routers. Order matters: specific callbacks first, then FSM workflows, then general messages.
dp.include_router(callbacks.router)
dp.include_router(workflows.router)
dp.include_router(student.router)
dp.include_router(documents.router)
dp.include_router(start.router)
dp.include_router(messages.router)

async def set_webhook() -> bool:
    try:
        webhook_url = str(settings.WEBHOOK_URL).rstrip('/') + "/webhook"
        success = await bot.set_webhook(
            url=webhook_url,
            secret_token=settings.TELEGRAM_WEBHOOK_SECRET.get_secret_value(),
            allowed_updates=["message", "callback_query"]
        )
        return success
    except Exception as e:
        logger.exception(f"Failed to set webhook: {e}")
        return False

async def delete_webhook() -> bool:
    try:
        return await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.exception(f"Failed to delete webhook: {e}")
        return False