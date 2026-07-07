# LifeOS

**A Production-Grade AI Operating System via Telegram**

LifeOS is a centralized, autonomous AI system designed to manage knowledge, finances, professional networks, and daily workflows through a unified Telegram interface. It leverages a distributed architecture where the AI acts as the central brain, Telegram as the sensory/motor interface, Render as the computational workforce, and SQLite Cloud as the persistent memory.

## Architecture Overview

LifeOS is built on four core pillars:

1. **The Cognitive Core (RAG & Hybrid Search):** Ingests documents, images, and text. Generates vector embeddings and utilizes SQLite FTS5 for high-speed hybrid keyword and semantic search.
2. **The Financial Command Center:** Parses transactional SMS messages for personal expense tracking and monitors external market APIs for macroeconomic sentiment analysis.
3. **The Network Intelligence Engine (CRM):** Automatically extracts contact information from forwarded messages, tracks relationship health, and schedules autonomous follow-ups.
4. **The Workflow Autopilot:** Extracts actionable tasks from natural language, prioritizes them based on deadlines and context, and generates daily executive briefings.

## Tech Stack

- **Framework:** FastAPI (Asynchronous web server and API router)
- **Bot Interface:** Aiogram 3.x (Asynchronous Telegram bot framework)
- **AI Engine:** NVIDIA NIM (Chat, Vision, and Embeddings via OpenAI-compatible API)
- **Database:** SQLite Cloud (Relational data, JSON metadata, and FTS5 full-text search)
- **Hosting:** Render (Free tier web service)
- **Uptime & Automation:** Cron-job.org (External pinging for 100% uptime and autonomous background tasks)

---

## Prerequisites

- Python 3.10+
- A Telegram Bot Token (via [@BotFather](https://t.me/BotFather))
- An NVIDIA NIM API Key (via [build.nvidia.com](https://build.nvidia.com/))
- A SQLite Cloud account and connection string
- A Render account for deployment
- A Cron-job.org account for external scheduling

---

## Local Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/lifeos.git
   cd lifeos