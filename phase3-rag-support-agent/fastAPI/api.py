"""
FastAPI server exposing the RAG agent.
"""
import sys
import logging
from pathlib import Path
import json
import itertools

sys.path.insert(0, str(Path(__file__).parent.parent / "Agent"))

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import anthropic

from agent import ask

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)
app = FastAPI()


class AskRequest(BaseModel):
    question: str = Field(min_length=1,  pattern=r"\S")


class AskResponse(BaseModel):
    answer: str
    docs_source: list[str]
    chunks_used: list[str] 
    chunk_texts: dict[str, str]  


@app.post("/ask", response_model=AskResponse)
def ask_endpoint(request: AskRequest) -> AskResponse:
    try:
        result = ask(request.question)
        return AskResponse(
            answer=result["answer"],
            docs_source=result.get("docs_used", []),
            chunks_used=list(chunk.id for chunk in itertools.chain.from_iterable(result["chunks_used"])),
            chunk_texts={chunk.id: chunk.text for chunk in itertools.chain.from_iterable(result["chunks_used"])}, 
        )
    except Exception as e:
        logger.exception("Error handling /ask request", exc_info=e)

        if isinstance(e, anthropic.RateLimitError):
            status_code, detail = 429, "Rate limit exceeded. Please try again later."
        else:
            status_code, detail = 500, "An error occurred while processing the request."

        logger.error(
            json.dumps({
                "question": request.question,
                "error_type": type(e).__name__,
                "status_code": status_code,
                "status": "error"
            })
        )
        raise HTTPException(status_code=status_code, detail=detail)

