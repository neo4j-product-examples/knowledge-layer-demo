"""Fetches and shapes the `ontology` constituent: a small meta-graph
describing how the composite database's real constituents fit together --
what each one holds (down to its real schema entities), how it's backed,
and how the constituents connect. This powers the "View Ontology" panel,
which is a separate, static architecture reveal -- unlike the shadow/
decision graph the chat tools build up, it isn't part of the tool-call loop
and doesn't change during a session.

Two node kinds come back, both in one flat list so the frontend can render
them in a single graph:
- "hub": one per real composite constituent (DataProduct)
- "entity": the real schema entities/labels that constituent's data
  actually contains (SchemaEntity), colored the same as their hub so a
  branch reads as one visual family.
"""


def fetch_ontology_graph(session):
    product_rows = [
        dict(row) for row in session.run(
            """
            USE meridianComposite.ontology
            MATCH (p:DataProduct)
            RETURN p.productId AS id, p.name AS label, p.shortCode AS shortCode,
                   p.backend AS backend, p.description AS description, p.color AS color
            ORDER BY p.productId
            """
        )
    ]
    color_by_product = {row["id"]: row["color"] for row in product_rows}

    entity_rows = [
        dict(row) for row in session.run(
            """
            USE meridianComposite.ontology
            MATCH (e:SchemaEntity)
            RETURN e.entityId AS id, e.productId AS productId, e.name AS label,
                   e.description AS description
            ORDER BY e.productId, e.entityId
            """
        )
    ]

    hub_edges = [
        {"from": row["fromId"], "to": row["toId"], "label": row["label"], "description": row["description"], "kind": "hub"}
        for row in (
            dict(row) for row in session.run(
                """
                USE meridianComposite.ontology
                MATCH (a:DataProduct)-[r]->(b:DataProduct)
                RETURN a.productId AS fromId, b.productId AS toId, type(r) AS label, r.description AS description
                """
            )
        )
    ]
    membership_edges = [
        {"from": row["fromId"], "to": row["toId"], "label": "HAS_ENTITY", "description": None, "kind": "membership"}
        for row in (
            dict(row) for row in session.run(
                """
                USE meridianComposite.ontology
                MATCH (p:DataProduct)-[:HAS_ENTITY]->(e:SchemaEntity)
                RETURN p.productId AS fromId, e.entityId AS toId
                """
            )
        )
    ]
    entity_edges = [
        {"from": row["fromId"], "to": row["toId"], "label": row["label"], "description": row["description"], "kind": "entity"}
        for row in (
            dict(row) for row in session.run(
                """
                USE meridianComposite.ontology
                MATCH (a:SchemaEntity)-[r:RELATES]->(b:SchemaEntity)
                RETURN a.entityId AS fromId, b.entityId AS toId, r.label AS label, r.description AS description
                """
            )
        )
    ]

    nodes = [
        {**row, "kind": "hub", "color": row["color"]} for row in product_rows
    ] + [
        {**row, "kind": "entity", "color": color_by_product.get(row["productId"], "#948A72"), "backend": None}
        for row in entity_rows
    ]

    return {"nodes": nodes, "edges": hub_edges + membership_edges + entity_edges}
