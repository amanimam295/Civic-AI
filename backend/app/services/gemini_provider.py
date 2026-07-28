import os
import json
import httpx
from typing import Dict, Any, List
from pydantic import ValidationError
from fastapi import HTTPException
from app.services.ai_provider import AIProvider
from app.services.gemma_client import AnalyzeResponseSchema, _repair_and_parse_json
from app.core.logging import get_logger

logger = get_logger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent"

class GeminiProvider(AIProvider):
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise HTTPException(
                status_code=400, 
                detail="Gemini API Key is missing. Please set GEMINI_API_KEY environment variable to use the Gemini provider."
            )
            
    async def generate_json(self, prompt: str) -> Dict[str, Any]:
        full_prompt = (
            f"{prompt}\n\n"
            "You MUST output valid JSON. No markdown formatting block (like ```json), no preamble, no trailing text. "
            "Just the raw JSON object matching this schema:\n"
            "{\n"
            '  "explanation": "string",\n'
            '  "eligibility": {"status": "likely|action-needed|confirmed", "text": "string"},\n'
            '  "checklist": ["string", "string"],\n'
            '  "missing_documents": ["string", "string"]\n'
            "}\n"
        )
        
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}]
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                res = await client.post(GEMINI_API_URL,json=payload,headers={"x-goog-api-key": self.api_key},)
                res.raise_for_status()
                data = res.json()
                
                # Extract text
                result_text = data["candidates"][0]["content"]["parts"][0]["text"]
                
                # Attempt to parse and validate
                parsed = _repair_and_parse_json(result_text)
                AnalyzeResponseSchema(**parsed)
                return parsed
            except Exception as e:
                logger.error(f"Gemini API JSON generation failed: {e}")
                if hasattr(e, 'response') and e.response:
                    logger.error(f"Response: {e.response.text}")
                raise HTTPException(status_code=500, detail="Failed to generate valid response from Gemini API.")

    async def chat(self, history: List[Dict[str, str]], new_message: str) -> str:
        # Convert history format
        contents = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            # Gemini only takes user or model, not system. For simplicity, just append all text if role is system (or ignore).
            if msg["role"] == "system": continue
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })
            
        contents.append({
            "role": "user",
            "parts": [{"text": new_message}]
        })
        
        payload = {"contents": contents}
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                res = await client.post(f"{GEMINI_API_URL}?key={self.api_key}", json=payload)
                res.raise_for_status()
                data = res.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:
                logger.error(f"Gemini API chat failed: {e}")
                raise HTTPException(status_code=500, detail="Failed to get chat response from Gemini API.")
