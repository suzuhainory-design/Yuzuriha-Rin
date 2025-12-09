# Pydantic schemas for API
from pydantic import BaseModel
from typing import List, Literal, Optional

class LLMConfig(BaseModel):
    provider: Literal["openai", "anthropic", "custom"] = "openai"
    api_key: str
    base_url: Optional[str] = None
    model: str = "gpt-3.5-turbo"
    system_prompt: str = "You are a helpful assistant."

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ChatRequest(BaseModel):
    llm_config: LLMConfig
    messages: List[ChatMessage]
    character_name: str = "Rie"

class MessageAction(BaseModel):
    type: Literal["send", "recall"]
    text: str
    delay: float  # seconds before this action

class ChatResponse(BaseModel):
    actions: List[MessageAction]
    raw_response: str