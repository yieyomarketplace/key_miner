# reset_db.py
import asyncio
from app.core.database import db

async def reset():
    print("Dropping all tables to apply schema fixes...")
    tables = [
        "pomodoro_sessions", "flashcards", "workflow_nodes", "workflows",
        "documents", "market_alerts", "market_assets", "transactions", 
        "tasks", "follow_ups", "interactions", "contacts", "users"
    ]
    for table in tables:
        try:
            await db.execute(f"DROP TABLE IF EXISTS {table}")
            print(f"Dropped {table}")
        except Exception as e:
            print(f"Error dropping {table}: {e}")
    
    try:
        await db.execute("DROP TABLE IF EXISTS fts_documents")
        print("Dropped fts_documents")
    except Exception as e:
        print(f"Error dropping fts: {e}")
        
    print("Database reset complete. Delete this file and restart uvicorn.")

if __name__ == "__main__":
    asyncio.run(reset())