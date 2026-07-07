# app/telegram/handlers/messages.py
"""
Handles standard text messages, URL detection for Media Engine, and AI routing.
"""
import logging
import re
from aiogram import Router, F
from aiogram.types import Message

from app.services.router_service import process_user_input
from app.services.media_service import media_engine
from app.telegram.keyboards import get_media_keyboard

logger = logging.getLogger(__name__)
router = Router()

# Regex to detect URLs
URL_PATTERN = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')

@router.message(F.text & ~F.text.startswith('/'))
async def handle_text_message(message: Message):
    user_id = message.from_user.id
    text = message.text
    
    # 1. Check for URLs (Media Engine)
    urls = URL_PATTERN.findall(text)
    if urls:
        url = urls[0]
        processing_msg = await message.answer("URL detected. Fetching metadata...")
        
        metadata = await media_engine.extract_metadata(url)
        if metadata:
            title = metadata.get('title', 'Unknown Title')
            keyboard = get_media_keyboard(url)
            await processing_msg.edit_text(f"<b>{title}</b>\nSelect an action:", parse_mode="HTML", reply_markup=keyboard)
            return
        else:
            await processing_msg.edit_text("Could not extract metadata from this URL. It may be unsupported or private.")
            return

    # 2. Standard AI Routing with UX feedback
    processing_msg = await message.answer("Processing...")
    
    try:
        response = await process_user_input(user_id, text)
        
        if len(response) > 4000:
            response = response[:4000] + "\n\n[Message truncated due to length limits]"
            
        await processing_msg.edit_text(response)
        
    except Exception as e:
        logger.exception(f"Error handling text message for user {user_id}: {e}")
        await processing_msg.edit_text("An internal error occurred. Please try again.")

@router.message(F.text & F.text.startswith('/'))
async def handle_unknown_command(message: Message):
    command = message.text.split()[0].lower()
    logger.warning(f"Unknown command received: {command} from user {message.from_user.id}")
    await message.answer(
        f"Unrecognized command: <code>{command}</code>\n"
        "Type /help to see available commands."
    )