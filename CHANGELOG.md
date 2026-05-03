# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-05-03

### Added

#### Mastra-Backed Tools (8)

- **mastra_recall** — Retrieve stored memories for the active profile using Mastra's memory provider.
- **mastra_search** — Keyword-based search across profile-isolated memory entries.
- **mastra_semantic_search** — Vector / semantic search over embedded memory content via Mastra.
- **mastra_observe** — Trigger an observation cycle that feeds into the Observer/Reflector pipeline.
- **mastra_working_memory** — Read and write short-lived working-memory slots scoped to the current session.
- **mastra_artifact_get** — Fetch a named artifact (identity file, prompt block, etc.) by ID.
- **mastra_artifact_history** — Retrieve the full version history of a stored artifact.
- **mastra_artifact_revert** — Revert an artifact to a prior version from its history.

#### Per-Profile Isolation

- All memory, artifact, and working-memory data is isolated per profile using **libSQL** as the backing store.
- Each profile receives its own namespace, preventing cross-profile data leakage.

#### Observer / Reflector Agent Roles

- **Observer** role watches agent interactions and extracts salient facts, decisions, and context into memory.
- **Reflector** role periodically reviews accumulated observations, consolidating and pruning memory to maintain relevance.

#### Non-Blocking Hook Contract

- Hooks execute under a strict **5-second deadline**.
- Hook results are returned asynchronously so the host agent loop is never blocked by a slow provider.

#### Capacity-Aware System Prompt Hints

- When stored memory or artifact volume exceeds **50%** of the configured capacity, the system automatically injects hints into the agent's system prompt encouraging consolidation or archival.

#### Versioned Identity-File Storage

- Identity files are stored as versioned **Mastra prompt-blocks**, enabling deterministic retrieval of any prior version and safe atomic updates.

#### Optional Mastra-Aware ContextEngine Wrapper

- A drop-in `ContextEngine` wrapper is provided that transparently routes memory operations through Mastra when the plugin is installed, while falling back to the built-in engine otherwise.

#### Bun Server

- Production-ready Bun server exposing **17 routes** for tool invocations, health checks, profile management, artifact CRUD, and memory queries.

#### Code-Size Policy Enforcement

- Automated policy checks reject PRs or builds that exceed the configured code-size budget, keeping the plugin lightweight.

#### Test Suite

- **425+ tests** covering tool contracts, isolation boundaries, hook deadlines, capacity hints, artifact versioning, server routes, and the ContextEngine wrapper.

[0.1.0]: https://github.com/nousresearch/hermes-mastra/releases/tag/v0.1.0
