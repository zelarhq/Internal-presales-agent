from __future__ import annotations
import time
# from fastapi import FastAPI, Header, HTTPException
from typing import Optional
# import uuid
from src.core import state
from src.core import state
from src.core.graphs.build_session_graph import build_sessiongraph
from src.core.state import SessionState
# from src.core.nodes.section_writer_node import ensure_section_generated
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from typing import Dict, Any, Optional
from pathlib import Path

from src.core.state import SessionState, SectionRef
from src.core.tools.llm_client import generate_text
from src.core.schemas.sections_schema import DOCUMENT_SECTIONS_CONFIG

# ------------------------------------------------------------------------
# Function for preparing session state
# ------------------------------------------------------------------------

async def prepare_session_state(
    *,
    session_id: str,
    customer_id: str,
    opportunity_id: str,
    report_type: str,
):
    """
    Prepare the LangGraph-backed session state.

    SQLite will fail with "unable to open database file" if the parent
    directory does not exist, so we ensure `.temp/` is created before
    initialising the async checkpointer.
    """
    db_path = Path(".temp") / "langgraph_checkpoints.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        compiled = build_sessiongraph().compile(checkpointer=checkpointer)

        state_dict = await compiled.ainvoke(
            {"session_id": session_id},
            config={
                "configurable": {
                    "thread_id": session_id,
                    "customer_id": customer_id,
                    "opportunity_id": opportunity_id,
                    "report_type": report_type
                }
            },
        )

       
    return SessionState.model_validate(state_dict)


# ------------------------------------------------------------------------
# Function for writing a section
# ------------------------------------------------------------------------

def filter_input_for_section(section_name, section_rules, facts) -> str:
    prompt = f"""
You are a content filter for a consulting report section.

SECTION TITLE
{section_name}

SECTION RULES (ABSOLUTE)
{section_rules}

TASK
From the raw text below:
- KEEP only content that is relavant to the section title and rules
- DO NOT rewrite, summarize.
- Also keep supporting text that provides necessary context for understanding.


RAW TEXT
\"\"\"
{facts}
\"\"\"

OUTPUT
Return ONLY the filtered text.
"""
    filtered_text = generate_text(prompt)
    return filtered_text


def _build_section_prompt(
    *,
    report_type: str,
    section_title: str,
    explicit_requirements: Optional[str],
    facts_text: str,
    prior_sections: str,
    section_rules: str,
) -> str:
    requirements_block = (
        f"\nEXPLICIT SECTION REQUIREMENTS:\n{explicit_requirements}\n"
        if explicit_requirements
        else ""
    )

    return f"""
You are writing a professional report section.

DOCUMENT TYPE:
{report_type}

SECTION:
{section_title}

SECTION INTENT:
{section_rules} or "Infer intent from context and facts."


FACTS:
{facts_text}

The following sections have already been finalized. Use them only for consistency of terminology and assumptions. 
Do NOT restate or reinterpret them.”

PREVIOUS SECTIONS FOR REFERENCE(aUTHORITATIVE):
{prior_sections}

You are producing a polished consulting deliverable for a specific section of a larger report.

Objectives and Audience:

    Write for senior decision-makers.

    Translate discussion points into a clear business narrative, not transcripts, meeting notes, or raw action items.

Content Rules:

    Use only the facts explicitly provided.

    If information is missing or unclear, state assumptions explicitly and concisely.

    You are authorized to ignore, compress, or remove extracted points that do not serve the section’s narrative purpose.

    Do not introduce speculative ideas, informal commentary, or brainstorming unless explicitly requested.

    Do not repeat background facts verbatim from other sections; build on them where relevant.

Style and Tone:

    Clear, professional, consulting-style language.

    Neutral, factual, confident tone; avoid hedging.

    Concise, structured, and non-repetitive.

    Avoid operational chatter and internal reminders.

    Avoid overuse of buzzwords; use technical terms only when they add precision.

    Maintain consistency in terminology, tense, and naming throughout the section.

    VERY IMPORTANT:

   - Write a concise, professional section in a narrative style.
   - Organize the content into logical paragraphs with clear flow and transitions.
   - Avoid listing facts. Integrate them into a coherent story that explains capabilities, delivery approach, and operational realities.”

Structure and Formatting:
    the section must be self-contained and logically organized.

    Use clear sectioning and logical flow.

    Use tables where they improve clarity or comparability.

    Use bullet points only when they materially enhance understanding.

    Ensure the section reads as a standalone, polished deliverable.

Output Requirement:

    Return only the final section content as text.

    Do not include explanations, process notes, or references to instructions.

    Before finalizing, verify that:
    - No individual names are mentioned
    - No meetings, calls, emails, or coordination activities appear
    - No future actions or next steps are listed
    If any are present, remove them.
""".strip()


