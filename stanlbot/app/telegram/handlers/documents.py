# app/telegram/handlers/documents.py
"""
Handles media and document uploads.
Processes images via Vision AI, extracts text from documents, and indexes them into the RAG system.
"""
import logging
import io
from aiogram import Router, F
from aiogram.types import Message
import httpx

from app.telegram.bot import bot
from app.services.rag_service import save_document
from app.ai.brain import brain

logger = logging.getLogger(__name__)
router = Router()

MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

async def download_telegram_file(file_id: str) -> bytes:
    """Downloads a file from Telegram servers."""
    file_info = await bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{bot.token}/{file_info.file_path}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(file_url)
        response.raise_for_status()
        return response.content

@router.message(F.photo)
async def handle_photo(message: Message):
    """Handles image uploads, extracts text using Vision AI, and indexes it."""
    user_id = message.from_user.id
    processing_msg = await message.answer("Processing image...")
    
    try:
        # Get the highest resolution photo
        photo = message.photo[-1]
        if photo.file_size and photo.file_size > MAX_FILE_SIZE_BYTES:
            await processing_msg.edit_text(f"Error: Image exceeds the {MAX_FILE_SIZE_MB}MB limit.")
            return

        image_bytes = await download_telegram_file(photo.file_id)
        
        # Use Vision AI to extract text and context
        extracted_text = await brain.process_vision(
            image_bytes, 
            prompt="Extract all text from this image. If it is a diagram or chart, describe its contents and structure in detail."
        )
        
        if not extracted_text or len(extracted_text.strip()) < 5:
            await processing_msg.edit_text("No readable text or significant content found in the image.")
            return

        metadata = {
            "source": "telegram_photo",
            "caption": message.caption or "",
            "file_id": photo.file_id
        }
        
        result = await save_document(user_id, "image.jpg", "image/jpeg", extracted_text, metadata)
        await processing_msg.edit_text(result)

    except Exception as e:
        logger.exception(f"Error processing photo: {e}")
        await processing_msg.edit_text("An error occurred while processing the image. Please try again.")

@router.message(F.document)
async def handle_document(message: Message):
    """Handles document uploads. Extracts text from supported formats and indexes it."""
    user_id = message.from_user.id
    doc = message.document
    
    if doc.file_size and doc.file_size > MAX_FILE_SIZE_BYTES:
        await message.answer(f"Error: Document exceeds the {MAX_FILE_SIZE_MB}MB limit.")
        return

    processing_msg = await message.answer(f"Processing document: {doc.file_name}...")
    
    try:
        file_bytes = await download_telegram_file(doc.file_id)
        mime_type = doc.mime_type or "application/octet-stream"
        extracted_text = ""
        
        # Handle plain text files
        if mime_type.startswith("text/"):
            extracted_text = file_bytes.decode('utf-8', errors='ignore')
            
        # Handle PDF files (requires pypdf in requirements.txt)
        elif mime_type == "application/pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                text_parts = []
                for page in reader.pages:
                    text_parts.append(page.extract_text() or "")
                extracted_text = "\n".join(text_parts)
            except ImportError:
                await processing_msg.edit_text("Error: PDF processing library is not installed on the server.")
                return
            except Exception as pdf_e:
                logger.error(f"PDF extraction failed: {pdf_e}")
                extracted_text = ""
        else:
            await processing_msg.edit_text(f"Unsupported file type: {mime_type}. Please send text, images, or PDFs.")
            return

        if not extracted_text or len(extracted_text.strip()) < 10:
            await processing_msg.edit_text("No readable text could be extracted from the document.")
            return

        metadata = {
            "source": "telegram_document",
            "file_name": doc.file_name,
            "mime_type": mime_type,
            "caption": message.caption or ""
        }
        
        result = await save_document(user_id, doc.file_name, mime_type, extracted_text, metadata)
        await processing_msg.edit_text(result)

    except Exception as e:
        logger.exception(f"Error processing document: {e}")
        await processing_msg.edit_text("An error occurred while processing the document. Please try again.")

@router.message(F.voice | F.audio)
async def handle_voice_audio(message: Message):
    """Handles voice notes and audio files. Acknowledges receipt (transcription requires external STT API)."""
    await message.answer(
        "Audio file received. Note: Native voice transcription requires an external Speech-to-Text (STT) integration. "
        "Please provide a text summary or forward the transcript for processing."
    )