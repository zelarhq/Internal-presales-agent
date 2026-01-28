InternalAgent is a AI system for generating, refining, and managing long-form business documents (Feasibility Reports, Technical Scopes, Commercial Proposals) from messy inputs such as discovery calls, transcripts, and human edits.

It is a **stateful document intelligence pipeline** designed to behave predictably under regeneration, refinement, and human-in-the-loop workflows.

---

## ✨ Key Capabilities

- 🧾 Generate report sections **one at a time**
- ✏️ Refine existing sections faithfully (instruction-first)
- 🔄 Sync human-edited sections from DB on every generate call
- 📚 Extract and reuse facts from transcripts
- 🔁 Regenerate sections without re-interpreting raw calls
- 👤 Treat human edits as authoritative
- 🧠 Ready for Knowledge Base / RAG integration
- 🔍 Fully traceable and debuggable

---



## 🏗️ High-Level Architecture

```
1. Client API Call (Generate)
      │
      ▼
SessionState Graph (LangGraph)
      │
      ├─► Load Transcripts (cached)
      │
      ├─► Extract Context & Facts (cached)
      │
      ├─► Sync Sections from DB (human edits)
      │
      ▼
  - Generate_section
      │
      ▼
Persist Section + Update SessionState
                                          
---

2. Client API Call (Refine)
      │
      ▼
Load Existing SessionState (no mutation)
      │
      ▼
  -refine_section
      │
      ▼
Overwrite Section Content 
---

```


---
---

## 📦 Repository Structure
```

InternalAgent/                         # MAIN REPOSITORY
│
├── src/
│   ├── core/
│   │   ├── graph/                     # LangGraph orchestration layer
│   │   │   ├── Session_graph.py       # Graph construction / wiring             
│   │   └── nodes/
│   │   │   │   ├── transcript_loader_node.py
│   │   │   │   ├── context_extractor_node.py
│   │   │   │   ├── section_sync_node.py
│   │   │   │   └── hydrate_from_config.py    
│   │   │
│   │   ├                    
│   │   ├── generate_section.py         # Business logic (LLM-facing)
│   │   └── refine_section.py
│   │   │
│   │   ├── tools/                     # Low-level reusable utilities
│   │   │   ├── llm_client.py           # generate_text / generate_json
│   │   │   ├── chunk.py                # text chunking logic
│   │   │   ├── transcript_extractor.py # pdf/audio/doc → text
│   │   │   └── supabase_db.py          # DB / file IO helpers (if used)
│   │   │
│   │   ├── schemas/                   # Pydantic contracts
│   │   │   ├── fact_schema.py
│   │   │   └── state_schema.py
│   │   │
│   │   └── state.py                   # SessionState, FileRef, SectionRef
│   │
│   └── api/
│       ├── main.py                    # FastAPI entrypoint
│       └── constants.py               # headers, status enums, error codes
│
├── .temp/                             # Ephemeral working state (gitignored)
│   ├── transcripts/
│   ├── context/
│   └── sections/
│
├── trial_graph.py                     # Local LangGraph runner / debugging
├── README.md                          # Architecture + usage
├── pyproject.toml
├── requirements.txt
└── .gitignore

```

## 🔄 Execution Flow

### 1️⃣ Build Session Graph (Every GENERATE Call)
A fresh LangGraph session graph is created for every API generate call to ensure:
- no stale state
- latest DB edits are respected
- idempotent behavior

LangGraph is used **only for orchestration**, not for writing sections.

---


#### 1.1  Load Transcripts (Once per Session)

- Files fetched from storage / DB
- Transcripts extracted and cached locally
- - Transcripts are treated as **immutable within a single session**


---

#### 1.2 Context & Fact Extraction (Once per Session)

- Transcripts are chunked
- Atomic facts extracted with evidence
- Facts stored as JSON on disk
- SessionState stores only file references

---

#### 1.3 Sync Sections from DB (Every Generate Call)

- Query DB for sections belonging to `(customer_id, opportunity_id, report_type)`
- Compare DB timestamps with cached metadata
- Fetch **only modified sections**
- Cache locally and update `SessionState.completed_sections`

DB is the **source of truth**.

---

### 2️⃣ Section Generation (Every Generate Call)

`generate_section`:
- consumes prepared SessionState
- reads extracted facts
- applies section intent
- writes text section to disk
- updates `completed_sections`

---

### 3️⃣ Section Refinement (Every Refine Call)

`refine_section`:
- treats original section as authoritative
- follows user instruction strictly
- uses facts only if requested


Refinement never regenerates.

---


