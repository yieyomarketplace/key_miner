# app/telegram/handlers/callbacks.py
"""
Handles inline keyboard callback queries.
Implements the "Glassy" UI navigation, Media Engine downloads, SOS actions, and dynamic actions.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.exceptions import TelegramBadRequest

from app.telegram.keyboards import (
    MenuNav, TaskAction, MediaAction, SOSAction,
    get_main_dashboard, get_back_button, get_task_list_keyboard, 
    get_student_keyboard, get_sos_keyboard
)
from app.core.database import db
from app.services.media_service import media_engine
from app.services.rag_service import save_document
from app.services.student_service import start_pomodoro_session, get_due_flashcards

logger = logging.getLogger(__name__)
router = Router()

async def safe_edit_message(callback: CallbackQuery, text: str, reply_markup=None):
    """Safely edits a message, ignoring errors if the message content hasn't changed."""
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logger.warning(f"Failed to edit message: {e}")

# ==============================================================================
# Media Engine Callbacks
# ==============================================================================

@router.callback_query(MediaAction.filter())
async def handle_media_actions(callback: CallbackQuery, callback_data: MediaAction):
    url = callback_data.url
    action = callback_data.action
    
    if action == "video":
        await callback.answer("Downloading best quality video... This may take a minute.")
        file_path = await media_engine.download_media(url, "best_video")
        if file_path:
            try:
                await callback.message.answer_video(video=FSInputFile(file_path), caption="Here is your video.")
            finally:
                media_engine.cleanup_file(file_path)
        else:
            await callback.message.answer("Failed to download video.")
            
    elif action == "audio":
        await callback.answer("Extracting audio... This may take a minute.")
        file_path = await media_engine.download_media(url, "mp3_audio")
        if file_path:
            try:
                await callback.message.answer_audio(audio=FSInputFile(file_path), caption="Here is your audio.")
            finally:
                media_engine.cleanup_file(file_path)
        else:
            await callback.message.answer("Failed to extract audio.")
            
    elif action == "720p":
        await callback.answer("Downloading 720p video... This may take a minute.")
        file_path = await media_engine.download_media(url, "720p_video")
        if file_path:
            try:
                await callback.message.answer_video(video=FSInputFile(file_path), caption="Here is your 720p video.")
            finally:
                media_engine.cleanup_file(file_path)
        else:
            await callback.message.answer("Failed to download 720p video.")
            
    elif action == "index":
        await callback.answer("Indexing URL content to Knowledge Base...")
        metadata = await media_engine.extract_metadata(url)
        if metadata:
            title = metadata.get('title', url)
            description = metadata.get('description', 'No description available.')
            text_to_index = f"Title: {title}\n\nDescription: {description}\n\nURL: {url}"
            result = await save_document(callback.from_user.id, title, "url_index", text_to_index, {"source_url": url})
            await callback.message.answer(result)
        else:
            await callback.message.answer("Failed to extract content from this URL.")

# ==============================================================================
# Student & SOS Callbacks
# ==============================================================================

@router.callback_query(F.data.startswith("pomodoro_"))
async def handle_pomodoro_callback(callback: CallbackQuery):
    duration = int(callback.data.split("_")[1])
    await start_pomodoro_session(callback.from_user.id, duration)
    await callback.message.answer(f"Focus session started. Deep work for {duration} minutes.")
    await callback.answer()

@router.callback_query(F.data == "review_cards")
async def handle_review_cards(callback: CallbackQuery):
    cards = await get_due_flashcards(callback.from_user.id, limit=3)
    if not cards:
        await callback.message.answer("No flashcards due for review right now.")
    else:
        text = "<b>Flashcard Review:</b>\n\n"
        for card_id, subject, front, back in cards:
            text += f"<b>Subject:</b> {subject}\n<b>Front:</b> {front}\n<i>(Back: {back})</i>\n\n"
        await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

@router.callback_query(SOSAction.filter())
async def handle_sos_actions(callback: CallbackQuery, callback_data: SOSAction):
    action = callback_data.action
    user_id = callback.from_user.id
    await callback.answer()
    
    if action == "focus":
        await start_pomodoro_session(user_id, 50)
        await callback.message.answer("SOS: 50-minute deep work session started. Distractions blocked.")
    elif action == "clear":
        await db.execute(
            "UPDATE tasks SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE user_id = ? AND status = 'pending' AND date(due_date) = date('now')",
            (user_id,)
        )
        await callback.message.answer("All tasks due today have been marked as completed.")
    elif action == "summary":
        await callback.message.answer("Summarizing recent documents... (Feature in progress)")
    elif action == "backup":
        await callback.message.answer("Backing up CRM contacts... (Feature in progress)")

# ==============================================================================
# Standard UI Navigation Callbacks
# ==============================================================================

