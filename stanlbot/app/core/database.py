# app/core/database.py
"""
SQLite Cloud connection manager and schema initialization.
"""
import sqlitecloud
import asyncio
import logging
from typing import Any, Tuple
from contextlib import contextmanager
from app.core.config import get_settings

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.settings = get_settings()
        self._connection_string = self.settings.SQLITE_CLOUD_URL.get_secret_value()

    @contextmanager
    def _get_connection(self):
        conn = None
        try:
            conn = sqlitecloud.connect(self._connection_string)
            yield conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()

    async def execute(self, query: str, params: Tuple = (), fetch: bool = False) -> Any:
        def _sync_execute():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                if fetch:
                    return cursor.fetchall()
                conn.commit()
                return cursor.lastrowid
        
        try:
            return await asyncio.to_thread(_sync_execute)
        except Exception as e:
            logger.error(f"Query execution failed: {query} | Params: {params} | Error: {e}")
            raise

    async def initialize_schema(self):
        logger.info("Initializing database schema...")
        
        schema_statements = [
            # Core Users - FIXED: tg_id is now the PRIMARY KEY
            """
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                full_name TEXT,
                username TEXT,
                settings_json TEXT DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
            # CRM / Network Intelligence
            """
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                email TEXT, phone TEXT, company TEXT, context_summary TEXT,
                relationship_score REAL DEFAULT 0.5, last_interaction DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(tg_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                interaction_type TEXT, summary TEXT, sentiment REAL, raw_data TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(contact_id) REFERENCES contacts(id),
                FOREIGN KEY(user_id) REFERENCES users(tg_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS follow_ups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                contact_id INTEGER,
                task_description TEXT NOT NULL,
                due_date DATETIME NOT NULL,
                is_completed BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(tg_id),
                FOREIGN KEY(contact_id) REFERENCES contacts(id)
            )
            """,
            # Workflow / Tasks
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                priority INTEGER DEFAULT 3, 
                due_date DATETIME,
                status TEXT DEFAULT 'pending', 
                source_type TEXT, 
                source_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(tg_id)
            )
            """,
            # Finance (Personal)
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                vendor TEXT,
                category TEXT,
                transaction_type TEXT DEFAULT 'expense', 
                raw_sms TEXT,
                transaction_date DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(tg_id)
            )
            """,
            # Finance (Market)
            """
            CREATE TABLE IF NOT EXISTS market_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT UNIQUE NOT NULL,
                asset_type TEXT, 
                current_price REAL,
                sentiment_score REAL DEFAULT 0.0,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS market_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                condition_type TEXT, 
                threshold_value REAL NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(tg_id)
            )
            """,
            # RAG / Knowledge Base
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                file_name TEXT,
                file_type TEXT,
                raw_text TEXT,
                metadata_json TEXT,
                embedding_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(tg_id)
            )
            """,
            # FTS5 for High-Speed Hybrid Search
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_documents USING fts5(
                raw_text, 
                metadata_json, 
                content='documents', 
                content_rowid='id'
            )
            """,
            # Triggers to keep FTS5 perfectly in sync
            """
            CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
                INSERT INTO fts_documents(rowid, raw_text, metadata_json) VALUES (new.id, new.raw_text, new.metadata_json);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON documents BEGIN
                INSERT INTO fts_documents(rowid, raw_text, metadata_json) VALUES (new.id, new.raw_text, new.metadata_json);
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documents BEGIN
                INSERT INTO fts_documents(fts_documents, rowid, raw_text, metadata_json) VALUES('delete', old.id, old.raw_text, old.metadata_json);
            END
            """,
            # Workflow Engine
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 1,
                trigger_type TEXT NOT NULL,
                trigger_config_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(tg_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS workflow_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_id INTEGER NOT NULL,
                execution_order INTEGER NOT NULL,
                node_type TEXT NOT NULL,
                node_config_json TEXT NOT NULL,
                FOREIGN KEY(workflow_id) REFERENCES workflows(id)
            )
            """,
            # Student / SOS Suite
            """
            CREATE TABLE IF NOT EXISTS flashcards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                front_text TEXT NOT NULL,
                back_text TEXT NOT NULL,
                ease_factor REAL DEFAULT 2.5,
                interval_days INTEGER DEFAULT 0,
                next_review DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(tg_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS pomodoro_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                duration_minutes INTEGER NOT NULL,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(tg_id)
            )
            """
        ]

        def _sync_init():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                for stmt in schema_statements:
                    try:
                        cursor.execute(stmt)
                    except Exception as e:
                        logger.error(f"Failed to execute schema statement: {e}")
                        raise
                conn.commit()

        try:
            await asyncio.to_thread(_sync_init)
            logger.info("Database schema initialized successfully.")
        except Exception as e:
            logger.error(f"Schema initialization failed: {e}")
            raise

db = DatabaseManager()