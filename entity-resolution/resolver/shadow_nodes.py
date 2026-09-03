"""Shadow node + SIMILAR_TO edge creation in shadowDb.

All writes are MERGE-based on (sourceGraph, sourceId) so seeding and
re-running the pipeline is always idempotent (requirements §5).
"""

MATCH_REL_TYPE = "SIMILAR_TO"
STRUCTURAL_REL_TYPES = ["OWNS_ACCOUNT", "WORKED_AT", "AUTHORIZED_FOR", "CO_OWNS", "OWNS", "HAS_PARENT"]
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


def seed_meridian_customers(session, customers):
    for c in customers:
        source_id = c.get("customerId")
        if source_id is None:
            continue
        _merge_shadow_node(
            session,
            label="Customer",
            source_graph="meridian",
            source_id=source_id,
            properties={
                "customerName": c.get("customerName"),
                "customerType": c.get("customerType"),
            },
        )


def seed_meridian_accounts(session, accounts):
    for a in accounts:
        source_id = a.get("accountId")
        if source_id is None:
            continue
        _merge_shadow_node(
            session,
            label="Account",
            source_graph="meridian",
            source_id=source_id,
            properties={},
        )


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


def seed_meridian_account_ownership(session, ownership_edges):
    """Shadows Customer-[:OWNS_ACCOUNT]->Account edges from the meridian
    graph between the already-shadowed Customer/Account shadow nodes."""
    for edge in ownership_edges:
        customer_id = edge.get("customerId")
        account_id = edge.get("accountId")
        if customer_id is None or account_id is None:
            continue
        create_shadow_relationship(session, "OWNS_ACCOUNT", "meridian", customer_id, "meridian", account_id)


def seed_meridian_customer_hierarchy(session, hierarchy_edges):
    """Shadows Customer-[:HAS_PARENT]->Customer edges (corporate ownership
    hierarchy) so WCC can surface customers connected only through a shared
    ultimate parent several hops up, which a shallow join would miss."""
    for edge in hierarchy_edges:
        customer_id = edge.get("customerId")
        parent_customer_id = edge.get("parentCustomerId")
        if customer_id is None or parent_customer_id is None:
            continue
        create_shadow_relationship(session, "HAS_PARENT", "meridian", customer_id, "meridian", parent_customer_id)


def create_document_shadow_node(session, label, source_id, properties):
    _merge_shadow_node(
        session,
        label=label,
        source_graph="documents",
        source_id=source_id,
        properties=properties,
    )


def seed_document_shadow_nodes(session, persons, organizations, accounts, properties):
    """Shadows every Person/Organization/Account/Property node from the
    documents graph, run when a document is uploaded (not on startup)."""
    for p in persons:
        source_id = p.get("__id__")
        if source_id is None:
            continue
        create_document_shadow_node(session, "Person", source_id, {
            "customerID": p.get("customerID"),
            "name": p.get("name"),
        })
    for o in organizations:
        source_id = o.get("__id__")
        if source_id is None:
            continue
        create_document_shadow_node(session, "Organization", source_id, {"name": o.get("name")})
    for a in accounts:
        source_id = a.get("__id__")
        if source_id is None:
            continue
        create_document_shadow_node(session, "Account", source_id, {
            "accountID": a.get("accountID"),
            "accountNumber": a.get("accountNumber"),
        })
    for pr in properties:
        source_id = pr.get("__id__")
        if source_id is None:
            continue
        create_document_shadow_node(session, "Property", source_id, {"name": pr.get("name")})


def seed_document_relationships(session, worked_at_edges, authorized_for_edges, co_owns_edges, ownership_edges=None):
    """Shadows the documents graph's own Person->Organization/Account/Property
    relationships between the already-shadowed documents nodes."""
    for edge in worked_at_edges:
        person_id, org_id = edge.get("personId"), edge.get("organizationId")
        if person_id is None or org_id is None:
            continue
        create_shadow_relationship(session, "WORKED_AT", "documents", person_id, "documents", org_id)
    for edge in authorized_for_edges:
        person_id, account_id = edge.get("personId"), edge.get("accountId")
        if person_id is None or account_id is None:
            continue
        create_shadow_relationship(session, "AUTHORIZED_FOR", "documents", person_id, "documents", account_id)
    for edge in co_owns_edges:
        person_id, property_id = edge.get("personId"), edge.get("propertyId")
        if person_id is None or property_id is None:
            continue
        create_shadow_relationship(session, "CO_OWNS", "documents", person_id, "documents", property_id)
    for edge in (ownership_edges or []):
        person_id, org_id = edge.get("personId"), edge.get("organizationId")
        if person_id is None or org_id is None:
            continue
        create_shadow_relationship(
            session, "OWNS", "documents", person_id, "documents", org_id,
            properties={"pct": edge.get("pct"), "role": edge.get("role")},
        )


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


def apply_document_matches(session, matches, documents_label, documents_lookup):
    """For each match, create the documents-side shadow node (looked up via
    documents_lookup, keyed by documents_id) and the SIMILAR_TO edge.

    documents_lookup: dict mapping documents_id -> raw property dict.
    """
    for match in matches:
        doc_id = match["documents_id"]
        properties = documents_lookup.get(doc_id, {})
        create_document_shadow_node(session, documents_label, doc_id, properties)
        create_similar_to(session, match)
