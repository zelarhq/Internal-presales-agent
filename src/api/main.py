from __future__ import annotations
import asyncio
import base64
import os
from typing import Any, Dict, Optional
from src.core.generate_section import prepare_session_state, write_section
from src.core.refine_section import refine_section
from fastapi import FastAPI, Header, Request, Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from src.core.state import SessionState
import uvicorn

import src.api.constants as C
from src.api.job_storage import get_storage, JobStatus, Job
    
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
    return {
        C.ENVELOPE_KEY_STATUS: status,
        C.ENVELOPE_KEY_MESSAGE: message,
        C.ENVELOPE_KEY_DATA: data,
    }

def api_error(http_status: int, error_code: str, message: str, *, extra: Optional[dict] = None) -> StarletteHTTPException:
    data = {C.ENVELOPE_KEY_ERROR_CODE: error_code}
    if extra:
        data.update(extra)
    return StarletteHTTPException(
        status_code=http_status,
        detail={C.ENVELOPE_KEY_MESSAGE: message, **data}
    )

def require_api_key(x_api_key: Optional[str]) -> None:
    if not x_api_key or x_api_key != C.API_KEY:
        raise api_error(
            C.HTTP_401_UNAUTHORIZED,
            C.ERR_AUTH_INVALID_API_KEY,
            C.MSG_INVALID_API_KEY,
        )

# ============================================================
# Exception Handlers
# ============================================================

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    msg = detail.get(C.ENVELOPE_KEY_MESSAGE, C.MSG_ERROR_OCCURRED) if isinstance(detail, dict) else str(detail)
    data = {k: v for k, v in detail.items() if k != C.ENVELOPE_KEY_MESSAGE} if isinstance(detail, dict) else {}
    data.setdefault(C.ENVELOPE_KEY_PATH, request.url.path)
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(C.RESP_STATUS_ERROR, msg, data),
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    raw_details = exc.errors()

    # Ensure all details are JSON-serializable (e.g. ctx.error may contain ValueError objects)
    details: list[dict] = []
    for err in raw_details:
        err_copy = dict(err)
        ctx = err_copy.get("ctx")
        if isinstance(ctx, dict):
            ctx_copy = dict(ctx)
            error_obj = ctx_copy.get("error")
            if error_obj is not None and not isinstance(error_obj, str):
                ctx_copy["error"] = str(error_obj)
            err_copy["ctx"] = ctx_copy
        details.append(err_copy)

    message = " ; ".join(
        f"{'.'.join(str(x) for x in err.get('loc', []) if x not in ('body',))}: {err.get('msg', C.MSG_INVALID_VALUE)}"
        for err in details
    )
    return JSONResponse(
        status_code=C.HTTP_422_UNPROCESSABLE_ENTITY,
        content=envelope(
            C.RESP_STATUS_ERROR,
            message,
            {
                C.ENVELOPE_KEY_ERROR_CODE: C.ERR_VALIDATION_ERROR,
                C.ENVELOPE_KEY_PATH: request.url.path,
                C.ENVELOPE_KEY_DETAILS: details,
            },
        ),
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=C.HTTP_500_INTERNAL_SERVER_ERROR,
        content=envelope(
            C.RESP_STATUS_ERROR,
            C.MSG_INTERNAL_SERVER_ERROR,
            {
                C.ENVELOPE_KEY_ERROR_CODE: C.ERR_INTERNAL_ERROR,
                C.ENVELOPE_KEY_PATH: request.url.path,
            },
        ),
    )

# ============================================================
# API Models
# ============================================================

class GenerateRequest(BaseModel):
    type: str = Field(
        ...,
        description=(
            "Report type. Accepted values (case-insensitive, '-' or '_' allowed): "
            "commercial-proposal | feasibility-report | technical-scope"
        ),
    )
    customer_id: str
    opportunity_id: str
    section_title: str

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        # Normalise common frontend variants into the canonical kebab-case values
        # that the backend uses internally (see src.api.constants.REPORT_TYPES).
        normalised = v.strip().lower().replace("_", "-")
        if normalised not in C.REPORT_TYPES:
            raise ValueError(f"Unsupported type. Allowed: {sorted(C.REPORT_TYPES)}")
        return normalised

    @model_validator(mode="after")
    def _validate_section_title(self):
        """Validate that section_title is allowed for the given report type."""
        if not C.is_section_allowed_for_report_type(self.type, self.section_title):
            allowed_sections = C.get_allowed_sections_for_report_type(self.type)
            raise ValueError(
                f"Section '{self.section_title}' is not allowed for report type '{self.type}'. "
                f"Allowed sections: {allowed_sections}"
            )
        return self

