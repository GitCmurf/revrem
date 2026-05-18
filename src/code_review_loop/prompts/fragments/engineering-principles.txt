# Engineering Principles

*(GitCmurf v1.1 -- 2026/03/05 revision)*

**Audience:** Human contributors and AI coding assistants (Codex,
Claude, Gemini, etc.)\
**Scope:** Universal engineering standards. Repository‑specific rules
live in `AGENTS.md`.\
If a rule conflicts with `AGENTS.md`, the repository rule takes
precedence.

These principles exist to keep the system **correct, testable,
maintainable, and understandable** as it evolves.

------------------------------------------------------------------------

## 1. Atomic Unit of Work

A change is **not complete** unless it includes all three:

  Required        Meaning
  --------------- ---------------------------------------------------
  Code            Implementation
  Tests           Automated proof behaviour works and stays working
  Documentation   Updated comments / docs reflecting the change

Partial deliveries create drift and are not acceptable.

------------------------------------------------------------------------

## 2. Architecture & Design

-   **Separation of concerns:** API/transport, business logic, and data
    access must be isolated.
-   **Single responsibility:** Modules should have one clear purpose.
    Large mixed‑utility files are a smell.
-   **KISS:** Prefer the simplest solution that meets requirements.
-   **DRY (pragmatic):** Extract shared logic when duplication becomes
    meaningful.
-   **SOLID (lightweight):** Prefer small interfaces and dependency
    injection over inheritance hierarchies.
-   **Backwards compatibility:** Public APIs and CLI interfaces must not
    change without migration paths.
-   **Data modelling:** Schemas are expensive to change. Define
    constraints at the schema level where possible.

------------------------------------------------------------------------

## 3. Code Quality

-   **Write for the reader.** Code is read far more often than written.
-   **Naming:** Prefer clarity over brevity (`retry_count` not `rc`).
-   **Function size:** Aim for ≤ 40 lines.
-   **Type safety:** Use strict typing (`tsc --strict`, Python type
    hints).
-   **Comments explain *why*, not *what*.**
-   **Formatting:** Follow project linters/formatters.

------------------------------------------------------------------------

## 4. Heuristics and Rule Sets

Rule‑based systems (stopword lists, regex banks, token filters, prompt
templates, etc.) must be treated as first‑class artifacts.

To prevent uncontrolled growth:

-   Lists larger than \~50 items require documented provenance or
    rationale.
-   Lists larger than \~200 items must live in dedicated resource files,
    not inline code.
-   Every rule set must have a clear owner.
-   Heuristic changes must include tests or benchmarks demonstrating
    improvement.
-   AI assistants must **not auto‑generate large lexical lists** without
    explicit approval.

If a heuristic cannot be justified with tests or metrics, it should not
be introduced.

------------------------------------------------------------------------

## 5. Testing

-   Prefer **test‑first development** (red → green → refactor).
-   Follow the **test pyramid**: unit \> integration \> E2E.
-   Tests must be **deterministic** (no wall clock, network, or
    randomness).
-   Each test verifies **one behaviour**.
-   Test names should read as specifications.
-   Prefer **fixture‑based tests** for complex transformations (parsers,
    NLP pipelines).
-   Pipelines must produce identical outputs for identical inputs.

Coverage matters less than testing the correct behaviours.

------------------------------------------------------------------------

## 6. Error Handling & Reliability

-   **Design failure‑first:** consider failure modes before writing the
    happy path.
-   **Fail explicitly:** never silently swallow exceptions.
-   **Error messages must include context.**
-   **Validate external inputs at boundaries.**
-   **Idempotency:** operations should be safe to retry.
-   **Retries:** use exponential backoff with jitter.
-   **Graceful degradation:** optional components failing should not
    break the core pipeline.
-   **Structured logging:** use levels (`debug`, `info`, `warn`,
    `error`) and avoid logging secrets.

------------------------------------------------------------------------

## 7. Security

-   No hardcoded secrets.
-   Sanitize all external inputs.
-   Use least‑privilege permissions.
-   Evaluate dependency health before adoption.

------------------------------------------------------------------------

## 8. Dependencies

-   Prefer well‑maintained libraries.
-   Pin dependency versions using lockfiles.
-   Commit lockfiles to ensure reproducible builds.
-   Minimize dependency surface area.

------------------------------------------------------------------------

## 9. Performance & Concurrency

-   Measure before optimizing.
-   Avoid premature concurrency.
-   Protect shared state when concurrency is necessary.
-   Be cautious of **O(n²)** algorithms in text or corpus processing
    pipelines.
-   Processes must start quickly and shut down cleanly.

------------------------------------------------------------------------

## 10. Version Control Discipline

-   **Atomic commits:** one logical change per commit.
-   **Descriptive messages:** imperative mood.
-   Do not commit build outputs or caches.
-   Develop on feature branches and merge via reviewed PRs.

------------------------------------------------------------------------

## 11. AI‑Generated Code

AI‑generated code is **untrusted draft output**.

Before merging:

-   Verify APIs and libraries actually exist.
-   Ensure architecture aligns with project design.
-   Confirm tests and documentation are included.
-   Reject autogenerated artifacts (large word lists, regex banks, etc.)
    unless justified.

AI systems are useful for scaffolding but must not introduce
architectural changes silently.

------------------------------------------------------------------------

## 12. Working With Existing Code

-   **Read before writing.**
-   Understand intent by reading tests and history.
-   Make the **smallest change that solves the problem**.
-   Preserve behaviour when refactoring.
-   If tests do not exist, write them before modifying behaviour.

------------------------------------------------------------------------

## 13. When in Doubt

-   Ask for clarification rather than guessing.
-   Prefer conservative, well‑understood solutions.
-   Leave the codebase slightly better than you found it.

------------------------------------------------------------------------

*This document is intentionally concise so it can be safely injected
into AI context windows.\
If a rule proves consistently incorrect, propose a revision rather than
ignoring it.*
