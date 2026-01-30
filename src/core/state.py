from __future__ import annotations

import time
from typing import Dict, Optional, Any
from pydantic import BaseModel, Field


class FileRef(BaseModel):
    """
    Reference to a local, session-scoped file in .temp.
    Store paths in state (lightweight), keep heavy content on disk.
    """
    name: str                       # e.g., "discovery_call_1"
    path: str                       # e.g., ".temp/sessions/<sid>/transcripts/discovery_call_1.txt"
    fetched_at_epoch: float = Field(default_factory=lambda: time.time())


class SectionSnapshot(BaseModel):
    """
    Cache record for a report section fetched from DB.
    We store only a local path + DB freshness metadata.
    """
    section_title: str              # e.g., "executive_summary"
    path: str                       # local cached copy: ".temp/sessions/<sid>/sections/executive_summary.md"

    # DB freshness markers (use whichever your DB provides)
    db_updated_at: Optional[str] = None   # ISO timestamp (preferred)
    db_version: Optional[int] = None      # optional version int

    # Optional debugging/optimization
    content_hash: Optional[str] = None
    fetched_at_epoch: float = Field(default_factory=lambda: time.time())

class SectionRef(BaseModel):
    section_id: str
    key: str
    md_path: str
    docs_path:Optional[str] = None
    updated_at: float
    source: str = "db"  # db | generated | human



class SessionState(BaseModel):
    """
    Persistent per-session state for LangGraph.
    Keep it compact: paths + metadata, not giant blobs.

    DB is source-of-truth; we cache to avoid refetching unchanged data.
    """
    session_id: str
    customer_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    whisper_model_size: str = "small"
    whisper_language: Optional[str] = None
    fail_fast: bool = False


    # Extracted transcripts (created once per session, reused)
    # Key by transcript name or id.
    transcripts: Dict[str, FileRef] = Field(default_factory=dict)

    # Extracted context 
    context_extracted: bool = False
    context: Optional[FileRef] = None 
    context_stats: Optional[FileRef] = None         
    context_json: Optional[Dict[str, Any]] = None

    # Cached DB sections (human-edited): local copies + freshness metadata
    # sections: Dict[str, SectionSnapshot] = Field(default_factory=dict)
    completed_sections: Dict[str, SectionRef] = Field(default_factory=dict)
    completed_sections_fetched_at: Dict[str, float] = Field(default_factory=dict)

    # Any other session files (attachments, parsed JSON, etc.)
    cached_paths: Dict[str, str] = Field(default_factory=dict)

    # Bookkeeping
    transcripts_loaded: bool = False
    context_loaded: bool = False
    last_db_sync_epoch: Optional[float] = None
    last_updated_epoch: float = Field(default_factory=lambda: time.time())



