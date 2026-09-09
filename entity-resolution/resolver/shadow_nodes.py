"""Shadow node + SIMILAR_TO edge creation in shadowDb.

All writes are MERGE-based on (sourceGraph, sourceId) so seeding and
re-running the pipeline is always idempotent (requirements §5).
"""

MATCH_REL_TYPE = "SIMILAR_TO"
STRUCTURAL_REL_TYPES = ["OWNS_ACCOUNT", "WORKED_AT", "AUTHORIZED_FOR", "CO_OWNS", "OWNS", "HAS_PARENT", "REQUESTS"]
ALL_REL_TYPES = [MATCH_REL_TYPE] + STRUCTURAL_REL_TYPES

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

_MERGE_SHADOW_RELATIONSHIP = """
USE meridianComposite.shadowDb
MATCH (a:Shadow {{sourceGraph: $fromSourceGraph, sourceId: $fromSourceId}})
MATCH (b:Shadow {{sourceGraph: $toSourceGraph, sourceId: $toSourceId}})
MERGE (a)-[r:{rel_type}]->(b)
SET r += $properties
RETURN r
"""

_MERGE_SHADOW_NODES_BATCH = """
USE meridianComposite.shadowDb
UNWIND $rows AS row
MERGE (n:Shadow:{label} {{sourceGraph: $sourceGraph, sourceId: row.sourceId}})
SET n += row.properties
"""

