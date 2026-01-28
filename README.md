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


---

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


