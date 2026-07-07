# app/ai/brain.py
"""
The LifeOS Brain: A robust wrapper around NVIDIA NIM APIs.
Handles Chat, Vision, Embeddings, and Intent Routing with retry logic.
"""
import logging
import json
import base64
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI, APIError, RateLimitError, APIConnectionError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import get_settings
from app.ai.tools import TOOLS

logger = logging.getLogger(__name__)

class LifeOSBrain:
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(
            base_url=str(settings.NVIDIA_BASE_URL),
            api_key=settings.NVIDIA_API_KEY.get_secret_value()
        )
        
        # --- SELECTED MODEL STACK ---
        
        # 1. The Brain: Optimized for speed and agentic tool calling (Function Calling)
        self.chat_model = "deepseek-ai/deepseek-v4-flash"
        
        # 2. The Eyes: Omni-modal model for structured reasoning on images/documents
        self.vision_model = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
        
        # 3. The Memory: Standard NVIDIA RAG embedding model
        self.embed_model = "nvidia/nv-embedqa-e5-v5"
        
        # ----------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((APIError, RateLimitError, APIConnectionError)),
        reraise=True
    )
    async def _chat_completion(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None, temperature: float = 0.7) -> Any:
        """Internal method to handle chat completions with automatic retries."""
        kwargs = {
            "model": self.chat_model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
            
        response = await self.client.chat.completions.create(**kwargs)
        return response.choices[0].message

    async def route_intent(self, user_input: str, context: str = "") -> Dict[str, Any]:
        """Uses Function Calling to determine the user's intent and route to the correct module."""
        messages = [
            {"role": "system", "content": "You are the central routing AI for LifeOS. Analyze the user input and route it to the correct module using the route_user_intent tool. If context is provided, use it to make a better decision."},
        ]
        if context:
            messages.append({"role": "system", "content": f"User Context: {context}"})
        messages.append({"role": "user", "content": user_input})

        try:
            message = await self._chat_completion(messages, tools=TOOLS, temperature=0.1)
            
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                if tool_call.function.name == "route_user_intent":
                    return json.loads(tool_call.function.arguments)
            
            logger.warning("Brain did not call route_user_intent tool. Falling back to general chat.")
            return {"module": "general_chat", "action": "chat", "confidence": 0.5}
            
        except Exception as e:
            logger.error(f"Intent routing failed: {e}")
            return {"module": "general_chat", "action": "chat", "confidence": 0.0}

    async def generate_text(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        """Standard text generation for summaries, replies, and general chat."""
        message = await self._chat_completion(messages, temperature=temperature)
        return message.content or ""

    async def process_vision(self, image_bytes: bytes, prompt: str = "Extract all text and describe the image in detail.") -> str:
        """Processes an image using a vision model. Converts bytes to base64 data URL."""
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        image_url = f"data:image/jpeg;base64,{base64_image}" 
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ]
        
        try:
            response = await self.client.chat.completions.create(
                model=self.vision_model,
                messages=messages,
                temperature=0.2
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Vision processing failed: {e}")
            raise

    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generates vector embeddings for a list of texts for RAG search."""
        try:
            response = await self.client.embeddings.create(
                model=self.embed_model,
                input=texts,
                extra_body={"input_type": input_type}
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise

# Singleton instance
brain = LifeOSBrain()