@router.callback_query(MenuNav.filter())
async def handle_menu_navigation(callback: CallbackQuery, callback_data: MenuNav):
    section = callback_data.section
    page = callback_data.page
    
    await callback.answer()
    
    if section == "dashboard":
        await safe_edit_message(callback, "<b>LifeOS Control Panel</b>\nSelect a module:", get_main_dashboard())
        
    elif section == "rag":
        text = (
            "<b>Knowledge Base (RAG)</b>\n\n"
            "Forward PDFs, images, or text documents to index them.\n"
            "Use the /find command to search your indexed knowledge."
        )
        await safe_edit_message(callback, text, get_back_button())
        
    elif section == "finance":
        text = (
            "<b>Financial Hub</b>\n\n"
            "Forward transaction SMS messages to automatically log expenses.\n"
            "Use the /wealth command to view your financial summary."
        )
        await safe_edit_message(callback, text, get_back_button())
        
    elif section == "crm":
        text = (
            "<b>Network CRM</b>\n\n"
            "Forward emails, LinkedIn messages, or contact details to build your network graph.\n"
            "The system will automatically extract contact info and log interactions."
        )
        await safe_edit_message(callback, text, get_back_button())
        
    elif section == "tasks":
        limit = 5
        offset = page * limit
        
        tasks = await db.execute(
            "SELECT id, title, priority FROM tasks WHERE user_id = ? AND status = 'pending' ORDER BY priority DESC, due_date ASC LIMIT ? OFFSET ?",
            (callback.from_user.id, limit, offset),
            fetch=True
        )
        
        total_tasks = await db.execute(
            "SELECT COUNT(*) FROM tasks WHERE user_id = ? AND status = 'pending'",
            (callback.from_user.id,),
            fetch=True
        )
        total_count = total_tasks[0][0] if total_tasks else 0
        total_pages = max(1, (total_count + limit - 1) // limit)
        
        if not tasks:
            text = "<b>Workflow Tasks</b>\n\nNo pending tasks found. Type your tasks naturally to add them."
            await safe_edit_message(callback, text, get_back_button())
        else:
            text = f"<b>Workflow Tasks</b> (Page {page + 1}/{total_pages})\n\nSelect a task to manage:"
            keyboard = get_task_list_keyboard(tasks, page, total_pages)
            await safe_edit_message(callback, text, keyboard)

    elif section == "media":
        text = (
            "<b>Media Engine</b>\n\n"
            "Paste any URL from YouTube, TikTok, Twitter, or Instagram.\n"
            "The system will extract metadata and allow you to download the video, "
            "extract the audio, or index the content directly into your Knowledge Base."
        )
        await safe_edit_message(callback, text, get_back_button())

    elif section == "workflows":
        text = (
            "<b>Workflow Engine (n8n-style)</b>\n\n"
            "Build custom automations using a conversational canvas.\n"
            "Use /newworkflow to start building, or /listworkflows to manage existing flows."
        )
        await safe_edit_message(callback, text, get_back_button())

    elif section == "student":
        text = "<b>Student & SOS Suite</b>\n\nSelect a productivity tool or emergency action:"
        await safe_edit_message(callback, text, get_student_keyboard())

    elif section == "sos_actions":
        text = "<b>SOS Quick Actions</b>\n\nSelect an emergency action to execute immediately:"
        await safe_edit_message(callback, text, get_sos_keyboard())
            
    elif section == "settings":
        text = (
            "<b>System Settings</b>\n\n"
            "Configuration management is currently handled via environment variables.\n"
            "Contact the system administrator to modify core settings."
        )
        await safe_edit_message(callback, text, get_back_button())

@router.callback_query(TaskAction.filter())
async def handle_task_actions(callback: CallbackQuery, callback_data: TaskAction):
    await callback.answer()
    task_id = callback_data.task_id
    user_id = callback.from_user.id
    
    if callback_data.action == "view":
        task = await db.execute(
            "SELECT title, description, priority, due_date, status FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
            fetch=True
        )
        if not task:
            await callback.message.answer("Task not found or access denied.")
            return
            
        title, desc, priority, due_date, status = task[0]
        text = (
            f"<b>Task Details</b>\n\n"
            f"<b>Title:</b> {title}\n"
            f"<b>Priority:</b> {priority}\n"
            f"<b>Status:</b> {status}\n"
            f"<b>Due Date:</b> {due_date or 'Not set'}\n\n"
            f"<b>Description:</b>\n{desc or 'No description provided.'}"
        )
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Mark Complete", callback_data=TaskAction(action="complete", task_id=task_id).pack()),
                InlineKeyboardButton(text="Back", callback_data=MenuNav(section="tasks").pack())
            ]
        ])
        await safe_edit_message(callback, text, keyboard)
        
    elif callback_data.action == "complete":
        await db.execute("UPDATE tasks SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?", (task_id, user_id))
        await callback.message.answer("Task marked as completed.")
        await handle_menu_navigation(callback, MenuNav(section="tasks", page=0))