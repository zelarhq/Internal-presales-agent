"""
constants.py
Central place for API constants used by FastAPI + frontend contract.
"""

from __future__ import annotations
import os
from typing import List

# ============================================================
# Security / Headers
# ============================================================

HEADER_API_KEY: str = "X-API-Key"
HEADER_SESSION_ID: str = "Session-Id"
HEADER_IDEMPOTENCY_KEY: str = "X-Idempotency-Key"  # optional, recommended
HEADER_REQUEST_ID = "X-Request-Id" 

API_KEY: str = os.getenv("API_KEY", "abc123")

# Useful if you want to generate absolute URLs in responses (optional)
PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080")

# ============================================================
# CORS
# ============================================================

# Comma-separated origins in env: "http://localhost:3000,https://your-frontend"
_frontend_origins_env = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000")
FRONTEND_ORIGINS: List[str] = [o.strip() for o in _frontend_origins_env.split(",") if o.strip()]

# ============================================================
# Response Status Strings (envelope.status)
# ============================================================

RESP_STATUS_OK = "ok"
RESP_STATUS_PROCESSING = "processing"
RESP_STATUS_READY = "ready"
RESP_STATUS_BUSY = "busy"
RESP_STATUS_ERROR = "error"

# ============================================================
# HTTP Status Codes
# ============================================================

HTTP_200_OK = 200
HTTP_202_ACCEPTED = 202
HTTP_400_BAD_REQUEST = 400
HTTP_401_UNAUTHORIZED = 401
HTTP_404_NOT_FOUND = 404
HTTP_422_UNPROCESSABLE_ENTITY = 422
HTTP_500_INTERNAL_SERVER_ERROR = 500

# ============================================================
# Error Codes (envelope.data.error_code)
# ============================================================

ERR_AUTH_INVALID_API_KEY = "AUTH_INVALID_API_KEY"
ERR_BAD_REQUEST = "BAD_REQUEST"
ERR_VALIDATION_ERROR = "VALIDATION_ERROR"
ERR_INTERNAL_ERROR = "INTERNAL_ERROR"
ERR_NOT_FOUND = "NOT_FOUND"
ERR_JOB_NOT_FOUND = "JOB_NOT_FOUND"

# ============================================================
# Job Types
# ============================================================

JOB_TYPE_GENERATE = "generate"
JOB_TYPE_REFINE = "refine"

# ============================================================
# Job Metadata Keys
# ============================================================

METADATA_KEY_SESSION_ID = "session_id"
METADATA_KEY_CUSTOMER_ID = "customer_id"
METADATA_KEY_OPPORTUNITY_ID = "opportunity_id"
METADATA_KEY_TYPE = "type"
METADATA_KEY_SECTION_TITLE = "section_title"
METADATA_KEY_ORIGINAL_TEXT = "original_text"
METADATA_KEY_USER_PROMPT = "user_prompt"

# ============================================================
# Response Data Keys
# ============================================================

RESP_DATA_KEY_JOB_ID = "job_id"
RESP_DATA_KEY_STATUS = "status"
RESP_DATA_KEY_RESULT = "result"
RESP_DATA_KEY_ERROR = "error"
RESP_DATA_KEY_CUSTOMER_ID = "customer_id"
RESP_DATA_KEY_OPPORTUNITY_ID = "opportunity_id"
RESP_DATA_KEY_SECTION_TITLE = "section_title"
RESP_DATA_KEY_GENERATED_SECTION_B64 = "generated_section_b64"
RESP_DATA_KEY_REFINED_SECTION_B64 = "refined_section_b64"

# ============================================================
# Response Messages
# ============================================================

MSG_JOB_QUEUED = "Job queued"
MSG_JOB_COMPLETED = "Job completed"
MSG_JOB_FAILED = "Job failed"
MSG_JOB_PROCESSING = "Job processing"
MSG_JOB_PENDING = "Job pending"
MSG_SESSION_ID_REQUIRED = "Session-Id is required"
MSG_INVALID_API_KEY = "Invalid API key"
MSG_INTERNAL_SERVER_ERROR = "Internal server error"
MSG_JOB_NOT_FOUND = "Job {job_id} not found"
MSG_ERROR_OCCURRED = "An error occurred"
MSG_INVALID_VALUE = "Invalid value"

# ============================================================
# Envelope Dictionary Keys
# ============================================================

ENVELOPE_KEY_STATUS = "status"
ENVELOPE_KEY_MESSAGE = "message"
ENVELOPE_KEY_DATA = "data"
ENVELOPE_KEY_ERROR_CODE = "error_code"
ENVELOPE_KEY_PATH = "path"
ENVELOPE_KEY_DETAILS = "details"

# ============================================================
# Result Dictionary Keys
# ============================================================

RESULT_KEY_CONTENT = "content"
RESULT_KEY_REFINED_SECTION = "refined_section"

# ============================================================
# Report Types (request.type)
# ============================================================

# --- existing constants above stay EXACTLY the same ---


# =========================
# Report sections (CONFIGURABLE)
# =========================
#
# NOTE: These section lists are defaults and can be modified as needed.
# To change sections:
# 1. Update the section constants below (e.g., SECTION_EXECUTIVE_SUMMARY)
# 2. Update the REPORT_SECTIONS dictionary to include/exclude sections
# 3. The API will automatically validate against these lists
# 4. All section-related code uses these constants to avoid hardcoding
#

