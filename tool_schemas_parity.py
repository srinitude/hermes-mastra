"""Parity tool schemas — covers profile / synthesize / browse / add-fact.

Each schema mirrors a bundled-provider surface (honcho_profile,
honcho_dialectic, viking_browse, mem0_conclude / retaindb_remember)
so the agent has a single Mastra-named tool for each role.
"""

from __future__ import annotations

PROFILE_SCHEMA = {
    "name": "mastra_profile",
    "description": (
        "Return a peer-card style profile recall over the active "
        "Mastra working memory and stored observations. Equivalent to "
        "honcho_profile / retaindb_profile / supermemory profile — pulls "
        "the durable identity / preference layer for the current "
        "agent_identity@hermes_home resource."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max observations to fold into the profile (default 8, max 32).",
            },
        },
        "required": [],
    },
}


SYNTHESIZE_SCHEMA = {
    "name": "mastra_synthesize",
    "description": (
        "LLM-reasoned synthesis over the top recall hits for a query. "
        "Equivalent to honcho_dialectic / hindsight_synthesize — calls the "
        "Reflector model with the retrieved observation set and a "
        "structured prompt to produce a single coherent answer."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language question to synthesise from observations.",
            },
            "limit": {
                "type": "integer",
                "description": "Max observations to feed the Reflector (default 8, max 20).",
            },
        },
        "required": ["query"],
    },
}


BROWSE_SCHEMA = {
    "name": "mastra_browse",
    "description": (
        "Filesystem-style browse over the artifact tree (SOUL.md, "
        "MEMORY.md, USER.md, AGENTS.md, agent-scoped artifacts). "
        "Equivalent to viking_browse — list available artifact kinds and "
        "the latest version metadata for each."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prefix": {
                "type": "string",
                "description": "Optional artifact-kind prefix filter (e.g. 'soul', 'agents/').",
            },
        },
        "required": [],
    },
}


ADD_FACT_SCHEMA = {
    "name": "mastra_add_fact",
    "description": (
        "Explicit user-facing fact write to Mastra working memory. "
        "Equivalent to mem0_conclude / retaindb_remember / viking_remember "
        "/ brv_curate — pins a single durable fact under the active "
        "resource id without going through the Observer extraction loop."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "Single durable fact to persist (concise, declarative).",
            },
            "kind": {
                "type": "string",
                "description": "Optional tag (e.g. 'preference', 'decision', 'correction').",
            },
        },
        "required": ["fact"],
    },
}
