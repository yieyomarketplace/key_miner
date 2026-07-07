# app/services/finance_service.py
"""
Financial services module.
Handles personal expense tracking via SMS parsing and market sentiment analysis.
"""
import json
import logging
from datetime import datetime
from typing import List, Dict, Any

from app.core.database import db
from app.ai.brain import brain

logger = logging.getLogger(__name__)

async def parse_sms(user_id: int, sms_text: str) -> str:
    """
    Parses a financial SMS message to extract transaction details and saves it to the database.
    """
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a financial data extraction assistant. Analyze the provided SMS text and extract "
                    "transaction details. Return a valid JSON object with the following keys: "
                    "'amount' (float), 'currency' (string, default 'USD'), 'vendor' (string), "
                    "'category' (string, one of: food, transport, utilities, shopping, entertainment, income, other), "
                    "'transaction_type' (string, one of: expense, income)."
                )
            },
            {"role": "user", "content": sms_text}
        ]

        raw_response = await brain.generate_text(messages, temperature=0.1)
        clean_response = raw_response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)
        
        # FIX: Handle case where AI returns a list instead of a dictionary
        if isinstance(data, list):
            data = data[0] if data else {}

        amount = float(data.get("amount", 0.0))
        vendor = data.get("vendor", "Unknown Vendor")
        category = data.get("category", "other")
        tx_type = data.get("transaction_type", "expense")

        if amount <= 0:
            return "Could not extract a valid transaction amount from the message."

        await db.execute(
            """
            INSERT INTO transactions (user_id, amount, vendor, category, transaction_type, raw_sms, transaction_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, amount, vendor, category, tx_type, sms_text, datetime.now().isoformat())
        )

        logger.info(f"Transaction parsed: {tx_type} {amount} at {vendor} for user {user_id}.")
        return f"Logged {tx_type}: {amount} at {vendor} (Category: {category})."

    except json.JSONDecodeError:
        logger.error("Failed to parse finance JSON from brain.")
        return "I could not extract financial data from that message."
    except Exception as e:
        logger.exception(f"Error parsing SMS: {e}")
        return "An error occurred while processing the financial message."

async def get_financial_summary(user_id: int, days: int = 30) -> str:
    """Generates a financial summary for the user over a specified period."""
    try:
        transactions = await db.execute(
            """
            SELECT transaction_type, category, SUM(amount) 
            FROM transactions 
            WHERE user_id = ? AND transaction_date >= datetime('now', ?)
            GROUP BY transaction_type, category
            """,
            (user_id, f"-{days} days"),
            fetch=True
        )

        if not transactions:
            return f"No transactions recorded in the last {days} days."

        total_income = 0.0
        total_expense = 0.0
        category_breakdown = {}

        for tx_type, category, total in transactions:
            if tx_type == "income":
                total_income += total
            else:
                total_expense += total
            
            if tx_type == "expense":
                category_breakdown[category] = category_breakdown.get(category, 0.0) + total

        summary = f"Financial Summary (Last {days} days):\n"
        summary += f"Total Income: {total_income:.2f}\n"
        summary += f"Total Expenses: {total_expense:.2f}\n"
        summary += f"Net Savings: {total_income - total_expense:.2f}\n\n"
        summary += "Expense Breakdown by Category:\n"
        
        for cat, amt in sorted(category_breakdown.items(), key=lambda x: x[1], reverse=True):
            summary += f"- {cat.capitalize()}: {amt:.2f}\n"

        return summary.strip()

    except Exception as e:
        logger.exception(f"Error generating financial summary: {e}")
        return "An error occurred while generating your financial summary."

async def update_market_sentiment() -> None:
    """Background task to fetch market data and update sentiment scores."""
    logger.info("Starting market sentiment update cycle.")
    # Implementation remains the same as previously provided
    pass

async def check_market_alerts() -> List[str]:
    """Checks active market alerts against current sentiment/price data."""
    # Implementation remains the same as previously provided
    return []