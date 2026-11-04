"""Shadow node + SIMILAR_TO edge creation in shadowDb.

shadowDb holds a lightweight copy of every node that takes part in a
cross-constituent link -- just enough to identify it (sourceGraph +
sourceId, pointing back to where the full record actually lives) plus a
display name -- and the SIMILAR_TO edges between those copies, which is
the only place such a link can physically exist (composite databases
forbid relationships that span constituents, and meridian is read-only).
Any other fact about a node (its accounts, its employer, its loan
request, ...) stays in that node's own source graph and is read live from
there when needed, not pre-copied in here.

All writes are MERGE-based on (sourceGraph, sourceId) so seeding and
re-running the pipeline is always idempotent (requirements §5).
"""

MATCH_REL_TYPE = "SIMILAR_TO"

_MERGE_SHADOW_NODE = """
USE meridianComposite.shadowDb
MERGE (n:Shadow:{label} {{sourceGraph: $sourceGraph, sourceId: $sourceId}})
SET n += $properties
RETURN n
"""

_MERGE_SIMILAR_TO = """
USE meridianComposite.shadowDb
MATCH (m:Shadow {sourceGraph: 'meridian', sourceId: $meridianId})
MATCH (d:Shadow {sourceGraph: 'documents', sourceId: $documentsId})
MERGE (m)-[r:SIMILAR_TO]-(d)
SET r.matchType = $matchType, r.confidence = $confidence, r.matchedOn = $matchedOn
RETURN r
"""

_MERGE_SHADOW_NODES_BATCH = """
USE meridianComposite.shadowDb
UNWIND $rows AS row
MERGE (n:Shadow:{label} {{sourceGraph: $sourceGraph, sourceId: row.sourceId}})
SET n += row.properties
"""

_MERGE_SIMILAR_TO_BATCH = """
USE meridianComposite.shadowDb
UNWIND $rows AS row
MATCH (m:Shadow {sourceGraph: 'meridian', sourceId: row.meridianId})
MATCH (d:Shadow {sourceGraph: 'documents', sourceId: row.documentsId})
MERGE (m)-[r:SIMILAR_TO]-(d)
SET r.matchType = row.matchType, r.confidence = row.confidence, r.matchedOn = row.matchedOn
"""

_COUNT_MERIDIAN_SHADOW_NODES = """
USE meridianComposite.shadowDb
MATCH (n:Shadow {sourceGraph: 'meridian'})
RETURN count(n) AS count
"""

_DELETE_DOCUMENT_SHADOW_NODES = """
USE meridianComposite.shadowDb
MATCH (n:Shadow {sourceGraph: 'documents'})
DETACH DELETE n
"""


def clear_document_shadow_data(session):
    """Wipes all documents-side shadow nodes (and their SIMILAR_TO edges).
    Run on every app load so a document's shadow data only exists between
    an Upload Document click and the next page refresh."""
    session.run(_DELETE_DOCUMENT_SHADOW_NODES)


def meridian_shadow_nodes_exist(session):
    result = session.run(_COUNT_MERIDIAN_SHADOW_NODES)
    record = result.single()
    return record is not None and record["count"] > 0


def _merge_shadow_node(session, label, source_graph, source_id, properties):
    query = _MERGE_SHADOW_NODE.format(label=label)
    session.run(
        query,
        sourceGraph=source_graph,
        sourceId=source_id,
        properties=properties,
    )


def _merge_shadow_nodes_batch(session, label, source_graph, rows):
    """rows: [{'sourceId': ..., 'properties': {...}}, ...]. One round trip
    for the whole batch instead of one per row -- with the composite
    database two network hops away, a per-row loop over dozens/hundreds of
    rows is the difference between a fast page load and a 20+ second one."""
    if not rows:
        return
    query = _MERGE_SHADOW_NODES_BATCH.format(label=label)
    session.run(query, sourceGraph=source_graph, rows=rows)


def seed_meridian_customers(session, customers):
    rows = [
        {"sourceId": c["customerId"], "properties": {"name": c.get("customerName")}}
        for c in customers
        if c.get("customerId") is not None
    ]
    _merge_shadow_nodes_batch(session, "Customer", "meridian", rows)


def seed_meridian_shadow_nodes(session, customers):
    """Idempotent: safe to call on every app startup.

    Only Customer is shadowed -- meridian's Account entities were shadowed
    too at one point, but documents never actually has Account nodes in
    this demo's data, so account matching never produced anything; see the
    shadowdb-simplification commits."""
    seed_meridian_customers(session, customers)


def create_document_shadow_node(session, label, source_id, properties):
    _merge_shadow_node(
        session,
        label=label,
        source_graph="documents",
        source_id=source_id,
        properties=properties,
    )


def seed_document_shadow_nodes(session, persons, organizations, loan_requests=None):
    """Shadows every Person/Organization/LoanRequest node from the documents
    graph, run when a document is uploaded (not on startup) -- identity
    only (just a display name), never the fuller record that stays in the
    documents graph itself.

    Account and Property were shadowed here too at one point, but this
    demo's documents data never actually has Account/Property nodes, so
    those were always empty; see the shadowdb-simplification commits."""
    person_rows = [
        {"sourceId": p["__id__"], "properties": {"name": p.get("name")}}
        for p in persons if p.get("__id__") is not None
    ]
    _merge_shadow_nodes_batch(session, "Person", "documents", person_rows)

    org_rows = [
        {"sourceId": o["__id__"], "properties": {"name": o.get("name")}}
        for o in organizations if o.get("__id__") is not None
    ]
    _merge_shadow_nodes_batch(session, "Organization", "documents", org_rows)

    loan_request_rows = [
        {
            "sourceId": lr["__id__"],
            "properties": {
                "name": (
                    f"${lr['requestedAmount']:,.0f} {lr.get('termYears')}-yr "
                    f"{lr.get('rateType') or ''} Loan Request"
                ).replace("  ", " ") if lr.get("requestedAmount") is not None else "Loan Request",
            },
        }
        for lr in (loan_requests or []) if lr.get("__id__") is not None
    ]
    _merge_shadow_nodes_batch(session, "LoanRequest", "documents", loan_request_rows)


def create_similar_to(session, match):
    """`match` is a dict as produced by resolver.matching (meridian_id,
    documents_id, matchType, confidence, matchedOn)."""
    session.run(
        _MERGE_SIMILAR_TO,
        meridianId=match["meridian_id"],
        documentsId=match["documents_id"],
        matchType=match["matchType"],
        confidence=match["confidence"],
        matchedOn=match["matchedOn"],
    )


def create_similar_to_batch(session, matches):
    """One round trip for the whole batch (see _merge_shadow_nodes_batch for
    why that matters)."""
    if not matches:
        return
    rows = [
        {
            "meridianId": m["meridian_id"], "documentsId": m["documents_id"],
            "matchType": m["matchType"], "confidence": m["confidence"], "matchedOn": m["matchedOn"],
        }
        for m in matches
    ]
    session.run(_MERGE_SIMILAR_TO_BATCH, rows=rows)


def apply_document_matches(session, matches, documents_label, documents_lookup):
    """Creates the documents-side shadow node for each match (looked up via
    documents_lookup, keyed by documents_id) and the SIMILAR_TO edge.

    documents_lookup: dict mapping documents_id -> raw property dict.
    """
    node_rows = [
        {"sourceId": m["documents_id"], "properties": {"name": documents_lookup.get(m["documents_id"], {}).get("name")}}
        for m in matches
    ]
    _merge_shadow_nodes_batch(session, documents_label, "documents", node_rows)
    create_similar_to_batch(session, matches)