class RefineRequest(BaseModel):
    type: str = Field(
        ...,
        description=(
            "Report type. Accepted values (case-insensitive, '-' or '_' allowed): "
            "commercial-proposal | feasibility-report | technical-scope"
        ),
    )
    customer_id: str
    opportunity_id: str
    section_title: str
    original_text: str = Field(..., description="Base64 of original markdown/text")
    prompt: str

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        # Apply the same normalisation logic as GenerateRequest.type
        normalised = v.strip().lower().replace("_", "-")
        if normalised not in C.REPORT_TYPES:
            raise ValueError(f"Unsupported type. Allowed: {sorted(C.REPORT_TYPES)}")
        return normalised

    @model_validator(mode="after")
    def _validate_section_title(self):
        """Validate that section_title is allowed for the given report type."""
        if not C.is_section_allowed_for_report_type(self.type, self.section_title):
            allowed_sections = C.get_allowed_sections_for_report_type(self.type)
            raise ValueError(
                f"Section '{self.section_title}' is not allowed for report type '{self.type}'. "
                f"Allowed sections: {allowed_sections}"
            )
        return self

# Job storage instance
job_storage = get_storage()

# Session states cache (for backward compatibility if needed)
SESSION_STATES: dict[str, SessionState] = {}

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
    return result[C.RESULT_KEY_CONTENT]

async def job_generate(job_id: str) -> None:
    """Background job handler for section generation."""
    job = job_storage.get_job(job_id)
    if not job:
        return
    
    try:
        # Update job status to processing
        job.update_status(JobStatus.PROCESSING)
        job_storage.update_job(job)
        
        # Extract job metadata
        metadata = job.metadata
        session_id = metadata.get(C.METADATA_KEY_SESSION_ID)
        customer_id = metadata.get(C.METADATA_KEY_CUSTOMER_ID)
        opportunity_id = metadata.get(C.METADATA_KEY_OPPORTUNITY_ID)
        report_type = metadata.get(C.METADATA_KEY_TYPE)
        section_title = metadata.get(C.METADATA_KEY_SECTION_TITLE)
        
        loop = asyncio.get_running_loop()

        def blocking_work() -> str:
            """
            Runs in a worker thread.
            Safe to block and to use asyncio.run().
            """
            session_state = asyncio.run(
                prepare_session_state(
                    session_id=session_id,
                    customer_id=customer_id,
                    opportunity_id=opportunity_id,
                    report_type=report_type,
                )
            )

            return asyncio.run(
                generate_section_internal(
                    state=session_state,
                    report_type=report_type,
                    section_title=section_title,
                    explicit_requirements=None,
                )
            )

        # Heavy work fully off event loop
        section_text: str = await loop.run_in_executor(None, blocking_work)

        # Encode generated markdown content as base64 to match the public API contract.
        section_text_b64 = base64.b64encode(section_text.encode("utf-8")).decode("ascii")

        # Update job with result
        job.update_status(
            JobStatus.COMPLETED,
            result={
                C.RESP_DATA_KEY_CUSTOMER_ID: customer_id,
                C.RESP_DATA_KEY_OPPORTUNITY_ID: opportunity_id,
                C.RESP_DATA_KEY_SECTION_TITLE: section_title,
                C.RESP_DATA_KEY_GENERATED_SECTION_B64: section_text_b64,
            }
        )
        job_storage.update_job(job)

    except Exception as e:
        # Update job with error
        job.update_status(
            JobStatus.FAILED,
            error={
                C.ENVELOPE_KEY_ERROR_CODE: C.ERR_INTERNAL_ERROR,
                C.ENVELOPE_KEY_MESSAGE: str(e),
            }
        )
        job_storage.update_job(job)

# ============================================================
# Refine Section Logic
# ============================================================

