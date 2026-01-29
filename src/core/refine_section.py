
from __future__ import annotations

import base64
from pathlib import Path
from typing import Dict, Any

from src.core.state import SessionState
from src.core.tools.llm_client import generate_text
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def _build_refine_prompt(
    *,
    report_type: str,
    section_title: str,
    user_prompt: str,
    original_text: str,
    facts_text: str,
) -> str:
    return f"""
You are a precise document editor.

TASK
Refine an existing report section based on an explicit user instruction.

IMPORTANT HIERARCHY (must follow strictly):
1) User instruction (highest priority)
2) Original section text
3) Facts (reference only, optional)

DO NOT:
- Invent new facts, numbers, timelines, systems, or costs
- Add content not implied by the original text or explicitly requested
- Rewrite the section unless asked
- “Improve” factual accuracy unless instructed
- Introduce facts unless the user explicitly asks to align with facts

YOU MAY:
- Rephrase, reorganize, or adjust tone/style if asked
- Clarify language
- Remove redundancy
- Correct inconsistencies ONLY if the user explicitly asks
- Use facts ONLY if the instruction requires factual alignment

DOCUMENT TYPE:
{report_type}

SECTION:
{section_title}

USER INSTRUCTION:
{user_prompt}

ORIGINAL SECTION (authoritative):
<<<
{original_text}
>>>

FACTS (reference only — use ONLY if instruction requires):
<<<
{facts_text}
>>>

EDITING RULES:
- Preserve original meaning unless the instruction demands change
- If instruction conflicts with facts, follow the instruction and do NOT “correct” it silently
- If instruction is ambiguous, make the smallest reasonable change
- Keep section length roughly similar unless instructed otherwise
- Maintain professional consulting-style language

OUTPUT:
Return ONLY the refined section content in Markdown.
No explanations.
No commentary.
No diff.
""".strip()


async def refine_section(
    *,
    session_id: str,
    report_type: str,
    section_title: str,
    original_text: str,
    user_prompt: str,
) -> Dict[str, Any]:

    # original_text may be empty when the caller wants the LLM to generate
    # content from scratch based on the prompt. We only require that the
    # parameter is present, not that it is non-empty.

    def extract_state(cp) -> SessionState:
        if cp is None:
            raise RuntimeError("No checkpoint found")

        if not isinstance(cp, dict):
            raise RuntimeError(f"Unexpected checkpoint type: {type(cp)}")

        if "channel_values" not in cp:
            raise RuntimeError(
                f"Checkpoint missing channel_values. Keys={list(cp.keys())}"
            )

        channel_values = cp["channel_values"]

        try:
            return SessionState(**channel_values)
        except Exception as e:
            raise RuntimeError(
                f"Failed to reconstruct SessionState from channel_values. "
                f"Keys={list(channel_values.keys())}"
            ) from e



    # Ensure the checkpoint directory exists before opening SQLite, otherwise
    # we may see "unable to open database file" errors.
    db_path = Path(".temp") / "langgraph_checkpoints.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:

        cp = await checkpointer.aget(
            config={"configurable": {"thread_id": session_id}}
        )

        if not cp:
            raise RuntimeError("Session not initialized")

        state: SessionState = extract_state(cp)

        facts_text = ""
        if state and state.context and state.context_extracted:
            facts_path = Path(state.context.path)
            if facts_path.exists():
                facts_text = facts_path.read_text(
                    encoding="utf-8", errors="ignore"
                )

        prompt = _build_refine_prompt(
            report_type=report_type,
            section_title=section_title,
            user_prompt=user_prompt,
            original_text=original_text,
            facts_text=facts_text,
        )

        refined_text: str = generate_text(prompt)

        return {
            "section_title": section_title,
            "report_type": report_type,
            "refined_section": refined_text,
        }
