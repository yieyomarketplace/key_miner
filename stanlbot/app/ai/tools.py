# app/ai/tools.py
"""
Comprehensive Function Calling definitions for NVIDIA NIM.
These tools allow the AI to act as a router and extract structured data 
directly into our Python services without fragile JSON parsing.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "route_user_intent",
            "description": "Analyzes the user's input and routes it to the correct LifeOS module. Use this for all incoming text messages to determine the appropriate action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "enum": [
                            "brain_rag",        # Document search, knowledge retrieval
                            "finance_personal", # SMS parsing, expense tracking
                            "finance_market",   # Market alerts, portfolio queries
                            "network_crm",      # Contact management, follow-ups
                            "workflow_tasks",   # Task extraction, scheduling
                            "general_chat"      # Fallback for general conversation
                        ],
                        "description": "The target LifeOS module."
                    },
                    "action": {
                        "type": "string",
                        "enum": [
                            "search",    # Finding information
                            "parse",     # Extracting structured data from unstructured text
                            "extract",   # Pulling entities or tasks
                            "summarize", # Condensing information
                            "alert",     # Setting or checking alerts
                            "chat"       # General conversation
                        ],
                        "description": "The specific action to perform within the module."
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "Confidence score of the routing decision."
                    },
                    "extracted_entities": {
                        "type": "object",
                        "description": "Any key entities extracted during routing (e.g., contact name, asset symbol, date).",
                        "additionalProperties": True
                    }
                },
                "required": ["module", "action", "confidence"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_crm_contact",
            "description": "Updates or creates a contact in the CRM based on interaction data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "update", "log_interaction"]},
                    "contact_name": {"type": "string"},
                    "company": {"type": "string"},
                    "interaction_summary": {"type": "string"},
                    "sentiment_score": {"type": "number", "minimum": -1.0, "maximum": 1.0},
                    "follow_up_required": {"type": "boolean"}
                },
                "required": ["action", "contact_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "parse_financial_transaction",
            "description": "Extracts financial transaction details from an SMS or text message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "currency": {"type": "string", "default": "USD"},
                    "vendor": {"type": "string"},
                    "category": {"type": "string", "enum": ["food", "transport", "utilities", "shopping", "entertainment", "income", "other"]},
                    "transaction_type": {"type": "string", "enum": ["expense", "income"]}
                },
                "required": ["amount", "vendor", "transaction_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_task",
            "description": "Creates, updates, or queries tasks in the workflow system.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "update_status", "list"]},
                    "title": {"type": "string"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                    "due_date": {"type": "string", "description": "ISO 8601 date string (YYYY-MM-DD)"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}
                },
                "required": ["action"]
            }
        }
    }
]