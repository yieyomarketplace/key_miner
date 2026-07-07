# app/telegram/handlers/student.py
"""
Student Suite and SOS Handlers.
"""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from app.services.student_service import start_pomodoro_session, create_flashcard, get_due_flashcards, get_sos_actions

logger = logging.getLogger(__name__)
router = Router()

@router.message(Command("pomodoro"))
async def cmd_pomodoro(message: Message):
    parts = message.text.split(maxsplit=1)
    duration = 25
    if len(parts) > 1:
        try:
            duration = int(parts[1])
        except ValueError:
            await message.answer("Invalid duration. Usage: /pomodoro [minutes]")
            return
            
    await start_pomodoro_session(message.from_user.id, duration)
    await message.answer(f"Focus session started. Deep work for {duration} minutes. Distractions blocked.")

@router.message(Command("flashcard"))
async def cmd_flashcard(message: Message):
    # Simple implementation: /flashcard Subject | Front | Back
    parts = message.text.split("|")
    if len(parts) < 3:
        await message.answer("Usage: /flashcard Subject | Front Text | Back Text")
        return
        
    subject = parts[0].split(maxsplit=1)[1].strip()
    front = parts[1].strip()
    back = parts[2].strip()
    
    await create_flashcard(message.from_user.id, subject, front, back)
    await message.answer(f"Flashcard added to '{subject}' deck.")

@router.message(Command("review"))
async def cmd_review(message: Message):
    cards = await get_due_flashcards(message.from_user.id, limit=3)
    if not cards:
        await message.answer("No flashcards due for review right now. Great job!")
        return
        
    text = "<b>Flashcard Review:</b>\n\n"
    for card_id, subject, front, back in cards:
        text += f"<b>Subject:</b> {subject}\n<b>Front:</b> {front}\n<i>(Back: {back})</i>\n\n"
        
    await message.answer(text, parse_mode="HTML")

@router.message(Command("sos"))
async def cmd_sos(message: Message):
    actions = await get_sos_actions()
    keyboard = []
    for key, desc in actions.items():
        keyboard.append([InlineKeyboardButton(text=f"Execute: {key.replace('_', ' ').title()}", callback_data=f"sos_{key}")])
        
    text = "<b>SOS Quick Actions</b>\n\nSelect an emergency action to execute immediately:"
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

# Note: Callback handlers for 'sos_' actions would be added to callbacks.py to execute the specific logic.