# app/services/student_service.py
"""
Student Suite: Pomodoro tracking, spaced repetition flashcards, and SOS actions.
"""
import json
import logging
from datetime import datetime, timedelta
from app.core.database import db

logger = logging.getLogger(__name__)

async def start_pomodoro_session(user_id: int, duration_minutes: int = 25) -> int:
    end_time = datetime.utcnow() + timedelta(minutes=duration_minutes)
    session_id = await db.execute(
        "INSERT INTO pomodoro_sessions (user_id, duration_minutes) VALUES (?, ?)",
        (user_id, duration_minutes)
    )
    
    # Also create a high-priority task to block distractions
    await db.execute(
        "INSERT INTO tasks (user_id, title, description, priority, due_date, status, source_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, f"Pomodoro Focus ({duration_minutes}m)", "Deep work session. Block distractions.", 
         5, end_time.isoformat(), "in_progress", "pomodoro")
    )
    return session_id

async def create_flashcard(user_id: int, subject: str, front: str, back: str) -> int:
    card_id = await db.execute(
        "INSERT INTO flashcards (user_id, subject, front_text, back_text, next_review) VALUES (?, ?, ?, ?, ?)",
        (user_id, subject, front, back, datetime.utcnow().isoformat())
    )
    return card_id

async def get_due_flashcards(user_id: int, limit: int = 10) -> list:
    return await db.execute(
        "SELECT id, subject, front_text, back_text FROM flashcards WHERE user_id = ? AND next_review <= ? ORDER BY next_review ASC LIMIT ?",
        (user_id, datetime.utcnow().isoformat(), limit),
        fetch=True
    )

async def get_sos_actions() -> dict[str, str]:
    return {
        "sos_focus": "Start a 50-minute deep work Pomodoro session immediately.",
        "sos_summary": "Instantly summarize the last 5 documents indexed in the knowledge base.",
        "sos_clear": "Mark all tasks due today as completed to clear mental clutter.",
        "sos_backup": "Trigger an immediate export of all CRM contacts to a CSV file."
    }