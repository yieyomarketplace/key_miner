# app/main.py
"""
FastAPI Application Entry Point.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import db
from app.api import webhooks, cron

# FIX: Import directly from the bot module
from app.telegram.bot import bot as telegram_bot, set_webhook, delete_webhook

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting LifeOS...")
    try:
        await db.initialize_schema()
        logger.info("Database schema verified/initialized.")
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}")
        
    # Optional: Auto-set webhook on startup
    # await set_webhook()
    
    yield
    logger.info("Shutting down LifeOS...")

app = FastAPI(
    title="LifeOS API",
    description="The Central Nervous System for your digital life.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks.router, tags=["Telegram"])
app.include_router(cron.router, tags=["Autonomous Cron"])

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "alive", "system": "LifeOS"}