_MERGE_SHADOW_RELATIONSHIPS_BATCH = """
USE meridianComposite.shadowDb
UNWIND $rows AS row
MATCH (a:Shadow {{sourceGraph: row.fromSourceGraph, sourceId: row.fromSourceId}})
MATCH (b:Shadow {{sourceGraph: row.toSourceGraph, sourceId: row.toSourceId}})
MERGE (a)-[r:{rel_type}]->(b)
SET r += row.properties
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
    """Wipes all documents-side shadow nodes (and their relationships,
    structural and SIMILAR_TO alike). Run on every app load so a document's
    shadow data only exists between an Upload Document click and the next
    page refresh."""
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
        {
            "sourceId": c["customerId"],
            "properties": {"customerName": c.get("customerName"), "customerType": c.get("customerType")},
        }
        for c in customers
        if c.get("customerId") is not None
    ]
    _merge_shadow_nodes_batch(session, "Customer", "meridian", rows)


def seed_meridian_accounts(session, accounts):
    rows = [
        {"sourceId": a["accountId"], "properties": {}}
        for a in accounts
        if a.get("accountId") is not None
    ]
    _merge_shadow_nodes_batch(session, "Account", "meridian", rows)


def seed_meridian_shadow_nodes(session, customers, accounts):
    """Idempotent: safe to call on every app startup."""
    seed_meridian_customers(session, customers)
    seed_meridian_accounts(session, accounts)


def create_shadow_relationship(
    session, rel_type, from_source_graph, from_source_id, to_source_graph, to_source_id, properties=None
):
    """MERGEs a directed relationship between two already-shadowed nodes,
    identified by (sourceGraph, sourceId). Both nodes must already exist."""
    query = _MERGE_SHADOW_RELATIONSHIP.format(rel_type=rel_type)
    session.run(
        query,
        fromSourceGraph=from_source_graph,
        fromSourceId=from_source_id,
        toSourceGraph=to_source_graph,
        toSourceId=to_source_id,
        properties=properties or {},
    )


def create_shadow_relationships_batch(session, rel_type, rows):
    """rows: [{'fromSourceGraph', 'fromSourceId', 'toSourceGraph', 'toSourceId',
    'properties'}, ...]. One round trip for the whole batch (see
    _merge_shadow_nodes_batch for why that matters)."""
    if not rows:
        return
    query = _MERGE_SHADOW_RELATIONSHIPS_BATCH.format(rel_type=rel_type)
    session.run(query, rows=rows)


def seed_meridian_account_ownership(session, ownership_edges):
    """Shadows Customer-[:OWNS_ACCOUNT]->Account edges from the meridian
    graph between the already-shadowed Customer/Account shadow nodes."""
    rows = [
        {
            "fromSourceGraph": "meridian", "fromSourceId": e["customerId"],
            "toSourceGraph": "meridian", "toSourceId": e["accountId"],
            "properties": {},
        }
        for e in ownership_edges
        if e.get("customerId") is not None and e.get("accountId") is not None
    ]
    create_shadow_relationships_batch(session, "OWNS_ACCOUNT", rows)


def seed_meridian_customer_hierarchy(session, hierarchy_edges):
    """Shadows Customer-[:HAS_PARENT]->Customer edges (corporate ownership
    hierarchy) so WCC can surface customers connected only through a shared
    ultimate parent several hops up, which a shallow join would miss."""
    rows = [
        {
            "fromSourceGraph": "meridian", "fromSourceId": e["customerId"],
            "toSourceGraph": "meridian", "toSourceId": e["parentCustomerId"],
            "properties": {},
        }
        for e in hierarchy_edges
        if e.get("customerId") is not None and e.get("parentCustomerId") is not None
    ]
    create_shadow_relationships_batch(session, "HAS_PARENT", rows)


def create_document_shadow_node(session, label, source_id, properties):
    _merge_shadow_node(
        session,
        label=label,
        source_graph="documents",
        source_id=source_id,
        properties=properties,
    )


def seed_document_shadow_nodes(session, persons, organizations, accounts, properties, loan_requests=None):
    """Shadows every Person/Organization/Account/Property/LoanRequest node
    from the documents graph, run when a document is uploaded (not on
    startup)."""
    person_rows = [
        {"sourceId": p["__id__"], "properties": {"customerID": p.get("customerID"), "name": p.get("name")}}
        for p in persons if p.get("__id__") is not None
    ]
    _merge_shadow_nodes_batch(session, "Person", "documents", person_rows)

    org_rows = [
        {"sourceId": o["__id__"], "properties": {"name": o.get("name")}}
        for o in organizations if o.get("__id__") is not None
    ]
    _merge_shadow_nodes_batch(session, "Organization", "documents", org_rows)

    account_rows = [
        {"sourceId": a["__id__"], "properties": {"accountID": a.get("accountID"), "accountNumber": a.get("accountNumber")}}
        for a in accounts if a.get("__id__") is not None
    ]
    _merge_shadow_nodes_batch(session, "Account", "documents", account_rows)

    property_rows = [
        {"sourceId": pr["__id__"], "properties": {"name": pr.get("name")}}
        for pr in properties if pr.get("__id__") is not None
    ]
    _merge_shadow_nodes_batch(session, "Property", "documents", property_rows)

    loan_request_rows = [
        {
            "sourceId": lr["__id__"],
            "properties": {
                "name": (
                    f"${lr['requestedAmount']:,.0f} {lr.get('termYears')}-yr "
                    f"{lr.get('rateType') or ''} Loan Request"
                ).replace("  ", " ") if lr.get("requestedAmount") is not None else "Loan Request",
                "requestedAmount": lr.get("requestedAmount"),
                "termYears": lr.get("termYears"),
                "rateType": lr.get("rateType"),
                "applicationId": lr.get("applicationId"),
                "purpose": lr.get("purpose"),
            },
        }
        for lr in (loan_requests or []) if lr.get("__id__") is not None
    ]
    _merge_shadow_nodes_batch(session, "LoanRequest", "documents", loan_request_rows)


def seed_document_relationships(session, worked_at_edges, authorized_for_edges, co_owns_edges, ownership_edges=None, requests_edges=None):
    """Shadows the documents graph's own Person->Organization/Account/Property
    relationships between the already-shadowed documents nodes."""
    worked_at_rows = [
        {
            "fromSourceGraph": "documents", "fromSourceId": e["personId"],
            "toSourceGraph": "documents", "toSourceId": e["organizationId"],
            "properties": {},
        }
        for e in worked_at_edges if e.get("personId") is not None and e.get("organizationId") is not None
    ]
    create_shadow_relationships_batch(session, "WORKED_AT", worked_at_rows)

    authorized_for_rows = [
        {
            "fromSourceGraph": "documents", "fromSourceId": e["personId"],
            "toSourceGraph": "documents", "toSourceId": e["accountId"],
            "properties": {},
        }
        for e in authorized_for_edges if e.get("personId") is not None and e.get("accountId") is not None
    ]
    create_shadow_relationships_batch(session, "AUTHORIZED_FOR", authorized_for_rows)

    co_owns_rows = [
        {
            "fromSourceGraph": "documents", "fromSourceId": e["personId"],
            "toSourceGraph": "documents", "toSourceId": e["propertyId"],
            "properties": {},
        }
        for e in co_owns_edges if e.get("personId") is not None and e.get("propertyId") is not None
    ]
    create_shadow_relationships_batch(session, "CO_OWNS", co_owns_rows)

    ownership_rows = [
        {
            "fromSourceGraph": "documents", "fromSourceId": e["personId"],
            "toSourceGraph": "documents", "toSourceId": e["organizationId"],
            "properties": {"pct": e.get("pct"), "role": e.get("role")},
        }
        for e in (ownership_edges or []) if e.get("personId") is not None and e.get("organizationId") is not None
    ]
    create_shadow_relationships_batch(session, "OWNS", ownership_rows)

    requests_rows = [
        {
            "fromSourceGraph": "documents", "fromSourceId": e["organizationId"],
            "toSourceGraph": "documents", "toSourceId": e["__id__"],
            "properties": {},
        }
        for e in (requests_edges or []) if e.get("organizationId") is not None and e.get("__id__") is not None
    ]
    create_shadow_relationships_batch(session, "REQUESTS", requests_rows)


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
        {"sourceId": m["documents_id"], "properties": documents_lookup.get(m["documents_id"], {})}
        for m in matches
    ]
    _merge_shadow_nodes_batch(session, documents_label, "documents", node_rows)
    create_similar_to_batch(session, matches)
