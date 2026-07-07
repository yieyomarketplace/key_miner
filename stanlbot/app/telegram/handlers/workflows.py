# app/telegram/handlers/workflows.py
"""
Workflow Builder Handlers.
Uses Aiogram FSM to guide users through creating custom automations step-by-step.
"""
import logging
import json
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.services.workflow_service import create_workflow, add_node_to_workflow, get_user_workflows, execute_workflow

logger = logging.getLogger(__name__)
router = Router()

class WorkflowBuilderStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_trigger = State()
    waiting_for_trigger_config = State()
    waiting_for_action = State()
    waiting_for_action_config = State()

@router.message(Command("newworkflow"))
async def cmd_new_workflow(message: Message, state: FSMContext):
    await message.answer("Starting Workflow Builder.\n\nStep 1: What is the name of this automation?")
    await state.set_state(WorkflowBuilderStates.waiting_for_name)

@router.message(WorkflowBuilderStates.waiting_for_name)
async def process_workflow_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text, nodes=[])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="On Schedule (Cron)", callback_data="trigger_schedule")],
        [InlineKeyboardButton(text="On Keyword (Text Match)", callback_data="trigger_keyword")],
        [InlineKeyboardButton(text="On Webhook (External API)", callback_data="trigger_webhook")]
    ])
    await message.answer("Step 2: Select the Trigger for this workflow:", reply_markup=keyboard)
    await state.set_state(WorkflowBuilderStates.waiting_for_trigger)

@router.callback_query(WorkflowBuilderStates.waiting_for_trigger, F.data.startswith("trigger_"))
async def process_workflow_trigger(callback: CallbackQuery, state: FSMContext):
    trigger_type = callback.data.split("_")[1]
    await state.update_data(trigger_type=trigger_type)
    
    prompt = "Step 3: Provide the configuration for the trigger.\n"
    if trigger_type == "schedule":
        prompt += "Enter a cron expression (e.g., '0 8 * * *' for 8 AM daily):"
    elif trigger_type == "keyword":
        prompt += "Enter the keyword that will trigger this workflow:"
    else:
        prompt += "Enter a unique webhook path (e.g., '/my-custom-hook'):"
        
    await callback.message.edit_text(prompt)
    await state.set_state(WorkflowBuilderStates.waiting_for_trigger_config)
    await callback.answer()

@router.message(WorkflowBuilderStates.waiting_for_trigger_config)
async def process_trigger_config(message: Message, state: FSMContext):
    await state.update_data(trigger_config={"value": message.text})
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Download Media (URL)", callback_data="action_download")],
        [InlineKeyboardButton(text="Extract Tasks (Text)", callback_data="action_tasks")],
        [InlineKeyboardButton(text="Index to Knowledge Base", callback_data="action_index")],
        [InlineKeyboardButton(text="Finish & Save Workflow", callback_data="action_finish")]
    ])
    await message.answer("Step 4: Select the first Action node to add to this workflow:", reply_markup=keyboard)
    await state.set_state(WorkflowBuilderStates.waiting_for_action)

@router.callback_query(WorkflowBuilderStates.waiting_for_action, F.data.startswith("action_"))
async def process_workflow_action(callback: CallbackQuery, state: FSMContext):
    action_type = callback.data.split("_")[1]
    
    if action_type == "finish":
        data = await state.get_data()
        workflow_id = await create_workflow(
            callback.from_user.id, data["name"], data["trigger_type"], data["trigger_config"]
        )
        for node in data.get("nodes", []):
            await add_node_to_workflow(workflow_id, node["type"], node["config"])
            
        await callback.message.edit_text(f"Workflow '{data['name']}' saved successfully with {len(data.get('nodes', []))} nodes.")
        await state.clear()
        await callback.answer()
        return

    await state.update_data(current_action=action_type)
    
    prompt = "Provide the configuration for this action node.\n"
    if action_type == "download":
        prompt += "Enter the default URL to download (or 'context_url' to use the trigger's URL):"
    elif action_type == "tasks":
        prompt += "Enter the default text to extract tasks from (or 'context_text'):"
    else:
        prompt += "Enter the default text to index (or 'context_text'):"
        
    await callback.message.edit_text(prompt)
    await state.set_state(WorkflowBuilderStates.waiting_for_action_config)
    await callback.answer()

@router.message(WorkflowBuilderStates.waiting_for_action_config)
async def process_action_config(message: Message, state: FSMContext):
    data = await state.get_data()
    action_type = data["current_action"]
    
    new_node = {"type": f"{action_type}_media" if action_type == "download" else f"extract_{action_type}", "config": {"value": message.text}}
    
    nodes = data.get("nodes", [])
    nodes.append(new_node)
    await state.update_data(nodes=nodes)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Download Media", callback_data="action_download")],
        [InlineKeyboardButton(text="Extract Tasks", callback_data="action_tasks")],
        [InlineKeyboardButton(text="Index to KB", callback_data="action_index")],
        [InlineKeyboardButton(text="Finish & Save Workflow", callback_data="action_finish")]
    ])
    await message.answer(f"Action added. Total nodes: {len(nodes)}.\nSelect the next action or finish:", reply_markup=keyboard)
    await state.set_state(WorkflowBuilderStates.waiting_for_action)

@router.message(Command("listworkflows"))
async def cmd_list_workflows(message: Message):
    workflows = await get_user_workflows(message.from_user.id)
    if not workflows:
        await message.answer("You have no active workflows. Use /newworkflow to create one.")
        return
        
    text = "<b>Your Workflows:</b>\n\n"
    keyboard = []
    for wf_id, name, trigger, is_active in workflows:
        status = "Active" if is_active else "Inactive"
        text += f"- {name} (Trigger: {trigger}, Status: {status})\n"
        keyboard.append([InlineKeyboardButton(text=f"Run: {name}", callback_data=f"runwf_{wf_id}")])
        
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@router.callback_query(F.data.startswith("runwf_"))
async def handle_run_workflow(callback: CallbackQuery):
    wf_id = int(callback.data.split("_")[1])
    await callback.answer("Executing workflow...")
    await execute_workflow(wf_id, context={"text": "Manual execution via Telegram"})
    await callback.message.answer("Workflow execution completed. Check logs for details.")