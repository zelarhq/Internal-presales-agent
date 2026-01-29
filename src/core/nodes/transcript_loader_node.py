from __future__ import annotations
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Dict
from src.core.tools.supabase_db import supabase
from src.core.state import SessionState, FileRef
from pathlib import Path
from src.core.tools.transcript_extractor import extract_text_any, ExtractOptions, ExtractionError

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".mp4"}


@dataclass
class TranscriptBlob:
    name: str
    filename: str
    content: bytes

#-------------------------------------------------------------------
# Getting files from supabase db/storage
#-------------------------------------------------------------------
def fetch_opportunity_files(
    opportunity_id: str,
    *,
    discovery_call_id: Optional[str] = None,
    mime_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    try:
        query = (
            supabase
            .table("opportunity_files")
            .select(
                "id, opportunity_id, discovery_call_id, file_name, file_path, "
                "file_size, mime_type, description, created_at"
            )
            .eq("opportunity_id", opportunity_id)
        )

        if discovery_call_id:
            query = query.eq("discovery_call_id", discovery_call_id)

        if mime_types:
            query = query.in_("mime_type", mime_types)

        response = query.order("created_at").execute()

    except Exception as e:
        raise RuntimeError(f"Supabase error: {type(e).__name__}: {e}") from e

    return response.data or []

#-------------------------------------------------------------------
# Define storage bucket
# -------------------------------------------------------------

STORAGE_BUCKET = "opportunity-files"

#-------------------------------------------------------------------
# Fetch transcript blobs
# -------------------------------------------------------------

def fetch_transcript_blobs(opportunity_id: str) -> List[TranscriptBlob]:
    files = fetch_opportunity_files(
        opportunity_id,
        # mime_types=TRANSCRIPT_MIME_TYPES,
    )

    blobs: List[TranscriptBlob] = []
    failures: List[str] = []

    for f in files:
        file_path = f.get("file_path")
        file_name = f.get("file_name")

        if not file_path or not file_name:
            continue

        try:
            content: bytes = supabase.storage.from_(STORAGE_BUCKET).download(file_path)

            if not content:
                continue

            blob = TranscriptBlob(
                name=f.get("description") or file_name,
                filename=file_name,
                content=content,
            )
            blobs.append(blob)

        except Exception as e:
            failures.append(f"{file_name}: {e}")

    if failures:
        print("Transcript fetch failures:")
        for f in failures:
            print("  -", f)

    return blobs

#-------------------------------------------------------------------
# Helper functions for transcript loading + extraction
#-------------------------------------------------------------------

def _safe_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9_\-]+", "_", s)
    return s[:80] or "file"


def transcripts_base_dir(session_id: str) -> Path:
    p = Path(".temp") / "transcripts" / session_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def transcripts_raw_dir(session_id: str) -> Path:
    p = transcripts_base_dir(session_id) / "raw"
    p.mkdir(parents=True, exist_ok=True)
    return p


def transcripts_extracted_dir(session_id: str) -> Path:
    p = transcripts_base_dir(session_id) / "extracted"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _dedupe_name(name_key: str, out_dir: Path) -> str:
    base = name_key
    i = 2
    while (out_dir / f"{name_key}.txt").exists():
        name_key = f"{base}_{i}"
        i += 1
    return name_key


#-------------------------------------------------------------------
# Main function: load + extract transcripts once per session
#-------------------------------------------------------------------

async def load_transcripts_once_per_session(
    state: SessionState,
    *,
    customer_id: str,
    opportunity_id: str,
    fail_fast: bool = False,
    max_bytes: int = 25 * 1024 * 1024,
) -> Dict[str, Any]:
    if getattr(state, "transcripts_loaded", False) and getattr(state, "transcripts", None):
        return {}

    raw_dir = transcripts_raw_dir(state.session_id)
    out_dir = transcripts_extracted_dir(state.session_id)

    blobs = fetch_transcript_blobs(opportunity_id)

    failures: List[str] = []

    opts = ExtractOptions(max_bytes=max_bytes, md_mode="keep")

    new_transcripts: Dict[str, FileRef] = {}

    for blob in blobs:
        try:
            ext = Path(blob.filename).suffix.lower()
            base_name = _safe_name(blob.name or Path(blob.filename).stem)
            name_key = _dedupe_name(base_name, out_dir)

            raw_path = raw_dir / f"{name_key}{ext or ''}"
            raw_path.write_bytes(blob.content)

            
            text = extract_text_any(raw_path, opts=opts)

            txt_path = out_dir / f"{name_key}.txt"
            txt_path.write_text(text, encoding="utf-8", errors="ignore")

            new_transcripts[name_key] = FileRef(
                name=name_key,
                path=str(txt_path),
                fetched_at_epoch=time.time(),
            )

        except (ExtractionError, RuntimeError, Exception) as e:
            msg = f"{blob.filename} ({blob.name}): {type(e).__name__}: {e}"
            failures.append(msg)
            if fail_fast:
                raise

    patch: Dict[str, Any] = {
        "customer_id": customer_id,
        "opportunity_id": opportunity_id,
        "last_updated_epoch": time.time(),
    }

    merged = dict(state.transcripts) if getattr(state, "transcripts", None) else {}
    merged.update(new_transcripts)

    patch["transcripts"] = merged


    if failures:
        fail_path = out_dir / "_failures.txt"
        fail_path.write_text("\n".join(failures), encoding="utf-8", errors="ignore")

        cached = dict(getattr(state, "cached_paths", {}) or {})
        cached["transcript_failures"] = str(fail_path)
        patch["cached_paths"] = cached

    
    patch["transcripts_loaded"] = bool(merged)

    return patch

#---------------------------------------------------
# Define node
#--------------------------------------------------

async def ensure_transcripts_loaded(state: SessionState) -> SessionState:
    """
    LangGraph node: fetch + extract transcripts ONCE per session.

    Requirements:
      - customer_id and opportunity_id must be available either in:
          (a) config["configurable"], or
          (b) already stored in state

    Side effects:
      - Writes raw + extracted transcript files under:
          .temp/transcripts/<session_id>/raw/
          .temp/transcripts/<session_id>/extracted/
      - Updates:
          state.transcripts[...]  -> FileRef(name, path)
          state.cached_paths["transcript_failures"] -> optional debug file
          state.transcripts_loaded = True
    """
    customer_id = state.customer_id
    opportunity_id = state.opportunity_id

    print("Loading transcripts for the given opportunity......")

    # If identifiers are missing (e.g. legacy data or documents not linked to
    # an opportunity), skip transcript loading instead of failing the graph.
    # The rest of the pipeline can continue using other context sources.
    if not customer_id or not opportunity_id:
        return state

    return await load_transcripts_once_per_session(
        state,
        customer_id=customer_id,
        opportunity_id=opportunity_id,
        fail_fast=state.fail_fast,
    )

#=========================================================================================
# =======================================================================================

if __name__ == "__main__":

    # Quick sanity check
    opp_id = "3822df74-6daf-410d-a119-727e077af555"
    files = fetch_opportunity_files(opp_id)
    print(f"Found {len(files)} files")
    for f in files:
        print(f["file_name"], f["mime_type"])
    blobs = fetch_transcript_blobs(opp_id)
    print(f"Fetched {len(blobs)} blobs")





 




