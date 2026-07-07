# app/services/router_service.py
"""
Central routing service. Analyzes user input via the AI Brain and delegates 
execution to the appropriate domain-specific service.
"""
import json
import logging
from typing import Any, Dict, List

from app.ai.brain import brain
from app.services import rag_service, crm_service, finance_service, task_service

logger = logging.getLogger(__name__)

# In-memory conversation history for General Chat (max 5 turns per user)
conversation_history: Dict[int, List[Dict[str, str]]] = {}

async def process_user_input(user_id: int, text: str, context: str = "", force_chat: bool = False) -> str:
    """
    Main entry point for processing text input.
    Routes the input to the correct service based on AI intent analysis.
    """
    try:
        # If forced into chat mode, skip routing
        if not force_chat:
            intent_raw = await brain.route_intent(text, context)
            
            if isinstance(intent_raw, str):
                intent = json.loads(intent_raw)
            else:
                intent = intent_raw
                
            module = intent.get("module", "general_chat")
            action = intent.get("action", "chat")
            confidence = intent.get("confidence", 0.0)
            entities = intent.get("extracted_entities", {})

            logger.info(f"Routing intent: module={module}, action={action}, confidence={confidence}")

            if module == "brain_rag":
                if action == "search":
                    return await rag_service.search_documents(user_id, text)
                return "Please specify what you want to search for in your documents."

            elif module == "finance_personal":
                if action == "parse":
                    return await finance_service.parse_sms(user_id, text)
                elif action == "summarize":
                    return await finance_service.get_financial_summary(user_id)
                return await finance_service.parse_sms(user_id, text)

            elif module == "network_crm":
                if action == "parse" or action == "extract":
                    return await crm_service.process_interaction(user_id, text)
                elif action == "search":
                    contact_name = entities.get("contact_name", text)
                    return await crm_service.get_contact_summary(user_id, contact_name)
                return await crm_service.process_interaction(user_id, text)

            elif module == "workflow_tasks":
                if action == "extract":
                    return await task_service.extract_tasks(user_id, text)
                elif action == "summarize":
                    return await task_service.get_daily_brief(user_id)
                return await task_service.extract_tasks(user_id, text)

            elif module == "finance_market":
                return "Market intelligence module is currently processing background updates."

        # --- GENERAL CHAT FALLBACK WITH MEMORY ---
        if user_id not in conversation_history:
            conversation_history[user_id] = []

        # Add user message to history
        conversation_history[user_id].append({"role": "user", "content": text})

        # Build messages array with system prompt and last 5 turns of context
        messages = [
            {
                "role": "system", 
                "content": (
                    "You are LifeOS, a highly capable, professional, and conversational AI assistant. "
                    "You help users manage their digital lives, answer complex questions, brainstorm ideas, "
                    "and provide technical support. Be concise, accurate, and maintain a professional tone."
                )
            }
        ]
        
        # Append the last 5 interactions for conversational context
        messages.extend(conversation_history[user_id][-5:])

        response = await brain.generate_text(messages, temperature=0.7)

        # Add assistant response to history
        conversation_history[user_id].append({"role": "assistant", "content": response})

        return response

    except json.JSONDecodeError:
        logger.error("Failed to parse intent JSON from brain.")
        return "I encountered an error processing your request. Please try again."
    except Exception as e:
        logger.exception(f"Error in router_service: {e}")
        return "An unexpected error occurred while processing your input."