async def refine_section_internal(
    *,
    session_id: str,
    report_type: str,
    section_title: str,
    original_text: str,
    user_prompt: str,
) -> str:
    """
    Pure business logic: refine an existing section.

    The public API contract expects `original_text` to be base64-encoded UTF-8.
    Decode it here so the core refine logic always receives plain text.
    """
    try:
        # Strip whitespace (e.g. newlines from JSON/HTTP) so length matches data chars
        b64 = "".join(original_text.split())
        # Base64 length must be a multiple of 4; pad with '=' if needed
        pad_len = (4 - len(b64) % 4) % 4
        b64_padded = b64 + "=" * pad_len
        decoded_original = base64.b64decode(b64_padded).decode("utf-8")
    except Exception as e:
        raise ValueError(f"Invalid base64 in original_text: {e}") from e

    result = await refine_section(
        session_id=session_id,
        report_type=report_type,
        section_title=section_title,
        original_text=decoded_original,
        user_prompt=user_prompt,
    )
    return result[C.RESULT_KEY_REFINED_SECTION]



async def job_refine(job_id: str) -> None:
    """Background job handler for section refinement."""
    job = job_storage.get_job(job_id)
    if not job:
        return
    
    try:
        # Update job status to processing
        job.update_status(JobStatus.PROCESSING)
        job_storage.update_job(job)
        
        # Extract job metadata
        metadata = job.metadata
        session_id = metadata.get(C.METADATA_KEY_SESSION_ID)
        report_type = metadata.get(C.METADATA_KEY_TYPE)
        section_title = metadata.get(C.METADATA_KEY_SECTION_TITLE)
        original_text = metadata.get(C.METADATA_KEY_ORIGINAL_TEXT)
        user_prompt = metadata.get(C.METADATA_KEY_USER_PROMPT)
        
        loop = asyncio.get_running_loop()

        def blocking_work() -> str:
            """
            Runs in a worker thread.
            Safe to block and to use asyncio.run().
            """
            return asyncio.run(
                refine_section_internal(
                    session_id=session_id,
                    report_type=report_type,
                    section_title=section_title,
                    original_text=original_text,
                    user_prompt=user_prompt,
                )
            )

        # Heavy work fully off the event loop
        refined_text: str = await loop.run_in_executor(None, blocking_work)

        # Encode refined markdown content as base64 to match the public API contract.
        refined_text_b64 = base64.b64encode(refined_text.encode("utf-8")).decode("ascii")

        # Update job with result
        job.update_status(
            JobStatus.COMPLETED,
            result={
                C.RESP_DATA_KEY_CUSTOMER_ID: metadata.get(C.METADATA_KEY_CUSTOMER_ID),
                C.RESP_DATA_KEY_OPPORTUNITY_ID: metadata.get(C.METADATA_KEY_OPPORTUNITY_ID),
                C.RESP_DATA_KEY_SECTION_TITLE: section_title,
                C.RESP_DATA_KEY_REFINED_SECTION_B64: refined_text_b64,
            }
        )
        job_storage.update_job(job)

    except Exception as e:
        # Update job with error
        job.update_status(
            JobStatus.FAILED,
            error={
                C.ENVELOPE_KEY_ERROR_CODE: C.ERR_INTERNAL_ERROR,
                C.ENVELOPE_KEY_MESSAGE: str(e),
            }
        )
        job_storage.update_job(job)

# ============================================================
# API Endpoints
# ============================================================

@app.post("/generate", status_code=C.HTTP_202_ACCEPTED)
async def generate(
    req: GenerateRequest,
    x_api_key: Optional[str] = Header(None, alias=C.HEADER_API_KEY),
    session_id: Optional[str] = Header(None, alias=C.HEADER_SESSION_ID),
):
    """
    Generate a new section. Returns immediately with a job_id for polling.
    """
    require_api_key(x_api_key)

    if not session_id:
        raise api_error(C.HTTP_400_BAD_REQUEST, C.ERR_BAD_REQUEST, C.MSG_SESSION_ID_REQUIRED)

    # Create a new job
    job = job_storage.create_job(
        job_type=C.JOB_TYPE_GENERATE,
        metadata={
            C.METADATA_KEY_SESSION_ID: session_id,
            C.METADATA_KEY_TYPE: req.type,
            C.METADATA_KEY_CUSTOMER_ID: req.customer_id,
            C.METADATA_KEY_OPPORTUNITY_ID: req.opportunity_id,
            C.METADATA_KEY_SECTION_TITLE: req.section_title,
        }
    )

    # Start background processing
    asyncio.create_task(job_generate(job.job_id))

    return envelope(
        C.RESP_STATUS_PROCESSING,
        C.MSG_JOB_QUEUED,
        {
            C.RESP_DATA_KEY_JOB_ID: job.job_id,
            C.RESP_DATA_KEY_STATUS: job.status.value,
        }
    )

