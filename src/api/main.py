from __future__ import annotations
import asyncio
import base64
import os
from typing import Any, Dict, Optional
from src.core.generate_section import prepare_session_state, write_section
from src.core.refine_section import refine_section
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from src.core.state import SessionState
import uvicorn

import src.api.constants as C
    
from pathlib import Path

BASE_PATH = Path(__file__).parent.parent


# ===========================================
# App Configuration
# ============================================================

app = FastAPI(title="Report Server (Dev)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=C.FRONTEND_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# lang_graph = LangGraph()

# ============================================================
# Helper Functions
# ============================================================

def envelope(status: str, message: str, data: Any = None) -> Dict[str, Any]:
    return {"status": status, "message": message, "data": data}

def api_error(http_status: int, error_code: str, message: str, *, extra: Optional[dict] = None) -> StarletteHTTPException:
    data = {"error_code": error_code}
    if extra:
        data.update(extra)
    return StarletteHTTPException(status_code=http_status, detail={"message": message, **data})

def require_api_key(x_api_key: Optional[str]) -> None:
    if not x_api_key or x_api_key != C.API_KEY:
        raise api_error(
            C.HTTP_401_UNAUTHORIZED,
            C.ERR_AUTH_INVALID_API_KEY,
            "Invalid API key",
        )

# ============================================================
# Exception Handlers
# ============================================================

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    msg = detail.get("message", "An error occurred") if isinstance(detail, dict) else str(detail)
    data = {k: v for k, v in detail.items() if k != "message"} if isinstance(detail, dict) else {}
    data.setdefault("path", request.url.path)
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(C.RESP_STATUS_ERROR, msg, data),
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = exc.errors()
    message = " ; ".join(
        f"{'.'.join(str(x) for x in err.get('loc', []) if x not in ('body',))}: {err.get('msg', 'Invalid value')}"
        for err in details
    )
    return JSONResponse(
        status_code=C.HTTP_422_UNPROCESSABLE_ENTITY,
        content=envelope(
            C.RESP_STATUS_ERROR,
            message,
            {"error_code": C.ERR_VALIDATION_ERROR, "path": request.url.path, "details": details},
        ),
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=C.HTTP_500_INTERNAL_SERVER_ERROR,
        content=envelope(
            C.RESP_STATUS_ERROR,
            "Internal server error",
            {"error_code": C.ERR_INTERNAL_ERROR, "path": request.url.path},
        ),
    )

# ============================================================
# API Models
# ============================================================

class GenerateRequest(BaseModel):
    type: str = Field(..., description="Feasibility_report | Technical_scope | Commercial_proposal")
    customer_id: str
    opportunity_id: str
    section_title: str

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in C.REPORT_TYPES:
            raise ValueError(f"Unsupported type. Allowed: {sorted(C.REPORT_TYPES)}")
        return v

class RefineRequest(BaseModel):
    type: str = Field(..., description="Feasibility_report | Technical_scope | Commercial_proposal")
    customer_id: str
    opportunity_id: str
    section_title: str
    original_text: str = Field(..., description="Base64 of original markdown/text")
    prompt: str

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in C.REPORT_TYPES:
            raise ValueError(f"Unsupported type. Allowed: {sorted(C.REPORT_TYPES)}")
        return v

# In-memory request store (dev)

SESSION_STATES: dict[str, SessionState] = {}
REQUESTS: Dict[str, Dict[str, Any]] = {}

async def generate_section_internal(
    *,
    state: SessionState,
    report_type: str,
    section_title: str,
    explicit_requirements: str | None = None,
) -> str:
    """
    Pure business logic: generate section text.
    """
    result = await write_section(
        state,
        report_type=report_type,
        section_title=section_title,
        explicit_requirements=explicit_requirements,
    )
    return result["content"]


import asyncio

async def job_generate(request_id: str) -> None:
    req_state = REQUESTS.get(request_id)
    if not req_state:
        return

    try:
        # immediately visible to polling
        req_state["busy"] = True
        req_state["status"] = C.RESP_STATUS_PROCESSING
        req_state["message"] = "Generating..."

        loop = asyncio.get_running_loop()

        def blocking_work() -> str:
            """
            Runs in a worker thread.
            Safe to block and to use asyncio.run().
            """
            session_state = asyncio.run(
                prepare_session_state(
                    session_id=req_state["session_id"],
                    customer_id=req_state["customer_id"],
                    opportunity_id=req_state["opportunity_id"],
                    report_type=req_state["type"],
                )
            )

         

            return asyncio.run(
                generate_section_internal(
                    state=session_state,
                    report_type=req_state["type"],
                    section_title=req_state["section_title"],
                    explicit_requirements=None,
                )
            )

        #  heavy work fully off event loop
        section_text: str = await loop.run_in_executor(None, blocking_work)

        req_state["busy"] = False
        req_state["status"] = C.RESP_STATUS_READY
        req_state["message"] = "Draft ready"
        req_state["data"] = {
            "customer_id": req_state["customer_id"],
            "opportunity_id": req_state["opportunity_id"],
            "section_title": req_state["section_title"],
            "generated_section_b64": section_text,
        }

    except Exception as e:
        req_state["busy"] = False
        req_state["status"] = C.RESP_STATUS_ERROR
        req_state["message"] = str(e)
        req_state["data"] = {"error_code": C.ERR_INTERNAL_ERROR}

## Refine Section Logic

async def refine_section_internal(
    *,
    session_id:str,
    report_type: str,
    section_title: str,
    original_text: str,
    user_prompt: str,
) -> str:
    """
    Pure business logic: refine an existing section.
    """
    result = await refine_section(
        session_id = session_id,
        report_type=report_type,
        section_title=section_title,
        original_text=original_text,
        user_prompt=user_prompt,
    )
    return result["refined_section"]



## Job refine

async def job_refine(request_id: str) -> None:
    req_state = REQUESTS.get(request_id)
    if not req_state:
        return

    try:
        # immediately visible to pollers
        req_state["busy"] = True
        req_state["status"] = C.RESP_STATUS_PROCESSING
        req_state["message"] = "Refining..."

        loop = asyncio.get_running_loop()

        def blocking_work() -> str:
            """
            Runs in a worker thread.
            Safe to block and to use asyncio.run().
            """

            session_id = req_state["session_id"]

        
         ### CAN PUT PREPARE STSTE IF SYNC SECTIONS IS DISABLED###
            return asyncio.run(
                refine_section_internal(
                    session_id=session_id,
                    report_type=req_state["type"],
                    section_title=req_state["section_title"],
                    original_text=req_state["original_text"],
                    user_prompt=req_state["user_prompt"],
                )
            )

        # heavy work fully off the event loop
        refined_text: str = await loop.run_in_executor(None, blocking_work)

        req_state["busy"] = False
        req_state["status"] = C.RESP_STATUS_READY
        req_state["message"] = "Refined text ready"
        req_state["data"] = {
            "customer_id": req_state["customer_id"],
            "opportunity_id": req_state["opportunity_id"],
            "section_title": req_state["section_title"],
            "refined_section_b64": refined_text,
        }

    except Exception as e:
        req_state["busy"] = False
        req_state["status"] = C.RESP_STATUS_ERROR
        req_state["message"] = str(e)
        req_state["data"] = {"error_code": C.ERR_INTERNAL_ERROR}

# ============================================================
# API Endpoints
# ============================================================

@app.post("/generate", status_code=C.HTTP_202_ACCEPTED)
async def generate(
    req: GenerateRequest,
    x_api_key: Optional[str] = Header(None, alias=C.HEADER_API_KEY),
    session_id: Optional[str] = Header(None, alias=C.HEADER_SESSION_ID),
    request_id: Optional[str] = Header(None, alias=C.HEADER_REQUEST_ID),
):
    require_api_key(x_api_key)

    if not session_id:
        raise api_error(C.HTTP_400_BAD_REQUEST, C.ERR_BAD_REQUEST, "Session-Id is required")
    if not request_id:
        raise api_error(C.HTTP_400_BAD_REQUEST, C.ERR_BAD_REQUEST, "Request-Id is required")

    # Idempotent polling behavior (client re-uses same Request-Id)
    if request_id in REQUESTS:
        st = REQUESTS[request_id]
        if st.get("busy"):
            return envelope(C.RESP_STATUS_BUSY, "Request is busy", {"ready": False, "request_id": request_id})
        if st.get("status") == C.RESP_STATUS_READY:
            return envelope(C.RESP_STATUS_READY, st.get("message", "Ready"), {"ready": True, "request_id": request_id, **(st.get("data") or {})})
        if st.get("status") == C.RESP_STATUS_ERROR:
            return envelope(C.RESP_STATUS_ERROR, st.get("message", "Error"), {"ready": False, "request_id": request_id, **(st.get("data") or {})})
        return envelope(C.RESP_STATUS_PROCESSING, st.get("message", "Processing"), {"ready": False, "request_id": request_id})

    REQUESTS[request_id] = {
        "request_id": request_id,
        "type": req.type,
        "customer_id": req.customer_id,
        "opportunity_id": req.opportunity_id,
        "section_title": req.section_title,
        "session_id": session_id,
        "busy": False,
        "status": C.RESP_STATUS_OK,
        "message": "Queued",
        "data": None,
    }

    asyncio.create_task(job_generate(request_id))
    return envelope(C.RESP_STATUS_PROCESSING, "Queued", {"ready": False, "request_id": request_id, "session_id": session_id})

@app.post("/refine", status_code=C.HTTP_202_ACCEPTED)
async def refine(
    req: RefineRequest,
    x_api_key: Optional[str] = Header(None, alias=C.HEADER_API_KEY),
    session_id: Optional[str] = Header(None, alias=C.HEADER_SESSION_ID),
    request_id: Optional[str] = Header(None, alias=C.HEADER_REQUEST_ID),
):
    require_api_key(x_api_key)

    if not session_id:
        raise api_error(C.HTTP_400_BAD_REQUEST, C.ERR_BAD_REQUEST, "Session-Id is required")
    if not request_id:
        raise api_error(C.HTTP_400_BAD_REQUEST, C.ERR_BAD_REQUEST, "Request-Id is required")

    # Idempotent polling behavior
    if request_id in REQUESTS:
        st = REQUESTS[request_id]
        if st.get("busy"):
            return envelope(C.RESP_STATUS_BUSY, "Request is busy", {"ready": False, "request_id": request_id})
        if st.get("status") == C.RESP_STATUS_READY:
            return envelope(C.RESP_STATUS_READY, st.get("message", "Ready"), {"ready": True, "request_id": request_id, **(st.get("data") or {})})
        if st.get("status") == C.RESP_STATUS_ERROR:
            return envelope(C.RESP_STATUS_ERROR, st.get("message", "Error"), {"ready": False, "request_id": request_id, **(st.get("data") or {})})
        return envelope(C.RESP_STATUS_PROCESSING, st.get("message", "Processing"), {"ready": False, "request_id": request_id})

    REQUESTS[request_id] = {
        "request_id": request_id,
        "type": req.type,
        "customer_id": req.customer_id,
        "opportunity_id": req.opportunity_id,
        "section_title": req.section_title,
        "original_text": req.original_text,
        "user_prompt": req.prompt,
        "session_id": session_id,
        "busy": False,
        "status": C.RESP_STATUS_OK,
        "message": "Queued",
        "data": None,
    }

    asyncio.create_task(job_refine(request_id))
    return envelope(C.RESP_STATUS_PROCESSING, "Queued", {"ready": False, "request_id": request_id, "session_id": session_id})

if __name__ == "__main__":

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
