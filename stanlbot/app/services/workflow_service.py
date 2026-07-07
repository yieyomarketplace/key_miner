# app/services/workflow_service.py
"""
Workflow Engine: Manages the creation, storage, and execution of custom automations.
"""
import json
import logging
from typing import List, Dict, Any

from app.core.database import db
from app.services import media_service, task_service, rag_service

logger = logging.getLogger(__name__)

async def create_workflow(user_id: int, name: str, trigger_type: str, trigger_config: Dict) -> int:
    workflow_id = await db.execute(
        "INSERT INTO workflows (user_id, name, trigger_type, trigger_config_json) VALUES (?, ?, ?, ?)",
        (user_id, name, trigger_type, json.dumps(trigger_config))
    )
    logger.info(f"Workflow '{name}' created with ID {workflow_id} for user {user_id}.")
    return workflow_id

async def add_node_to_workflow(workflow_id: int, node_type: str, node_config: Dict) -> int:
    # Get current max execution order
    max_order = await db.execute(
        "SELECT COALESCE(MAX(execution_order), -1) FROM workflow_nodes WHERE workflow_id = ?",
        (workflow_id,), fetch=True
    )
    next_order = (max_order[0][0] if max_order else -1) + 1

    node_id = await db.execute(
        "INSERT INTO workflow_nodes (workflow_id, execution_order, node_type, node_config_json) VALUES (?, ?, ?, ?)",
        (workflow_id, next_order, node_type, json.dumps(node_config))
    )
    return node_id

async def get_user_workflows(user_id: int) -> List[tuple]:
    return await db.execute(
        "SELECT id, name, trigger_type, is_active FROM workflows WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,), fetch=True
    )

async def execute_workflow(workflow_id: int, context: Dict[str, Any] = None):
    workflow = await db.execute("SELECT id, user_id FROM workflows WHERE id = ? AND is_active = 1", (workflow_id,), fetch=True)
    if not workflow:
        logger.warning(f"Workflow {workflow_id} not found or inactive.")
        return

    user_id = workflow[0][1]
    nodes = await db.execute(
        "SELECT node_type, node_config_json FROM workflow_nodes WHERE workflow_id = ? ORDER BY execution_order",
        (workflow_id,), fetch=True
    )

    current_context = context or {}
    
    for node_type, config_json in nodes:
        config = json.loads(config_json)
        logger.info(f"Executing node: {node_type} for workflow {workflow_id}")
        
        try:
            if node_type == "download_media":
                url = current_context.get("url") or config.get("default_url")
                if url:
                    file_path = await media_service.download_media(url, config.get("format", "best_video"))
                    current_context["downloaded_file"] = file_path
                    
            elif node_type == "extract_tasks":
                text = current_context.get("text", "")
                if text:
                    await task_service.extract_tasks(user_id, text)
                    
            elif node_type == "index_document":
                text = current_context.get("text", "")
                if text:
                    await rag_service.save_document(user_id, "Workflow Auto-Index", "text/plain", text, {"source": "workflow"})
                    
            elif node_type == "ai_prompt":
                # Placeholder for future AI node execution
                pass
                
        except Exception as e:
            logger.error(f"Node {node_type} failed in workflow {workflow_id}: {e}")
            break

    logger.info(f"Workflow {workflow_id} execution completed.")