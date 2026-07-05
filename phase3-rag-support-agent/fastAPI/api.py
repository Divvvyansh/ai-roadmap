"""
FastAPI server exposing the RAG agent.
"""
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "Agent"))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import anthropic

from agent import ask

logger = logging.getLogger(__name__)
app = FastAPI()


class AskRequest(BaseModel):
    question: str = Field(min_length=1,  pattern=r"\S")


class AskResponse(BaseModel):
    answer: str
    docs_source: list[str]


@app.post("/ask", response_model=AskResponse)
def ask_endpoint(request: AskRequest) -> AskResponse:
    
    try:
        result = ask(request.question)
        return AskResponse(
            answer=result["answer"],
            docs_source=result.get("docs_used", []),
        )
    except Exception as e:
        logger.exception("Error handling /ask request", exc_info=e)
        if isinstance(e, anthropic.RateLimitError):
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.")
        else:
            raise HTTPException(status_code=500, detail="An error occurred while processing the request.")

