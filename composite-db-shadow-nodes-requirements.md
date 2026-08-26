# Requirements: Composite Database with Shadow Nodes for Cross-Graph Entity Resolution

## Background

Two separate Neo4j graphs currently exist:

- **Knowledge graph** (`neo4j-documents` connection) — built from a business plan, containing `Person`, `Organization`, `Account`, `Property`, and `__Entity__` nodes, plus document/chunk provenance nodes from the source text.
- **Banking virtual graph** (`meridian-virtual-graph` connection) — a virtualized graph over banking data (backed by Snowflake). Schema could not be pulled live during this session due to an auth error (`JWT token is invalid`) — this needs to be resolved before build starts.

Goal, per Stegi's suggestion: stand up a **composite database** in Neo4j that holds **shadow nodes** — lightweight copies of the identity-bearing nodes from both source graphs — so we can run graph algorithms (entity resolution / similarity) to determine whether people in the business-plan knowledge graph are the same people as those in the banking graph.

## Objective

Enable graph algorithms (node similarity, entity resolution) to run across both graphs by:
1. Creating a composite (federated) database in Neo4j that can query both source graphs.
2. Populating a shadow layer — copies of key entity nodes (primarily `Person`) with shared/normalized identity properties — into a working database where GDS algorithms can run natively (GDS does not run directly over federated/virtual queries).
3. Linking matched shadow nodes back to their source-graph originals so results are traceable.

## Requirements

### 1. Connectivity & Access
- Resolve the `meridian-virtual-graph` auth failure (JWT invalid) before any schema/data pull.
- Confirm both source DBs are reachable from the same Neo4j instance/cluster that will host the composite database (composite databases require the constituent databases to be in the same DBMS or reachable via Fabric).
- Confirm read credentials are sufficient to pull node data for shadowing (no write access to source graphs required).

### 2. Composite Database Setup
- Create a composite database definition pointing at the two constituent databases (knowledge graph DB, banking DB).
- Verify `USE` clauses / composite queries can reach both graphs from a single Cypher session.
- Document the composite DB name and connection details for future use.

### 3. Shadow Node Layer
- Create a new physical database (or a dedicated set of labels within an existing writable DB) to hold shadow nodes, since GDS projections need a concrete database, not a virtual/composite one.
- For each source `Person`-type node, create a shadow node with:
  - `sourceGraph` (e.g., `"knowledge_graph"` or `"banking_graph"`)
  - `sourceId` (the originating node's `__id__` / `customerID` / `guid`, whichever applies)
  - Normalized identity fields: `name`, `customerID` (where present), and any other resolvable attributes (email, employer, account numbers) once the banking schema is confirmed.
- Add a `SHADOWS` relationship from each shadow node back to its source node (or store source reference as a property if cross-database relationships aren't supported).
- Define a refresh/sync process (manual re-run vs. scheduled) to keep shadow nodes current as source graphs change.

### 4. Entity Resolution / Matching Logic
- Decide the matching strategy: exact key match (e.g., `customerID`), fuzzy name matching, or GDS similarity algorithms (Node Similarity, kNN, or Entity Resolution via node embeddings).
- Define which properties count as matching signals (name, employer/organization, address, account numbers) once the banking graph schema is available — need to confirm overlapping fields exist (`Person.name`/`customerID` in the knowledge graph vs. `User.guid` and related fields in the banking graph, assuming `meridian-virtual-graph` is the banking source).
- Set a similarity/confidence threshold for what counts as "likely the same person."
- Write matched pairs back as a relationship (e.g., `POSSIBLY_SAME_AS {score: float}`) between shadow nodes.

### 5. Algorithms to Support
- Node Similarity (GDS) for attribute-based matching.
- Optionally, community detection or path-finding across the merged shadow graph to explore relationships between the business-plan entities and banking entities once matches are found.

### 6. Validation
- Spot-check a sample of matched pairs manually against source data.
- Produce a small report/summary of match counts and confidence distribution before treating results as reliable.

## Open Questions
- Is `meridian-virtual-graph` definitely the intended "banking virtual graph," or is `neo4j-fabric-fraud` (User/Card/Device/IP schema) the intended target? Fraud graph has no direct name/person-identity fields today (only `guid`), which would make matching harder.
- What identity fields actually exist in the banking graph once the connection is fixed?
- Where should the shadow/composite database physically live — same Aura instance, same on-prem cluster, or a new sandbox?

## Next Steps
1. Fix `meridian-virtual-graph` auth and pull its schema.
2. Confirm with Corydon/Stegi which banking graph is the real target (virtual graph vs. fraud graph).
3. Build the composite database definition.
4. Build the shadow node ETL (Cypher scripts or a small pipeline).
5. Run first-pass matching and validate.