def finalise_section(section_name, section_content, section_rules) -> str:
    prompt = f"""
You are a content editor for a consulting report section.

SECTION TITLE
{section_name}

SECTION RULES (ABSOLUTE)
{section_rules}

TASK
From the section content below:
- Keep all the informaion.
- Improve the tone to a narrative style and ensure logical flow.
- Ensure there are no mentions of meetings, calls, emails, coordination activities, or individual names.
- Ensure there is no content dump.
- Ensure the tone is professional consulting-style.
- Return in text format.


Section Content
\"\"\"
{section_content}
\"\"\"

OUTPUT
Return the finalised section.
"""
    finalised_text = generate_text(prompt)
    return finalised_text


async def write_section(
    state: SessionState,
    *,
    report_type: str,
    # section_key: str,
    section_title: Optional[str] = None,
    explicit_requirements: Optional[str] = None,
) -> Dict[str, Any]:
    
    """
    Generates a single report section.
    """

    print("Generating section...")

    # 1. Checking prerequisites....
    # We require that the context extraction step has run at least once for
    # this session, but it's valid for there to be no transcript-derived
    # context (e.g. no files uploaded). In that case, context may be None and
    # we simply proceed with an empty facts_text.
    if not getattr(state, "context_extracted", False):
        raise ValueError("Context must be extracted before section generation.")

    if state.context and state.context.path:
        facts_text = Path(state.context.path).read_text(
            encoding="utf-8", errors="ignore"
        )
    else:
        facts_text = ""

    # 2. Extracting prior sections for reference
    sections_dir = Path(".temp") / state.session_id / "sections"

    prior_sections = []

    if sections_dir.exists():
        for p in sorted(sections_dir.glob("*.txt")):
            prior_sections.append(
                f"### {p.stem}\n{p.read_text(encoding='utf-8', errors='ignore')}"
            )

    # 3. Extracting section configuration and requirements from schema

    print(report_type, section_title)

    def get_report_cfg(report_type: str):
        try:
            return DOCUMENT_SECTIONS_CONFIG[report_type]
        except KeyError:
            raise ValueError(f"Report '{report_type}' not found")


    def normalize(text: str) -> str:
        return text.strip().lower().replace("-", " ")


    def get_section_cfg(report_cfg, section_name: str):
        section_name_norm = normalize(section_name)

        for section in report_cfg.sections:
            print(f"{normalize(section.title)}, {section_name_norm}")
            if normalize(section.title) == section_name_norm:
               
                print(f"section {section_name} found in schema")
                return section

        return None


    report_cfg = get_report_cfg(report_type)
    section_cfg = get_section_cfg(report_cfg, section_title)

    if section_cfg:
        section_key = section_cfg.key
        section_rules = section_cfg.llm_requirements
    else:
        # Fallback: generate section key from title if not in schema
        # This allows flexibility for sections not yet in the schema
        section_key = section_title.lower().replace(" ", "-")
        section_rules = (
            "This section is not defined in the schema. "
            "Write only content explicitly relevant to the section title. "
            "Use only facts present in the provided context. "
            "Do not introduce recommendations, solutions, timelines, "
            "or content from other sections."
        )

    print(section_rules)

    filtered_facts = filter_input_for_section(section_title, section_cfg, facts_text)

    # 4. Build prompt
    prompt = _build_section_prompt(
        report_type=report_type,
        section_title=section_title,  
        explicit_requirements=explicit_requirements,
        facts_text=facts_text,
        prior_sections="\n\n".join(prior_sections),
        section_rules=section_rules,
    )

    # 5. Generate section content
    section_content = generate_text(prompt)
    section_md = finalise_section(section_title, section_content, section_rules)


    # 6. update session state with section ref
    session_dir = Path(".temp") / "sections" / state.session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    section_path = session_dir / f"{section_key}.md"
    section_path.write_text(section_md, encoding="utf-8")

    now = time.time()

    section_ref = SectionRef(
        section_id=f"{section_key}_{int(now)}",
        key=section_key,
        path=str(section_path),
        updated_at=now,
        source="generated",
    )

    return {
        "key": section_key,
        "title": section_title,
        "content": section_md,
        "report_type": report_type,
        "completed_sections": {
            **state.completed_sections,
            section_key: section_ref,
        },
        "completed_sections_fetched_at": {
            **state.completed_sections_fetched_at,
            section_key: now,
        },
    }
    