@app.post("/refine", status_code=C.HTTP_202_ACCEPTED)
async def refine(
    req: RefineRequest,
    x_api_key: Optional[str] = Header(None, alias=C.HEADER_API_KEY),
    session_id: Optional[str] = Header(None, alias=C.HEADER_SESSION_ID),
):
    """
    Refine an existing section. Returns immediately with a job_id for polling.
    """
    require_api_key(x_api_key)

    if not session_id:
        raise api_error(C.HTTP_400_BAD_REQUEST, C.ERR_BAD_REQUEST, C.MSG_SESSION_ID_REQUIRED)

    # Create a new job
    job = job_storage.create_job(
        job_type=C.JOB_TYPE_REFINE,
        metadata={
            C.METADATA_KEY_SESSION_ID: session_id,
            C.METADATA_KEY_TYPE: req.type,
            C.METADATA_KEY_CUSTOMER_ID: req.customer_id,
            C.METADATA_KEY_OPPORTUNITY_ID: req.opportunity_id,
            C.METADATA_KEY_SECTION_TITLE: req.section_title,
            C.METADATA_KEY_ORIGINAL_TEXT: req.original_text,
            C.METADATA_KEY_USER_PROMPT: req.prompt,
        }
    )

    # Start background processing
    asyncio.create_task(job_refine(job.job_id))

    return envelope(
        C.RESP_STATUS_PROCESSING,
        C.MSG_JOB_QUEUED,
        {
            C.RESP_DATA_KEY_JOB_ID: job.job_id,
            C.RESP_DATA_KEY_STATUS: job.status.value,
        }
    )


@app.get("/status/{job_id}", status_code=C.HTTP_200_OK)
async def get_job_status(
    job_id: str = PathParam(..., description="Job ID returned from /generate or /refine"),
    x_api_key: Optional[str] = Header(None, alias=C.HEADER_API_KEY),
):
    """
    Get the status of a background job.
    Returns job status, result (when completed), or error (when failed).
    """
    require_api_key(x_api_key)

    job = job_storage.get_job(job_id)
    if not job:
        raise api_error(
            C.HTTP_404_NOT_FOUND,
            C.ERR_JOB_NOT_FOUND,
            C.MSG_JOB_NOT_FOUND.format(job_id=job_id),
        )

    # Map job status to response status
    if job.status == JobStatus.COMPLETED:
        return envelope(
            C.RESP_STATUS_READY,
            C.MSG_JOB_COMPLETED,
            {
                C.RESP_DATA_KEY_JOB_ID: job.job_id,
                C.RESP_DATA_KEY_STATUS: job.status.value,
                C.RESP_DATA_KEY_RESULT: job.result,
            }
        )
    elif job.status == JobStatus.FAILED:
        return envelope(
            C.RESP_STATUS_ERROR,
            C.MSG_JOB_FAILED,
            {
                C.RESP_DATA_KEY_JOB_ID: job.job_id,
                C.RESP_DATA_KEY_STATUS: job.status.value,
                C.RESP_DATA_KEY_ERROR: job.error,
            }
        )
    elif job.status == JobStatus.PROCESSING:
        return envelope(
            C.RESP_STATUS_PROCESSING,
            C.MSG_JOB_PROCESSING,
            {
                C.RESP_DATA_KEY_JOB_ID: job.job_id,
                C.RESP_DATA_KEY_STATUS: job.status.value,
            }
        )
    else:  # PENDING
        return envelope(
            C.RESP_STATUS_PROCESSING,
            C.MSG_JOB_PENDING,
            {
                C.RESP_DATA_KEY_JOB_ID: job.job_id,
                C.RESP_DATA_KEY_STATUS: job.status.value,
            }
        )

if __name__ == "__main__":
    DEFAULT_PORT = 5001
    port = int(os.getenv("PORT", str(DEFAULT_PORT)))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
