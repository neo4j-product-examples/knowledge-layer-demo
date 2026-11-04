# Entity Resolution App — Requirements

## 1. Overview

A Flask web app that resolves entities between two Neo4j graphs — `meridian`
(structured banking data, exposed as a read-only Aura Virtual Graph) and
`documents` (a document-intelligence knowledge graph built from unstructured
documents) — using a Neo4j composite database (`meridianComposite`) as the
query layer.

Composite database constituents (already provisioned):

- `meridianComposite.meridian` → Aura Virtual Graph, **read-only**
- `meridianComposite.documents` → Aura standard DB, read/write
- `meridianComposite.shadowDb` → Aura standard DB, read/write, dedicated to
  resolution output (shadow nodes, `SIMILAR_TO` edges)

## 2. Why a shadow-node pattern

Composite/Fabric databases route queries across constituents but forbid
native relationships that span two constituents. `meridian` is also
read-only (Virtual Graph does not support `CREATE`/`MERGE`/`SET`). So:

- Nothing can ever be written into `meridian`.
- Cross-graph relationships must be materialized as copies ("shadow nodes")
  in a single physical database — `shadowDb` — connected by `SIMILAR_TO`
  edges, so WCC can run over one connected graph.

## 3. Entity types in scope

| Source | Label | Key identifying properties |
|---|---|---|
| meridian | `Customer` | `customerId`, `customerName`, `ein`, `customerType` |
| documents | `Person` | `customerID`, `name` |
| documents | `Organization` | `name` |

`meridian.Account`/`documents.Account` (exact-id account matching) and
`documents.Property` were in scope at one point, but this demo's
`documents` data never actually has `Account`/`Property` nodes, so that
matching rule and those shadow copies never produced anything — removed
rather than kept as permanently-dead capability.

## 4. Matching rules (per entity-type pair)

### 4.1 Customer ↔ Person
- **Priority 1 (exact):** `meridian.Customer.customerId` ==
  `documents.Person.customerID`, when the `documents.Person` node has a
  non-null `customerID`.
- **Priority 2 (fuzzy fallback):** normalized name similarity between
  `meridian.Customer.customerName` and `documents.Person.name` (lowercase,
  strip punctuation/whitespace) using token-set similarity, only applied
  when `customerType` indicates an individual. Match if similarity ≥ 0.85.

### 4.2 Customer ↔ Organization
- **Signal (fuzzy only — no shared key exists in the schema):** normalized
  name similarity between `meridian.Customer.customerName` and
  `documents.Organization.name`, applied when `customerType` indicates a
  business. Normalize by lowercasing and stripping common legal suffixes
  (`inc`, `llc`, `corp`, `co`, `ltd`, punctuation). Match if similarity ≥
  0.85.

### 4.3 Confidence labeling
Every `SIMILAR_TO` edge must carry:
- `matchType`: `"customer_exact"` | `"name_fuzzy"`
- `confidence`: float 0–1 (1.0 for exact matches, similarity score for
  fuzzy matches)
- `matchedOn`: the property name(s) used

## 5. Shadow node model (written to `shadowDb`)

Nothing is pre-seeded. A `:Shadow` node exists only as the endpoint of a
real `SIMILAR_TO` match -- matching always runs against data fetched fresh
from `meridian`/`documents` (never from a pre-existing shadow copy), and
only once a match is accepted does either side get written to `shadowDb`:

1. For the matched `meridian.Customer`, `MERGE` a shadow node in
   `shadowDb` labeled `:Shadow:Customer`, with `sourceGraph: "meridian"`,
   `sourceId` set to `customerId`, and just enough to display it (`name`)
   -- not a copy of the full record, which stays in `meridian` and is read
   live when needed (see §2).
2. For the matched `documents` node, `MERGE` a shadow node in `shadowDb`:
   `:Shadow:<OriginalLabel>` with `sourceGraph: "documents"` and `sourceId`
   set to the original key, same identity-only shape.
3. Connect the two with `SIMILAR_TO` (properties per §4.3).
4. Idempotency requirement: re-running the pipeline on the same source
   data must not create duplicate shadow nodes or edges (`MERGE` on
   `(sourceGraph, sourceId)` for nodes, and on the node pair for edges).
5. An entity that never matches anything is never shadowed at all -- the
   initial "documents-only" canvas view, and anywhere else an unmatched
   entity needs to be shown, is built from a live read of its own source
   graph instead (see `graph_data.build_documents_graph`).
6. On every page load, any `:Shadow` node left with no `SIMILAR_TO` edge
   (a match from a previous demo run) is deleted, so state never carries
   from one run into the next.

## 6. Web app behavior (MVP)

1. **On page load**, the backend clears any `:Shadow` node orphaned by a
   previous run (§5.6) -- it never writes shadow nodes itself. The canvas
   starts empty; nothing is shown until a document is uploaded.
2. The same page has an **Upload Document** button. The document is
   already present on disk for this MVP — the button just triggers the
   rest of the pipeline (no real upload UI needed yet).
3. Finding a match (today, the `find_customer` chat tool) runs, in order:
   a. Candidate matching queries (§4) between `documents` and `meridian`,
      fetched live, not against any pre-existing shadow copy.
   b. For each accepted match, shadow node + `SIMILAR_TO` creation in
      `shadowDb` (§5).
4. The page then re-renders the embedded graph view so the user can
   visually inspect which entities were resolved as the same.
5. Errors at any stage (e.g. composite database unreachable) must surface
   a clear message in the UI, not a stack trace.

## 7. Testing strategy (TDD)

- All matching and shadow-node logic must be unit-testable without a
  live Neo4j connection — the Neo4j driver/session is injected and mocked
  in tests.
- Test coverage required before implementation is considered done:
  - Name normalization and similarity scoring (pure functions).
  - Match-candidate query construction for each of the three entity-type
    pairs.
  - Shadow node/edge Cypher generation and idempotency (`MERGE` semantics).
- A small number of integration tests may run against the real composite
  database, gated behind an environment flag, not run by default in CI.

## 8. Out of scope (for this MVP)
- Real file upload / document ingestion pipeline.
- Authentication.
- Editing/correcting matches from the UI.
- Automated re-runs / scheduling.
