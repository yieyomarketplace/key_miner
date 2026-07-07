# app/telegram/handlers/start.py
"""
Handles initialization commands: /start, /dashboard, /help, and module commands.
"""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

from app.core.database import db
from app.telegram.keyboards import get_main_dashboard
from app.services import rag_service, finance_service, task_service, router_service

logger = logging.getLogger(__name__)
router = Router()

WELCOME_MESSAGE = (
    "<b>Welcome to LifeOS</b>\n\n"
    "Your centralized AI operating system for knowledge management, "
    "financial tracking, network intelligence, workflow automation, and media processing.\n\n"
    "Use the dashboard below to navigate, or simply forward messages, "
    "documents, and URLs directly to this chat."
)

HELP_MESSAGE = (
    "<b>LifeOS Command Reference</b>\n\n"
    "<b>Core Commands:</b>\n"
    "/dashboard - Open the main control panel.\n"
    "/chat [message] - Force a general conversation with the AI.\n\n"
    "<b>Knowledge & CRM:</b>\n"
    "/find [query] - Search your knowledge base.\n\n"
    "<b>Finance:</b>\n"
    "/wealth - View financial summary.\n\n"
    "<b>Workflows & Tasks:</b>\n"
    "/tasks - View pending workflow tasks.\n"
    "/newworkflow - Build an n8n-style automation.\n"
    "/listworkflows - View and run your automations.\n\n"
    "<b>Student & SOS:</b>\n"
    "/pomodoro [minutes] - Start a focus session.\n"
    "/flashcard Subject | Front | Back - Create a flashcard.\n"
    "/review - Review due flashcards.\n"
    "/sos - Access emergency quick actions.\n\n"
    "<b>Automatic Processing:</b>\n"
    "- Paste a URL (YouTube, TikTok, etc.) to download media.\n"
    "- Forward SMS messages to log expenses.\n"
    "- Forward emails/messages to update your CRM.\n"
    "- Send PDFs or images to index them in your knowledge base."
)

@router.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    try:
        await db.execute(
            "INSERT OR IGNORE INTO users (tg_id, full_name, username) VALUES (?, ?, ?)",
            (user.id, user.full_name, user.username)
        )
        logger.info(f"Registered/Verified user: {user.id} ({user.full_name})")
    except Exception as e:
        logger.exception(f"Failed to register user {user.id}: {e}")

    await message.answer(WELCOME_MESSAGE, reply_markup=get_main_dashboard())

@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message):
    await message.answer("<b>LifeOS Control Panel</b>\nSelect a module:", reply_markup=get_main_dashboard())

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_MESSAGE)

@router.message(Command("find"))
async def cmd_find(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /find <search query>")
        return
    
    processing_msg = await message.answer("Searching your knowledge base...")
    result = await rag_service.search_documents(message.from_user.id, parts[1])
    await processing_msg.edit_text(result)

@router.message(Command("wealth"))
async def cmd_wealth(message: Message):
    processing_msg = await message.answer("Calculating financial summary...")
    result = await finance_service.get_financial_summary(message.from_user.id)
    await processing_msg.edit_text(result)

@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    processing_msg = await message.answer("Generating workflow brief...")
    result = await task_service.get_daily_brief(message.from_user.id)
    await processing_msg.edit_text(result)

@router.message(Command("chat"))
async def cmd_chat(message: Message):
    """Forces the router into general chat mode, bypassing intent routing."""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /chat <your message>")
        return
    
    processing_msg = await message.answer("Thinking...")
    result = await router_service.process_user_input(message.from_user.id, parts[1], force_chat=True)
    await processing_msg.edit_text(result)