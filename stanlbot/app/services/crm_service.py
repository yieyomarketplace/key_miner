# app/services/crm_service.py
"""
Customer Relationship Management (CRM) service.
Handles contact extraction, interaction logging, and follow-up scheduling.
"""
import json
import logging
from datetime import datetime
from typing import List, Dict, Any

from app.core.database import db
from app.ai.brain import brain

logger = logging.getLogger(__name__)

async def process_interaction(user_id: int, text: str) -> str:
    """
    Analyzes text to extract contact info and interaction details,
    then saves it to the CRM database.
    """
    try:
        messages = [
            {
                "role": "system", 
                "content": (
                    "You are a CRM data extraction assistant. Analyze the provided text and extract "
                    "contact information and interaction details. Return a valid JSON object with the following keys: "
                    "'contact_name' (string), 'company' (string, optional), 'email' (string, optional), "
                    "'phone' (string, optional), 'interaction_summary' (string, 1-2 sentences), "
                    "'sentiment_score' (float between -1.0 and 1.0), 'follow_up_required' (boolean)."
                )
            },
            {"role": "user", "content": text}
        ]
        
        raw_response = await brain.generate_text(messages, temperature=0.1)
        clean_response = raw_response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)

        contact_name = data.get("contact_name", "Unknown Contact")
        company = data.get("company")
        email = data.get("email")
        phone = data.get("phone")
        summary = data.get("interaction_summary", text[:100])
        sentiment = data.get("sentiment_score", 0.0)
        follow_up = data.get("follow_up_required", False)

        # Upsert contact
        existing = await db.execute(
            "SELECT id FROM contacts WHERE user_id = ? AND name = ?",
            (user_id, contact_name),
            fetch=True
        )

        if existing:
            contact_id = existing[0][0]
            await db.execute(
                """
                UPDATE contacts 
                SET company = COALESCE(?, company), 
                    email = COALESCE(?, email), 
                    phone = COALESCE(?, phone),
                    context_summary = ?, 
                    relationship_score = ?, 
                    last_interaction = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (company, email, phone, summary, max(0.1, min(1.0, (sentiment + 1) / 2)), contact_id)
            )
        else:
            contact_id = await db.execute(
                """
                INSERT INTO contacts (user_id, name, company, email, phone, context_summary, relationship_score, last_interaction)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (user_id, contact_name, company, email, phone, summary, max(0.1, min(1.0, (sentiment + 1) / 2)))
            )

        # Log the interaction
        await db.execute(
            """
            INSERT INTO interactions (contact_id, user_id, interaction_type, summary, sentiment, raw_data)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (contact_id, user_id, "text_message", summary, sentiment, text)
        )

        # Create follow-up task if required
        if follow_up:
            await db.execute(
                """
                INSERT INTO follow_ups (user_id, contact_id, task_description, due_date)
                VALUES (?, ?, ?, datetime('now', '+3 days'))
                """,
                (user_id, contact_id, f"Follow up with {contact_name} regarding recent interaction.")
            )

        logger.info(f"CRM interaction processed for contact '{contact_name}' (ID: {contact_id}).")
        return f"Interaction with {contact_name} logged successfully. Context updated."

    except json.JSONDecodeError:
        logger.error("Failed to parse CRM JSON from brain.")
        return "I could not extract structured contact information from that message."
    except Exception as e:
        logger.exception(f"Error processing CRM interaction: {e}")
        return "An error occurred while updating your network intelligence."

async def get_contact_summary(user_id: int, contact_name: str) -> str:
    """
    Retrieves a summary of a specific contact, including recent interactions.
    """
    try:
        contact = await db.execute(
            "SELECT id, name, company, context_summary, relationship_score FROM contacts WHERE user_id = ? AND name LIKE ?",
            (user_id, f"%{contact_name}%"),
            fetch=True
        )

        if not contact:
            return f"No contact found matching the name '{contact_name}'."

        c_id, c_name, c_company, c_context, c_score = contact[0]
        
        interactions = await db.execute(
            "SELECT summary, sentiment, created_at FROM interactions WHERE contact_id = ? ORDER BY created_at DESC LIMIT 3",
            (c_id,),
            fetch=True
        )

        summary_text = f"Contact: {c_name}"
        if c_company:
            summary_text += f" at {c_company}"
        summary_text += f"\nRelationship Score: {c_score:.2f}\nContext: {c_context}\n\nRecent Interactions:\n"
        
        for i in interactions:
            summary_text += f"- [{i[2]}] {i[0]} (Sentiment: {i[1]:.2f})\n"

        return summary_text.strip()

    except Exception as e:
        logger.exception(f"Error fetching contact summary: {e}")
        return "An error occurred while retrieving the contact information."

async def process_follow_ups() -> List[str]:
    """
    Checks for overdue follow-ups and generates reminder messages.
    Intended to be called by the autonomous cron job.
    """
    reminders = []
    try:
        overdue = await db.execute(
            """
            SELECT f.id, f.user_id, f.task_description, c.name 
            FROM follow_ups f
            LEFT JOIN contacts c ON f.contact_id = c.id
            WHERE f.is_completed = 0 AND f.due_date <= CURRENT_TIMESTAMP
            """,
            fetch=True
        )

        if not overdue:
            return reminders

        for item in overdue:
            f_id, user_id, task_desc, contact_name = item
            
            messages = [
                {
                    "role": "system", 
                    "content": "You are a professional assistant. Generate a concise, polite reminder for the user about an overdue task."
                },
                {
                    "role": "user", 
                    "content": f"Task: {task_desc}. Contact: {contact_name if contact_name else 'N/A'}."
                }
            ]
            
            reminder_text = await brain.generate_text(messages, temperature=0.5)
            reminders.append(f"Reminder for User {user_id}: {reminder_text}")
            
            # Mark as notified to prevent spamming
            await db.execute("UPDATE follow_ups SET is_completed = 1 WHERE id = ?", (f_id,))

        return reminders

    except Exception as e:
        logger.exception(f"Error processing follow-ups: {e}")
        return reminders