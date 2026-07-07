# app/telegram/keyboards.py
"""
UI layouts, inline keyboards, CallbackData factories, and text formatting utilities.
Implements the "Glassy" UI pattern using structured callback data and dynamic message editing.
"""
from typing import List, Tuple, Any
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ==============================================================================
# Callback Data Factories (Ensures type safety and clean callback parsing)
# ==============================================================================

class MenuNav(CallbackData, prefix="menu"):
    """Handles main menu and sub-menu navigation."""
    section: str
    page: int = 0

class TaskAction(CallbackData, prefix="task"):
    """Handles task-specific actions."""
    action: str  # 'view', 'complete', 'delete'
    task_id: int

class MediaAction(CallbackData, prefix="media"):
    """Handles Media Engine download and indexing actions."""
    action: str  # 'video', 'audio', '720p', 'index'
    url: str

class SOSAction(CallbackData, prefix="sos"):
    """Handles Student Suite SOS quick actions."""
    action: str  # 'focus', 'summary', 'clear', 'backup'

# ==============================================================================
# Keyboard Builders
# ==============================================================================

def get_main_dashboard() -> InlineKeyboardMarkup:
    """Generates the main dashboard keyboard with all system modules."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Knowledge Base (RAG)", callback_data=MenuNav(section="rag"))
    builder.button(text="Financial Hub", callback_data=MenuNav(section="finance"))
    builder.button(text="Network CRM", callback_data=MenuNav(section="crm"))
    builder.button(text="Workflow Tasks", callback_data=MenuNav(section="tasks"))
    builder.button(text="Media Engine", callback_data=MenuNav(section="media"))
    builder.button(text="Workflows (n8n)", callback_data=MenuNav(section="workflows"))
    builder.button(text="Student & SOS", callback_data=MenuNav(section="student"))
    builder.button(text="System Settings", callback_data=MenuNav(section="settings"))
    builder.adjust(2, 2, 2, 2) # 2 columns per row
    return builder.as_markup()

def get_back_button(section: str = "dashboard") -> InlineKeyboardMarkup:
    """Generates a standardized back button."""
    builder = InlineKeyboardBuilder()
    button_text = "Back to Dashboard" if section == "dashboard" else f"Back to {section.capitalize()}"
    builder.button(text=button_text, callback_data=MenuNav(section=section))
    return builder.as_markup()

def get_media_keyboard(url: str) -> InlineKeyboardMarkup:
    """Generates action buttons for the Media Engine when a URL is detected."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Download Best Video (MP4)", callback_data=MediaAction(action="video", url=url))
    builder.button(text="Extract Audio (MP3)", callback_data=MediaAction(action="audio", url=url))
    builder.button(text="Download 720p Video", callback_data=MediaAction(action="720p", url=url))
    builder.button(text="Index to Knowledge Base", callback_data=MediaAction(action="index", url=url))
    builder.adjust(1)
    return builder.as_markup()

def get_student_keyboard() -> InlineKeyboardMarkup:
    """Generates the Student Suite productivity tools keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Start Pomodoro (25m)", callback_data="pomodoro_25")
    builder.button(text="Start Pomodoro (50m)", callback_data="pomodoro_50")
    builder.button(text="Review Flashcards", callback_data="review_cards")
    builder.button(text="SOS Quick Actions", callback_data=MenuNav(section="sos_actions"))
    builder.adjust(2, 2)
    builder.row(InlineKeyboardButton(text="Back to Dashboard", callback_data=MenuNav(section="dashboard").pack()))
    return builder.as_markup()

def get_sos_keyboard() -> InlineKeyboardMarkup:
    """Generates the SOS emergency quick-actions keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Deep Focus (50m)", callback_data=SOSAction(action="focus"))
    builder.button(text="Summarize Recent Docs", callback_data=SOSAction(action="summary"))
    builder.button(text="Clear Today's Tasks", callback_data=SOSAction(action="clear"))
    builder.button(text="Backup CRM Contacts", callback_data=SOSAction(action="backup"))
    builder.adjust(2, 2)
    builder.row(InlineKeyboardButton(text="Back to Student", callback_data=MenuNav(section="student").pack()))
    return builder.as_markup()

def get_task_list_keyboard(tasks: List[Tuple[Any, ...]], page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Generates a paginated keyboard for a list of tasks."""
    builder = InlineKeyboardBuilder()
    
    for task in tasks:
        task_id = task[0]
        title = task[1]
        priority = task[2]
        display_title = (title[:35] + "...") if len(title) > 35 else title
        button_text = f"[P{priority}] {display_title}"
        builder.button(text=button_text, callback_data=TaskAction(action="view", task_id=task_id))
        
    builder.adjust(1)
    
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="Previous", callback_data=MenuNav(section="tasks_list", page=page-1).pack()))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="Next", callback_data=MenuNav(section="tasks_list", page=page+1).pack()))
        if nav_buttons:
            builder.row(*nav_buttons)
            
    builder.row(InlineKeyboardButton(text="Back to Dashboard", callback_data=MenuNav(section="dashboard").pack()))
    return builder.as_markup()