# Canonical report type values (must match your API docs exactly)
REPORT_TYPE_FEASIBILITY = "feasibility-report"
REPORT_TYPE_TECHNICAL_SCOPE = "technical-scope"
REPORT_TYPE_COMMERCIAL_PROPOSAL = "commercial-proposal"

# Canonical section titles (as used by frontend in section_title)
# These are the default section titles - modify as needed for your use case
# Feasibility report sections
SECTION_EXECUTIVE_SUMMARY = "Executive Summary"
SECTION_PROJECT_OVERVIEW = "Project Overview"
SECTION_BUSINESS_REQUIREMENTS = "Business Requirements"
SECTION_TECHNICAL_ASSESSMENT = "Technical Assessment"
SECTION_RESOURCE_ASSESSMENT = "Resource Assessment"
SECTION_COST_BENEFIT_ANALYSIS = "Cost-Benefit Analysis"
SECTION_RISK_ASSESSMENT = "Risk Assessment"
SECTION_ALTERNATIVE_SOLUTIONS = "Alternative Solutions"
SECTION_TIMELINE_FEASIBILITY = "Timeline Feasibility"
SECTION_STAKEHOLDER_ANALYSIS = "Stakeholder Analysis"
SECTION_RECOMMENDATIONS = "Recommendations"
SECTION_APPENDIX = "Appendix"

# Technical scope sections
SECTION_COMPANY_BACKGROUND = "Company Background"
SECTION_CURRENT_STATE_ANALYSIS = "Current State Analysis"
SECTION_REQUIREMENTS_OVERVIEW = "Requirements Overview"
SECTION_PROPOSED_SOLUTION = "Proposed Solution"
SECTION_TECHNOLOGY_STACK = "Technology Stack"
SECTION_INTEGRATION_POINTS = "Integration Points"
SECTION_SECURITY_COMPLIANCE = "Security & Compliance"
SECTION_IMPLEMENTATION_TIMELINE = "Implementation Timeline"
SECTION_RESOURCE_REQUIREMENTS = "Resource Requirements"
SECTION_RISKS_MITIGATIONS = "Risks & Mitigations"
SECTION_ASSUMPTIONS_DEPENDENCIES = "Assumptions & Dependencies"

# Allowed + ordered sections per report type
# This dictionary defines which sections are valid for each report type.
# Modify this to add/remove/reorder sections as needed.
# The API will automatically validate incoming requests against these lists.
REPORT_SECTIONS = {
    REPORT_TYPE_FEASIBILITY: [
        SECTION_EXECUTIVE_SUMMARY,
        SECTION_PROJECT_OVERVIEW,
        SECTION_BUSINESS_REQUIREMENTS,
        SECTION_TECHNICAL_ASSESSMENT,
        SECTION_RESOURCE_ASSESSMENT,
        SECTION_COST_BENEFIT_ANALYSIS,
        SECTION_RISK_ASSESSMENT,
        SECTION_ALTERNATIVE_SOLUTIONS,
        SECTION_TIMELINE_FEASIBILITY,
        SECTION_STAKEHOLDER_ANALYSIS,
        SECTION_RECOMMENDATIONS,
        SECTION_APPENDIX,
    ],
    REPORT_TYPE_TECHNICAL_SCOPE: [
        SECTION_EXECUTIVE_SUMMARY,
        SECTION_COMPANY_BACKGROUND,
        SECTION_CURRENT_STATE_ANALYSIS,
        SECTION_REQUIREMENTS_OVERVIEW,
        SECTION_PROPOSED_SOLUTION,
        SECTION_TECHNOLOGY_STACK,
        SECTION_INTEGRATION_POINTS,
        SECTION_SECURITY_COMPLIANCE,
        SECTION_IMPLEMENTATION_TIMELINE,
        SECTION_RESOURCE_REQUIREMENTS,
        SECTION_RISKS_MITIGATIONS,
        SECTION_ASSUMPTIONS_DEPENDENCIES,
    ],
    # Keep commercial proposal empty for now unless you share its UI section list
    REPORT_TYPE_COMMERCIAL_PROPOSAL: [],
}

# Quick validation helper constants (optional usage in code)
REPORT_TYPES = set(REPORT_SECTIONS.keys())

# Helper function to get allowed sections for a report type
def get_allowed_sections_for_report_type(report_type: str) -> list[str]:
    """
    Get the list of allowed section titles for a given report type.
    Returns empty list if report type is not found.
    """
    return REPORT_SECTIONS.get(report_type, [])

# Helper function to validate if a section title is allowed for a report type
def is_section_allowed_for_report_type(report_type: str, section_title: str) -> bool:
    """
    Check if a section title is allowed for a given report type.
    Returns False if report type or section is not found.
    """
    allowed_sections = get_allowed_sections_for_report_type(report_type)
    return section_title in allowed_sections

# Helper function to get all unique section titles across all report types
def get_all_section_titles() -> set[str]:
    """
    Get all unique section titles across all report types.
    """
    all_titles = set()
    for sections in REPORT_SECTIONS.values():
        all_titles.update(sections)
    return all_titles



# ============================================================
# (Optional) HTML snippets / UI helpers
# Only keep these if backend returns pre-renderable HTML blocks.
# If frontend renders everything, delete this section.
# ============================================================

HTML_LINE_BREAK = "<br/>"
HTML_BOLD_OPEN = "<b>"
HTML_BOLD_CLOSE = "</b>"
