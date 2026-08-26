"""Shapes the shadowDb graph into vis-network-friendly JSON for the UI."""
from resolver.shadow_nodes import ALL_REL_TYPES, MATCH_REL_TYPE

_REL_TYPE_PATTERN = "|".join(ALL_REL_TYPES)

_FETCH_NODES = """
USE meridianComposite.shadowDb
MATCH (n:Shadow)
RETURN n.sourceGraph AS sourceGraph, n.sourceId AS sourceId, labels(n) AS labels,
       n.componentId AS componentId, n.customerName AS customerName, n.name AS name
"""

# Directed MATCH (not `-[r]-`) so `from`/`to` reflect the relationship's real
# stored direction instead of being reconstructed by guesswork.
_FETCH_EDGES = f"""
USE meridianComposite.shadowDb
MATCH (a:Shadow)-[r:{_REL_TYPE_PATTERN}]->(b:Shadow)
RETURN a.sourceGraph AS fromSourceGraph, a.sourceId AS fromSourceId,
       b.sourceGraph AS toSourceGraph, b.sourceId AS toSourceId,
       type(r) AS relType, r.confidence AS confidence, r.matchType AS matchType
"""

_GROUP_COLORS = {"meridian": "#4C8BF5", "documents": "#F59E4C"}


def _node_id(source_graph, source_id):
    return f"{source_graph}:{source_id}"


def _display_label(row):
    entity_label = next((l for l in row["labels"] if l != "Shadow"), "Node")
    name = row.get("customerName") or row.get("name") or row["sourceId"]
    return f"{entity_label}: {name}"


def build_vis_graph(node_rows, edge_rows):
    nodes = {}
    for row in node_rows:
        nid = _node_id(row["sourceGraph"], row["sourceId"])
        nodes[nid] = {
            "id": nid,
            "label": _display_label(row),
            "group": row["sourceGraph"],
            "color": _GROUP_COLORS.get(row["sourceGraph"], "#999999"),
            "componentId": row.get("componentId"),
        }

    edges = []
    for row in edge_rows:
        rel_type = row["relType"]
        is_match = rel_type == MATCH_REL_TYPE
        edges.append({
            "from": _node_id(row["fromSourceGraph"], row["fromSourceId"]),
            "to": _node_id(row["toSourceGraph"], row["toSourceId"]),
            "label": row.get("matchType") or rel_type,
            "title": f"confidence: {row.get('confidence')}" if is_match else rel_type,
            "dashes": is_match,
        })

    return {"nodes": list(nodes.values()), "edges": edges}


def fetch_graph_json(session):
    node_rows = [dict(r) for r in session.run(_FETCH_NODES)]
    edge_rows = [dict(r) for r in session.run(_FETCH_EDGES)]
    return build_vis_graph(node_rows, edge_rows)
