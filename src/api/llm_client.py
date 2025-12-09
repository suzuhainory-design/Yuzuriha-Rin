# LLM API client supporting multiple providers
import httpx
from typing import List, Dict, Any
from .schemas import LLMConfig, ChatMessage

class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config
        self.client = httpx.AsyncClient(timeout=60.0)
    
    async def chat(self, messages: List[ChatMessage]) -> str:
        if self.config.provider == "openai":
            return await self._openai_chat(messages)
        elif self.config.provider == "anthropic":
            return await self._anthropic_chat(messages)
        elif self.config.provider == "custom":
            return await self._custom_chat(messages)
        else:
            raise ValueError(f"Unsupported provider: {self.config.provider}")
    
    async def _openai_chat(self, messages: List[ChatMessage]) -> str:
        base_url = self.config.base_url or "https://api.openai.com/v1"
        
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.system_prompt}
            ] + [{"role": m.role, "content": m.content} for m in messages]
        }
        
        response = await self.client.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    
    async def _anthropic_chat(self, messages: List[ChatMessage]) -> str:
        base_url = self.config.base_url or "https://api.anthropic.com/v1"
        
        # Convert messages format for Anthropic
        anthropic_messages = [
            {"role": m.role, "content": m.content} for m in messages
        ]
        
        payload = {
            "model": self.config.model,
            "max_tokens": 1024,
            "system": self.config.system_prompt,
            "messages": anthropic_messages
        }
        
        response = await self.client.post(
            f"{base_url}/messages",
            json=payload,
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]
    
    async def _custom_chat(self, messages: List[ChatMessage]) -> str:
        # Generic OpenAI-compatible API
        if not self.config.base_url:
            raise ValueError("base_url required for custom provider")
        
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.system_prompt}
            ] + [{"role": m.role, "content": m.content} for m in messages]
        }
        
        response = await self.client.post(
            f"{self.config.base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    
    async def close(self):
        await self.client.aclose()