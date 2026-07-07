# app/services/task_service.py
"""
Workflow and Task management service.
Handles task extraction from natural language, prioritization, and daily briefings.
"""
import json
import logging
from datetime import datetime
from typing import List, Dict, Any

from app.core.database import db
from app.ai.brain import brain

logger = logging.getLogger(__name__)

async def extract_tasks(user_id: int, text: str) -> str:
    """
    Extracts actionable tasks from natural language text and saves them to the database.
    """
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a productivity assistant. Analyze the provided text and extract actionable tasks. "
                    "Return a valid JSON array of objects. Each object must have the following keys: "
                    "'title' (string, concise task description), 'priority' (integer 1-5, where 5 is highest), "
                    "'due_date' (string, ISO 8601 format YYYY-MM-DD, or null if no specific date)."
                )
            },
            {"role": "user", "content": text}
        ]

        raw_response = await brain.generate_text(messages, temperature=0.2)
        clean_response = raw_response.replace("```json", "").replace("```", "").strip()
        
        if clean_response.startswith("{"):
            data = json.loads(clean_response)
            tasks = data.get("tasks", [])
        else:
            tasks = json.loads(clean_response)

        if not tasks:
            return "No actionable tasks were identified in the text."

        inserted_count = 0
        for task in tasks:
            title = task.get("title")
            if not title:
                continue
                
            priority = int(task.get("priority", 3))
            due_date = task.get("due_date")

            await db.execute(
                """
                INSERT INTO tasks (user_id, title, priority, due_date, status, source_type)
                VALUES (?, ?, ?, ?, 'pending', 'text_input')
                """,
                (user_id, title, priority, due_date)
            )
            inserted_count += 1

        logger.info(f"Extracted and saved {inserted_count} tasks for user {user_id}.")
        return f"Successfully added {inserted_count} task(s) to your workflow."

    except json.JSONDecodeError:
        logger.error("Failed to parse tasks JSON from brain.")
        return "I could not extract structured tasks from that text."
    except Exception as e:
        logger.exception(f"Error extracting tasks: {e}")
        return "An error occurred while processing your tasks."

async def get_daily_brief(user_id: int) -> str:
    """
    Generates a prioritized daily brief of tasks and follow-ups.
    """
    try:
        tasks = await db.execute(
            """
            SELECT title, priority, due_date 
            FROM tasks 
            WHERE user_id = ? AND status = 'pending'
            ORDER BY priority DESC, due_date ASC NULLS LAST
            LIMIT 10
            """,
            (user_id,),
            fetch=True
        )

        if not tasks:
            return "You have no pending tasks in your workflow today."

        brief_context = "Pending Tasks:\n"
        for title, priority, due_date in tasks:
            brief_context += f"- [Priority {priority}] {title}"
            if due_date:
                brief_context += f" (Due: {due_date})"
            brief_context += "\n"

        messages = [
            {
                "role": "system",
                "content": "You are a professional executive assistant. Generate a concise, motivating, and highly prioritized morning brief based on the provided tasks. Focus on what needs immediate attention."
            },
            {"role": "user", "content": brief_context}
        ]

        brief_text = await brain.generate_text(messages, temperature=0.5)
        return f"Good morning. Here is your daily brief:\n\n{brief_text}"

    except Exception as e:
        logger.exception(f"Error generating daily brief: {e}")
        return "An error occurred while generating your daily brief."

async def update_task_status(user_id: int, task_title_keyword: str, new_status: str) -> str:
    """
    Updates the status of a task based on a keyword search in the title.
    """
    try:
        task = await db.execute(
            "SELECT id, title FROM tasks WHERE user_id = ? AND status != 'completed' AND title LIKE ?",
            (user_id, f"%{task_title_keyword}%"),
            fetch=True
        )

        if not task:
            return f"No pending tasks found matching '{task_title_keyword}'."

        task_id, title = task[0]
        
        completed_at = datetime.now().isoformat() if new_status == "completed" else None

        await db.execute(
            "UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?",
            (new_status, completed_at, task_id)
        )

        logger.info(f"Task {task_id} status updated to {new_status} for user {user_id}.")
        return f"Task '{title}' has been marked as {new_status}."

    except Exception as e:
        logger.exception(f"Error updating task status: {e}")
        return "An error occurred while updating the task status."