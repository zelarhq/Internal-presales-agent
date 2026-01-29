from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from pydantic import ValidationError

from src.core.state import SessionState
from src.core.state import FileRef
from src.core.tools.llm_client import generate_json
from src.core.tools.chunk_text import chunk_text
from src.core.schemas.fact_schema import Fact

OUT_DIR = Path(".temp/context")

# ------------------------
# helpers
# ------------------------


def get_json_schema(model: Any) -> dict:
    if hasattr(model, "model_json_schema"): 
        return model.model_json_schema()
    return model.schema()  

FACT_SCHEMA_JSON = get_json_schema(Fact)
FACT_SCHEMA_TEXT = json.dumps(FACT_SCHEMA_JSON, indent=2)




def _normalize(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _dedupe_merge(
    existing: List[Dict[str, Any]],
    new: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Dedupe by (type + normalized value).
    Keep the higher-confidence fact.
    Preserve evidence where possible.
    """
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    index: Dict[tuple[str, str], Dict[str, Any]] = {}

    def upsert(item: Dict[str, Any]):
        key = (item.get("type", "OTHER"), _normalize(item.get("value", "")))
        if not key[1]:
            return

        if key not in index:
            index[key] = item
            return

        cur = index[key]
        if rank.get(item.get("confidence", "LOW"), 0) > rank.get(cur.get("confidence", "LOW"), 0):
            index[key] = item
        else:
            # light evidence merge
            cur_ev = cur.get("evidence") or {}
            new_ev = item.get("evidence") or {}
            if not cur_ev.get("quote") and new_ev.get("quote"):
                cur_ev["quote"] = new_ev["quote"]
            cur["evidence"] = cur_ev

    for it in existing:
        upsert(it)
    for it in new:
        upsert(it)

    return list(index.values())


def _read_transcripts(state: SessionState) -> Dict[str, Dict[str, str]]:
    """
    Returns:
      {
        transcript_key: {
          "text": "...",
          "file_name": "call1.txt"
        }
      }
    """
    out: Dict[str, Dict[str, str]] = {}
    for key, ref in state.transcripts.items():
        p = Path(ref.path)
        out[key] = {
            "text": p.read_text(encoding="utf-8", errors="ignore") if p.exists() else "",
            "file_name": p.name,
        }
    return out


def _facts_prompt(
    *,
    transcript_key: str,
    transcript_file: str,
    chunk_id: int,
    chunk_text: str,
) -> str:
    return f"""
Extract atomic facts from the transcript chunk.

Return ONLY JSON: a list of fact objects with keys exactly:
- type (one of: OBJECTIVE, PROBLEM, KPI, WORKFLOW, WORKFLOW_STEP, PAIN_POINT, SYSTEM, INTEGRATION_TARGET,
  DATA_SOURCE, DATA_QUALITY, DATA_VOLUME, ACCESS_CONSTRAINT, TIMELINE, MILESTONE, PHASE, RESOURCE,
  COST_CAPEX, COST_OPEX, PRICING_MODEL, ROI_ASSUMPTION, RISK, MITIGATION, DECISION, 
  ACTION_ITEM, OPEN_QUESTION, OTHER)
- value (string)
- confidence (HIGH/MEDIUM/LOW)
- evidence: {{
    transcript_key,
    transcript_file,
    chunk_id,
    quote,
    anchor
  }}

FACT JSON SCHEMA:
{FACT_SCHEMA_TEXT}

Rules:
- Be exhaustive. Prefer many small facts over fewer big ones.
- Do NOT invent. If uncertain, keep confidence LOW.
- quote must be a short excerpt (<=200 chars) from this chunk.

transcript_key = {transcript_key}
transcript_file = {transcript_file}
chunk_id = {chunk_id}

CHUNK:
{chunk_text}
""".strip()


# ------------------------
# main node
# ------------------------



async def ensure_context_extracted(state: SessionState) -> Dict[str, Any]:
    """
    Extract atomic, evidence-backed facts from all transcripts.
    Runs once per session.
    """

    # no-op if already done and artifact exists
    if (
        state.context_extracted
        and state.context
        and Path(state.context.path).exists()
    ):
        return {}

    if not state.transcripts:
        return {
            "context_extracted": False,
            "context": None,
        }
        
    if not state.transcripts_loaded:
        raise ValueError("Transcripts must be loaded before extracting facts.")
    
    print("Extracting context/facts from transcripts...")

    transcripts = _read_transcripts(state)


    all_facts: List[Dict[str, Any]] = []
    extraction_stats: Dict[str, Any] = {}

    for tkey, payload in transcripts.items():
        text = payload["text"]
        file_name = payload["file_name"]

        chunks = chunk_text(text, max_chars=12000, overlap_chars=1200)
        chunks_with_facts: List[int] = []

        for ch in chunks:
            prompt = _facts_prompt(
                transcript_key=tkey,
                transcript_file=file_name,
                chunk_id=ch.chunk_id,
                chunk_text=ch.text,
            )

            try:
                raw = generate_json(
                    prompt,
                    schema_name="Context",
                    temperature=0.2,
                )
            except Exception:
                continue

            if not isinstance(raw, list):
                continue

            chunk_facts: List[Dict[str, Any]] = []
            for item in raw:
                try:
                    fact = Fact.model_validate(item)
                    chunk_facts.append(fact.model_dump())
                except ValidationError:
                    continue

            if chunk_facts:
                chunks_with_facts.append(ch.chunk_id)
                all_facts = _dedupe_merge(all_facts, chunk_facts)

        # lightweight stats (debuggable, optional)
        extraction_stats[tkey] = {
            "transcript_file": file_name,
            "num_chunks": len(chunks),
            "chunks_with_facts": chunks_with_facts,
        }

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    facts_path = OUT_DIR / f"{state.session_id}_facts.json"
    stats_path = OUT_DIR / f"{state.session_id}_facts_stats.json"

    facts_path.write_text(
        json.dumps(all_facts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    stats_path.write_text(
        json.dumps(extraction_stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "context_extracted": True,
        "context": FileRef(
            name="context_facts",
            path=str(facts_path),
        ),
        # optional: keep stats path if you want to inspect coverage
        "context_stats": FileRef(
            name="context_facts_stats",
            path=str(stats_path),
        ),
    }
