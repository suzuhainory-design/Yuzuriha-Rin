# API routes
from fastapi import APIRouter, HTTPException
from .schemas import ChatRequest, ChatResponse, MessageAction
from .llm_client import LLMClient

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        client = LLMClient(request.llm_config)
        response_text = await client.chat(request.messages)
        await client.close()
        
        # Simple conversion: send full text as one message
        # TODO: Replace with ML model for segmentation
        actions = [
            MessageAction(
                type="send",
                text=response_text,
                delay=0.5  # typing delay
            )
        ]
        
        return ChatResponse(
            actions=actions,
            raw_response=response_text
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health_check():
    return {"status": "ok"}