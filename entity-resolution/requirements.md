# Entity Resolution App — Requirements

## 1. Overview

A Flask web app that resolves entities between two Neo4j graphs — `meridian`
(structured banking data, exposed as a read-only Aura Virtual Graph) and
`documents` (a document-intelligence knowledge graph built from unstructured
documents) — using a Neo4j composite database (`meridianComposite`) as the
query layer, and Weakly Connected Components (WCC) as the resolution
algorithm.

Composite database constituents (already provisioned):

- `meridianComposite.meridian` → Aura Virtual Graph, **read-only**
- `meridianComposite.documents` → Aura standard DB, read/write
- `meridianComposite.shadowDb` → Aura standard DB, read/write, dedicated to
  resolution output (shadow nodes, `SIMILAR_TO` edges, WCC results)

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
| meridian | `Account` | `accountId` |
| documents | `Person` | `customerID`, `name` |
| documents | `Organization` | `name` |
| documents | `Account` | `accountID`, `accountNumber` |

## 4. Matching rules (per entity-type pair)

### 4.1 Account ↔ Account
- **Signal:** exact match, case-insensitive, on normalized identifier
  (strip whitespace/dashes/leading zeros).
- Compare `meridian.Account.accountId` against `documents.Account.accountID`
  **or** `documents.Account.accountNumber`.
- This is the highest-confidence match type — treat as ground truth.

### 4.2 Customer ↔ Person
- **Priority 1 (exact):** `meridian.Customer.customerId` ==
  `documents.Person.customerID`, when the `documents.Person` node has a
  non-null `customerID`.
- **Priority 2 (fuzzy fallback):** normalized name similarity between
  `meridian.Customer.customerName` and `documents.Person.name` (lowercase,
  strip punctuation/whitespace) using token-set similarity, only applied
  when `customerType` indicates an individual. Match if similarity ≥ 0.85.

### 4.3 Customer ↔ Organization
- **Signal (fuzzy only — no shared key exists in the schema):** normalized
  name similarity between `meridian.Customer.customerName` and
  `documents.Organization.name`, applied when `customerType` indicates a
  business. Normalize by lowercasing and stripping common legal suffixes
  (`inc`, `llc`, `corp`, `co`, `ltd`, punctuation). Match if similarity ≥
  0.85.

### 4.4 Confidence labeling
Every `SIMILAR_TO` edge must carry:
- `matchType`: `"account_exact"` | `"customer_exact"` | `"name_fuzzy"`
- `confidence`: float 0–1 (1.0 for exact matches, similarity score for
  fuzzy matches)
- `matchedOn`: the property name(s) used

## 5. Shadow node model (written to `shadowDb`)

### 5.1 Meridian seeding (happens first, independent of any document)
On app startup, if `shadowDb` does not yet contain shadow nodes for the
`meridian` constituent, create them:
- For every `meridian.Customer` and `meridian.Account`, `MERGE` a shadow
  node in `shadowDb` labeled `:Shadow:<OriginalLabel>`, with
  `sourceGraph: "meridian"` and `sourceId` set to the original key
  (`customerId` / `accountId`), copying the other identifying properties.
- `MERGE` on `(sourceGraph, sourceId)` so this is idempotent — safe to run
  on every startup without creating duplicates or re-seeding if already
  present.
- This seeding step does not depend on any document being uploaded — it
  reflects the operational banking system as it exists in `meridian`.

### 5.2 Document-side shadow nodes + linking (triggered by Upload Document)
For every match found between `documents` and the existing Meridian shadow
nodes (§4):
1. `MERGE` a shadow node in `shadowDb` for the matching `documents` node:
   `:Shadow:<OriginalLabel>` with `sourceGraph: "documents"` and `sourceId`
   set to the original key, copying identifying properties.
2. Connect it to the existing Meridian shadow node (from §5.1) with
   `SIMILAR_TO` (properties per §4.4).
3. Idempotency requirement: re-running the pipeline on the same source data
   must not create duplicate shadow nodes or edges (`MERGE` on
   `(sourceGraph, sourceId)` for nodes, and on the node pair for edges).

## 6. Weakly Connected Components step

- After shadow nodes + `SIMILAR_TO` edges exist in `shadowDb`, run WCC
  over that graph (Neo4j GDS `gds.wcc` if the GDS plugin is available on
  that Aura instance; otherwise a pure-Cypher fallback implementation).
- Write the resulting `componentId` back onto each shadow node.
- Two shadow nodes in the same component are considered **the same
  real-world entity** across `meridian` and `documents`.

## 7. Web app behavior (MVP)

1. **On startup**, the backend runs the Meridian seeding step (§5.1) if
   needed. **On page load**, the app queries `shadowDb` and renders
   whatever Meridian shadow nodes already exist as the initial graph view
   — the user sees these immediately, with no button click required.
2. The same page has an **Upload Document** button. The document is
   already present on disk for this MVP — the button just triggers the
   rest of the pipeline (no real upload UI needed yet).
3. On click, the backend runs, in order:
   a. Candidate matching queries (§4) between `documents` and the existing
      Meridian shadow nodes, via the composite database.
   b. Document-side shadow node + `SIMILAR_TO` creation in `shadowDb`
      (§5.2).
   c. WCC over `shadowDb` (§6).
4. The page then re-renders the embedded graph view (shadow nodes colored
   by `componentId`, `SIMILAR_TO` edges shown) so the user can visually
   inspect which entities were resolved as the same.
5. Errors at any stage (e.g. composite database unreachable) must surface
   a clear message in the UI, not a stack trace.

## 8. Testing strategy (TDD)

- All matching, shadow-node, and WCC logic must be unit-testable without a
  live Neo4j connection — the Neo4j driver/session is injected and mocked
  in tests.
- Test coverage required before implementation is considered done:
  - Name normalization and similarity scoring (pure functions).
  - Match-candidate query construction for each of the three entity-type
    pairs.
  - Shadow node/edge Cypher generation and idempotency (`MERGE` semantics).
  - WCC result parsing and component assignment.
- A small number of integration tests may run against the real composite
  database, gated behind an environment flag, not run by default in CI.

## 9. Out of scope (for this MVP)
- Real file upload / document ingestion pipeline.
- Authentication.
- Editing/correcting matches from the UI.
- Automated re-runs / scheduling.
