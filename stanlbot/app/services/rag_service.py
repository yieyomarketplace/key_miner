# app/services/rag_service.py
"""
Retrieval-Augmented Generation (RAG) service.
Handles document ingestion, embedding generation, and hybrid search (FTS5 + Vector).
"""
import json
import logging
import numpy as np
from typing import List, Dict, Any

from app.core.database import db
from app.ai.brain import brain

logger = logging.getLogger(__name__)

async def save_document(user_id: int, file_name: str, file_type: str, raw_text: str, metadata: Dict[str, Any]) -> str:
    """
    Processes a document, generates embeddings, and saves it to the database.
    """
    if not raw_text or len(raw_text.strip()) < 10:
        return "The document appears to be empty or unreadable. No data was saved."

    try:
        # Generate embedding for the document text (limit to 2000 chars for API limits)
        text_to_embed = raw_text[:2000]
        embeddings = await brain.generate_embeddings([text_to_embed], input_type="passage")
        embedding_json = json.dumps(embeddings[0])
        metadata_json = json.dumps(metadata)

        await db.execute(
            """
            INSERT INTO documents (user_id, file_name, file_type, raw_text, metadata_json, embedding_json) 
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, file_name, file_type, raw_text, metadata_json, embedding_json)
        )
        
        logger.info(f"Document '{file_name}' saved and indexed for user {user_id}.")
        return f"Document '{file_name}' has been successfully processed and added to your knowledge base."

    except Exception as e:
        logger.exception(f"Failed to save document: {e}")
        return "An error occurred while processing and saving the document."

async def search_documents(user_id: int, query: str) -> str:
    """
    Performs a hybrid search: FTS5 for keyword candidates, then vector cosine similarity for re-ranking.
    """
    try:
        # Step 1: FTS5 Keyword Search to get candidate documents
        safe_query = query.replace('"', '""')
        fts_query = f'"{safe_query}"'
        
        candidates = await db.execute(
            "SELECT rowid, raw_text FROM fts_documents WHERE fts_documents MATCH ? LIMIT 20",
            (fts_query,),
            fetch=True
        )

        if not candidates:
            return "No documents found matching your query keywords."

        # Step 2: Fetch full details and embeddings for the candidates
        doc_ids = [str(c[0]) for c in candidates]
        placeholders = ','.join(['?'] * len(doc_ids))
        
        doc_details = await db.execute(
            f"SELECT id, file_name, raw_text, embedding_json FROM documents WHERE id IN ({placeholders})",
            doc_ids,
            fetch=True
        )

        # Step 3: Generate embedding for the user's query
        query_embeddings = await brain.generate_embeddings([query], input_type="query")
        query_vec = np.array(query_embeddings[0])

        # Step 4: Calculate cosine similarity and rank
        ranked_docs = []
        for doc in doc_details:
            doc_id, file_name, raw_text, emb_json = doc
            try:
                doc_vec = np.array(json.loads(emb_json))
                similarity = np.dot(query_vec, doc_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(doc_vec))
                ranked_docs.append({
                    "id": doc_id,
                    "file_name": file_name,
                    "raw_text": raw_text,
                    "score": float(similarity)
                })
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Skipping document {doc_id} due to embedding parse error: {e}")
                continue

        if not ranked_docs:
            return "Found keyword matches, but semantic relevance could not be calculated."

        # Sort by score descending
        ranked_docs.sort(key=lambda x: x["score"], reverse=True)
        
        # Take the top document for summarization
        top_doc = ranked_docs[0]
        
        # Step 5: Use AI to generate an answer based on the top document and the query
        messages = [
            {
                "role": "system", 
                "content": "You are an expert research assistant. Answer the user's query based ONLY on the provided document context. If the answer is not in the context, state that clearly. Be professional and concise."
            },
            {
                "role": "user", 
                "content": f"Query: {query}\n\nDocument Context (from {top_doc['file_name']}):\n{top_doc['raw_text'][:3000]}"
            }
        ]
        
        answer = await brain.generate_text(messages, temperature=0.3)
        
        return f"Found relevant information in '{top_doc['file_name']}' (Relevance: {top_doc['score']:.2f}):\n\n{answer}"

    except Exception as e:
        logger.exception(f"Error during document search: {e}")
        return "An error occurred while searching your documents."