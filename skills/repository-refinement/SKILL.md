---
name: repository-refinement
description: Convert retrieved evidence and project context into source-closed repository specs, code, tests, diagrams, schemas, and traceable change sets.
---

# Repository Refinement

Use this skill when the task requires more than retrieving or summarizing information: the retrieved material must be transformed into durable repository artifacts.

## Boundaries

- Treat System-OS Systems as selected analytical functions, not proof of hidden or continuous runtime modules.
- Treat PseuLang and QeuLang as declarative specifications unless an interpreter, compiler, backend, and tests are present.
- Do not claim that code ran, tests passed, memory changed, or a repository was patched without tool evidence.
- Do not write credentials, tokens, private keys, service-account JSON, or local environment paths into the repository.
- Repository mutation requires an explicit write capability and a reviewable branch or change set.

## Workflow

1. **Resolve scope.** Identify target repository, branch, objective, constraints, requested artifacts, and validation standard.
2. **Retrieve narrowly.** Gather the smallest sufficient source set from the conversation, library, repository, connectors, and authoritative public documentation.
3. **Create source records.** Preserve source ID, URI, revision, fragment, timestamp, digest, and evidence state.
4. **Map the task.** Extract entities, claims, dependencies, constraints, ambiguity, implementation anchors, and open questions.
5. **Assign an ensemble.** Choose the smallest sufficient functions and assign `LEAD`, `SUPPORT`, `FRAME`, `COUNTERPOINT`, `MONITOR`, `GUARD`, or `UNDERSTUDY` roles.
6. **Refine artifacts.** Produce complete specs, source code, tests, schemas, diagrams, skills, or configuration. Keep each artifact focused and link related files with relative paths.
7. **Validate source closure.** Every material claim and artifact must trace to the bound source set. Check version, branch, implementation target, and test binding.
8. **Validate evidence state.** Distinguish declared, specified, interpreted, observed, tool-supported, runtime-enforced, and counterfactually validated outputs.
9. **Apply governance.** Check permissions, privacy, security, user purpose, path safety, reversibility, and blast radius.
10. **Emit a change set.** Write only approved artifacts to a non-default branch, run relevant checks, and produce a trace receipt.

## Artifact design rules

- Use Markdown for explanations and navigation.
- Use Mermaid in Markdown for architecture, sequence, state, dependency, and data-flow diagrams.
- Use Python for executable behavior with type hints, explicit errors, and tests.
- Use JSON Schema for structural validation; keep lengthy rationale in Markdown.
- Use PseuLang/QeuLang for domain contracts that lower to a shared intermediate representation.
- Keep `SKILL.md` self-contained, focused, actionable, and example-driven.

## Evidence-state gate

- `STRUCTURALLY_SPECIFIED` requires a concrete artifact or contract.
- `TOOL_SUPPORTED` requires a cited tool result.
- `RUNTIME_ENFORCED` requires a validator or test receipt.
- `COUNTERFACTUALLY_VALIDATED` requires a controlled comparison showing the claimed dependency.

When evidence is insufficient, lower the label rather than strengthen the prose.

## Output contract

Return or write:

- source inventory and provenance map;
- context/task map;
- proposed artifact paths;
- complete artifact content;
- validation report;
- tests or validators used;
- trace receipt;
- unresolved risks or candidate-only adaptations.
