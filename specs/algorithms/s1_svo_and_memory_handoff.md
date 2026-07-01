# System-1 Algorithm Note: SVO and Memory Handoff

## Status

The current S1 implementation includes a deterministic, clearly labeled SVO **heuristic** so the base package has no heavyweight NLP dependency. It is not equivalent to dependency parsing.

A stronger upstream NLP adapter may provide dependency-parsed triples, named entities, and coreference-resolved text through the S1 input/context contract. System-1 preserves those structures as evidence-bearing context rather than claiming to derive them itself.

## Baseline SVO heuristic

```text
for each sentence:
  identify configured action verbs
  select nearest non-stopword before verb as subject candidate
  select nearest non-stopword after verb as object candidate
  emit {subject, verb, object, method: "heuristic"}
```

The heuristic is useful for transparent fallback behavior and tests. It must not be used as a high-confidence factual parser in domains requiring full linguistic accuracy.

## Preferred enriched path

```text
S3 or external NLP adapter
  → sentence segmentation
  → dependency parsing
  → named-entity recognition
  → optional coreference resolution
  → triples/entities with source provenance
  → S1 cognitive map
```

## Memory handoff contract

Before mapping, S1 may call bounded `memory.recall(query, limit=3)` and attach the returned evidence packet. After mapping, S1 emits a `memory_write_candidate`; it does not write inferred claims automatically.

A separate persistence path must verify governance, authority, evidence, and lifecycle before adding an artifact or checkpoint to the Semantic Memory Lake.
