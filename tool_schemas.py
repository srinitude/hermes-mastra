"""JSON-Schema definitions for the three tools the provider exposes."""

from __future__ import annotations

RECALL_SCHEMA = {
    "name": "mastra_recall",
    "description": (
        "Pull the dense observation log for the CURRENT session from Mastra "
        "Observational Memory. Returns a compressed summary of facts the "
        "Observer + Reflector have distilled so far for THIS thread.\n\n"
        "Use this when you need more detail than the system-prompt block "
        "already gives you. For keyword search across ALL past observations, "
        "use `mastra_search`. For raw conversation transcripts from past "
        "sessions, use `session_search` — Mastra's distilled observations "
        "are complementary to session_search's raw recall."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max observations to return (default 8, max 32).",
            },
        },
        "required": [],
    },
}

OBSERVE_SCHEMA = {
    "name": "mastra_observe",
    "description": (
        "Persist a manual observation to the active Mastra thread. The "
        "Observer ingests it on its next pass.\n\n"
        "When to use which durable-memory surface:\n"
        "  - Built-in `memory` tool → MEMORY.md / USER.md — small (≤2200/1375 "
        "chars), critical, frozen into the system prompt at session start.\n"
        "  - `mastra_observe` (this tool) → Mastra — unlimited size, "
        "session-specific or larger durable facts, surfaces via mastra_recall "
        "and mastra_search on subsequent turns/sessions.\n\n"
        "Use sparingly for facts you want guaranteed (corrections, decisions, "
        "preferences). The Observer/Reflector handle routine summarization "
        "automatically — only call this when you'd otherwise add to MEMORY.md "
        "but the content is too big or session-specific."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The observation to store."},
            "kind": {
                "type": "string",
                "description": ("Optional tag (e.g. 'preference', 'decision', 'correction')."),
            },
        },
        "required": ["text"],
    },
}

SEARCH_SCHEMA = {
    "name": "mastra_search",
    "description": (
        "Keyword search across stored Mastra Observational Memory observations "
        "for the current profile. Parallel API to `session_search` — but where "
        "session_search returns LLM-summarized PAST CONVERSATION transcripts, "
        "this returns the DISTILLED OBSERVATIONS the Observer has compressed "
        "from those sessions.\n\n"
        "When to use which:\n"
        "  - `mastra_recall` — current thread's observation log (no query)\n"
        "  - `mastra_search` — keyword search across observations from ANY past thread\n"
        "  - `mastra_semantic_search` — vector search by MEANING across observations\n"
        "  - `session_search` — full-text search of raw past-session transcripts\n\n"
        "Each result includes the originating threadId so you can correlate "
        "Mastra hits with session_search hits."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keyword query (substring match across observations).",
            },
            "limit": {
                "type": "integer",
                "description": "Max observations to return (default 8, max 20).",
            },
        },
        "required": ["query"],
    },
}


SEMANTIC_SEARCH_SCHEMA = {
    "name": "mastra_semantic_search",
    "description": (
        "Semantic / vector search across observations using meaning rather than "
        "keywords. Use this when keyword `mastra_search` would miss "
        "synonyms / paraphrases / conceptually-similar phrases.\n\n"
        "Costs more than `mastra_search` (vector query + re-rank), so the "
        "agent calls this deliberately when keyword fails. Returns the same "
        "shape as `mastra_search` plus a relevance `score` per hit. "
        "Falls back to no results if the server's vector store is not "
        "configured."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language query — searched by meaning.",
            },
            "limit": {
                "type": "integer",
                "description": "Max observations to return (default 8, max 20).",
            },
        },
        "required": ["query"],
    },
}


WORKING_MEMORY_GET_SCHEMA = {
    "name": "mastra_working_memory",
    "description": (
        "Read the working-memory mirror that Mastra keeps in sync with "
        "the built-in MEMORY.md / USER.md edits. The built-in `memory` tool "
        "is the AUTHORITATIVE store for durable facts; this read is for "
        "inspecting what was mirrored, not for routine recall — prefer "
        "the system-prompt MEMORY.md / USER.md blocks for that.\n\n"
        "Use this when you suspect the mirror diverged or want to see "
        "the resource-scoped working-memory document Mastra has built up."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


# ----- artifact tools (SOUL.md / MEMORY.md / USER.md / AGENTS.md as
#       versioned Mastra prompt-blocks; see HERMES_INTEGRATION_MAP §2.6) ----


_ARTIFACT_KIND_DESC = (
    "Artifact kind. One of:\n"
    "  - `soul` — SOUL.md (agent identity, layer 1 of system prompt)\n"
    "  - `memory` — MEMORY.md (durable agent memory, layer 5)\n"
    "  - `user` — USER.md (user profile, layer 6)\n"
    "  - `agents` — AGENTS.md (project-scoped context files)"
)


ARTIFACT_GET_SCHEMA = {
    "name": "mastra_artifact_get",
    "description": (
        "Return the latest version of a Hermes artifact (SOUL.md, MEMORY.md, "
        "USER.md, or a per-project AGENTS.md snapshot) from the Mastra "
        "prompt-blocks store. The on-disk file is the *cache*; this tool "
        "reads the canonical version Mastra holds.\n\n"
        "Use to verify the file cache matches the database, or when the "
        "agent wants the very latest version after another process edited "
        "the mirror."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": _ARTIFACT_KIND_DESC},
        },
        "required": ["kind"],
    },
}


ARTIFACT_HISTORY_SCHEMA = {
    "name": "mastra_artifact_history",
    "description": (
        "List version history (newest first) for a Hermes artifact. Each "
        "version includes its content, change_message, and timestamp.\n\n"
        "Use to audit changes, diff revisions, or pick a version to revert "
        "to via `mastra_artifact_revert`."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": _ARTIFACT_KIND_DESC},
            "limit": {"type": "integer", "description": "Max versions (default 20, max 50)."},
        },
        "required": ["kind"],
    },
}


ARTIFACT_REVERT_SCHEMA = {
    "name": "mastra_artifact_revert",
    "description": (
        "Restore the content of a prior version of a Hermes artifact by "
        "appending a NEW version with that content (history is preserved — "
        "no rewinds).\n\n"
        "The on-disk file cache is refreshed atomically right after."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": _ARTIFACT_KIND_DESC},
            "version": {
                "type": "integer",
                "description": "Version number to restore (must exist in history).",
            },
        },
        "required": ["kind", "version"],
    },
}
