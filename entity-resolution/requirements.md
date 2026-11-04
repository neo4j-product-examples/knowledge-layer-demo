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

### 5.1 Nordtell seeding (run once, outside the app, independent of any document)
Run via `scripts/seed_shadowdb.py` by hand -- once, or whenever meridian's
customer/account list changes -- never from the Flask app itself:
- For every `meridian.Customer` and `meridian.Account`, `MERGE` a shadow
  node in `shadowDb` labeled `:Shadow:<OriginalLabel>`, with
  `sourceGraph: "meridian"`, `sourceId` set to the original key
  (`customerId` / `accountId`), and just enough to display it (`name`) --
  not a copy of the full record, which stays in `meridian` and is read
  live when needed (see §2).
- `MERGE` on `(sourceGraph, sourceId)` so this is idempotent — safe to
  re-run without creating duplicates.
- The app (`index()`) only ever reads this seeding's result (a check that
  it exists, surfacing an error if not) -- it never writes these nodes
  itself. A page load that could seed on the fly was exactly how stale
  data kept reappearing: any old copy of the app pointed at the same
  shared database would silently re-derive and re-write it on every
  request.

### 5.2 Document-side shadow nodes + linking (triggered by Upload Document)
For every match found between `documents` and the existing Nordtell shadow
nodes (§4):
1. `MERGE` a shadow node in `shadowDb` for the matching `documents` node:
   `:Shadow:<OriginalLabel>` with `sourceGraph: "documents"` and `sourceId`
   set to the original key, copying identifying properties.
2. Connect it to the existing Nordtell shadow node (from §5.1) with
   `SIMILAR_TO` (properties per §4.4).
3. Idempotency requirement: re-running the pipeline on the same source data
   must not create duplicate shadow nodes or edges (`MERGE` on
   `(sourceGraph, sourceId)` for nodes, and on the node pair for edges).

## 6. Web app behavior (MVP)

1. **On page load**, the backend only checks that the Nordtell seeding
   step (§5.1) has already been run (read-only -- it never runs that
   seeding itself) and surfaces an error if not, then queries `shadowDb`
   and renders whatever Nordtell shadow nodes already exist as the
   initial graph view — the user sees these immediately, with no button
   click required.
2. The same page has an **Upload Document** button. The document is
   already present on disk for this MVP — the button just triggers the
   rest of the pipeline (no real upload UI needed yet).
3. On click, the backend runs, in order:
   a. Candidate matching queries (§4) between `documents` and the existing
      Nordtell shadow nodes, via the composite database.
   b. Document-side shadow node + `SIMILAR_TO` creation in `shadowDb`
      (§5.2).
4. The page then re-renders the embedded graph view (shadow nodes,
   `SIMILAR_TO` edges shown) so the user can visually inspect which
   entities were resolved as the same.
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
