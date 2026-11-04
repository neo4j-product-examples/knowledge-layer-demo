"""Shadow node + SIMILAR_TO edge creation in shadowDb.

A :Shadow node exists only when it is the endpoint of a real SIMILAR_TO
match -- nothing is pre-seeded. Matching itself always runs against live
data fetched fresh from meridian/documents (see resolver.matching); only
once a match is accepted do both endpoints get MERGE'd here -- just enough
to identify them (sourceGraph + sourceId + a display name) -- along with
the SIMILAR_TO edge between them, which is the only place such a
cross-constituent link can physically exist (composite databases forbid
relationships that span constituents, and meridian is read-only). Any
other fact about a node (its accounts, its employer, its loan request,
...) stays in that node's own source graph and is read live from there
when needed, never copied in here -- and an entity that never matches
anything is simply never shadowed at all.

All writes are MERGE-based on (sourceGraph, sourceId) so re-running is
always idempotent (requirements §5).
"""

MATCH_REL_TYPE = "SIMILAR_TO"
# Every match's meridian side is a Customer -- meridian Account matching
# was removed (documents never actually has Account nodes in this demo's
# data), so this is the only label a meridian-side shadow node ever needs.
MERIDIAN_MATCH_LABEL = "Customer"

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

_CLEAR_ORPHANED_SHADOW_NODES = """
USE meridianComposite.shadowDb
MATCH (n:Shadow)
WHERE NOT (n)-[:SIMILAR_TO]-()
DETACH DELETE n
"""


def clear_orphaned_shadow_nodes(session):
    """Deletes any :Shadow node left with no SIMILAR_TO edge. Run on every
    app load so a match from a previous demo run never carries into the
    next one. Under this match-time-only model a :Shadow node should only
    ever exist as a match endpoint -- an orphan here just means "leftover
    from a prior run," not something a bug created mid-session."""
    session.run(_CLEAR_ORPHANED_SHADOW_NODES)


def _merge_shadow_nodes_batch(session, label, source_graph, rows):
    """rows: [{'sourceId': ..., 'properties': {...}}, ...]. One round trip
    for the whole batch instead of one per row -- with the composite
    database two network hops away, a per-row loop over dozens/hundreds of
    rows is the difference between a fast page load and a 20+ second one."""
    if not rows:
        return
    query = _MERGE_SHADOW_NODES_BATCH.format(label=label)
    session.run(query, sourceGraph=source_graph, rows=rows)


def create_similar_to_batch(session, matches):
    """One round trip for the whole batch (see _merge_shadow_nodes_batch
    for why that matters). Both endpoints must already exist --
    apply_document_matches MERGEs them first."""
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


def apply_document_matches(session, matches, documents_label, documents_lookup, meridian_lookup):
    """For each accepted match, MERGEs both the meridian-side and
    documents-side shadow nodes -- the only two nodes ever shadowed for
    this match -- plus the SIMILAR_TO edge between them. An entity that
    doesn't match anything is never shadowed at all.

    documents_lookup: dict mapping documents_id -> raw property dict (for name).
    meridian_lookup: dict mapping meridian_id -> raw meridian.Customer dict.
    """
    if not matches:
        return
    meridian_rows = [
        {
            "sourceId": m["meridian_id"],
            "properties": {"name": meridian_lookup.get(m["meridian_id"], {}).get("customerName")},
        }
        for m in matches
    ]
    _merge_shadow_nodes_batch(session, MERIDIAN_MATCH_LABEL, "meridian", meridian_rows)

    document_rows = [
        {"sourceId": m["documents_id"], "properties": {"name": documents_lookup.get(m["documents_id"], {}).get("name")}}
        for m in matches
    ]
    _merge_shadow_nodes_batch(session, documents_label, "documents", document_rows)

    create_similar_to_batch(session, matches)
