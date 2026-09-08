"""Shapes the shadowDb graph into vis-network-friendly JSON for the UI."""
from resolver.shadow_nodes import ALL_REL_TYPES, MATCH_REL_TYPE

_REL_TYPE_PATTERN = "|".join(ALL_REL_TYPES)

_FETCH_NODES = """
USE meridianComposite.shadowDb
MATCH (n:Shadow)
RETURN n.sourceGraph AS sourceGraph, n.sourceId AS sourceId, labels(n) AS labels,
       n.componentId AS componentId, n.customerName AS customerName, n.name AS name
"""

_FETCH_DOCUMENTS_NODES = """
USE meridianComposite.shadowDb
MATCH (n:Shadow {sourceGraph: 'documents'})
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

_FETCH_DOCUMENTS_EDGES = f"""
USE meridianComposite.shadowDb
MATCH (a:Shadow {{sourceGraph: 'documents'}})-[r:{_REL_TYPE_PATTERN}]->(b:Shadow {{sourceGraph: 'documents'}})
RETURN a.sourceGraph AS fromSourceGraph, a.sourceId AS fromSourceId,
       b.sourceGraph AS toSourceGraph, b.sourceId AS toSourceId,
       type(r) AS relType, r.confidence AS confidence, r.matchType AS matchType
"""

_FETCH_HIERARCHY_NEIGHBORHOOD = """
USE meridianComposite.shadowDb
MATCH (start:Shadow:Customer {{sourceGraph: 'meridian', sourceId: $customerId}})
MATCH (start)-[:HAS_PARENT*1..{max_hops}]-(other:Shadow:Customer)
RETURN DISTINCT other.sourceId AS sourceId, other.customerName AS customerName
"""

_FETCH_HIERARCHY_EDGES = """
USE meridianComposite.shadowDb
MATCH (a:Shadow:Customer)-[:HAS_PARENT]->(b:Shadow:Customer)
WHERE a.sourceId IN $ids AND b.sourceId IN $ids
RETURN a.sourceId AS fromId, b.sourceId AS toId
"""

_GROUP_COLORS = {"meridian": "#4C8BF5", "documents": "#F59E4C"}
_RISK_COLOR = "#E5484D"


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


def build_match_delta(matches, meridian_customer_by_id, meridian_account_by_id):
    """Graph delta revealing the meridian side of each match (the documents
    side is assumed already on the canvas from the documents-only view)."""
    nodes = {}
    edges = []
    for m in matches:
        meridian_id = m["meridian_id"]
        nid = _node_id("meridian", meridian_id)
        if meridian_id in meridian_customer_by_id:
            label = f"Customer: {meridian_customer_by_id[meridian_id].get('customerName')}"
        elif meridian_id in meridian_account_by_id:
            label = f"Account: {meridian_id}"
        else:
            label = meridian_id
        nodes[nid] = {
            "id": nid,
            "label": label,
            "group": "meridian",
            "color": _GROUP_COLORS["meridian"],
            "componentId": None,
        }
        edges.append({
            "from": nid,
            "to": _node_id("documents", m["documents_id"]),
            "label": m["matchType"],
            "title": f"confidence: {m['confidence']}",
            "dashes": True,
        })
    return {"nodes": list(nodes.values()), "edges": edges}


def build_hierarchy_delta(hierarchy_rows, edge_rows, risk_customer_ids=None):
    """Graph delta revealing the corporate-hierarchy neighborhood of an
    already-shadowed customer. Risk-flagged customers (e.g. with a
    delinquent facility) render in a distinct color."""
    risk_customer_ids = risk_customer_ids or set()
    nodes = {}
    for row in hierarchy_rows:
        source_id = row["sourceId"]
        nid = _node_id("meridian", source_id)
        nodes[nid] = {
            "id": nid,
            "label": f"Customer: {row.get('customerName') or source_id}",
            "group": "meridian",
            "color": _RISK_COLOR if source_id in risk_customer_ids else _GROUP_COLORS["meridian"],
            "componentId": None,
        }
    edges = [
        {
            "from": _node_id("meridian", row["fromId"]),
            "to": _node_id("meridian", row["toId"]),
            "label": "HAS_PARENT",
            "title": "HAS_PARENT",
            "dashes": False,
        }
        for row in edge_rows
    ]
    return {"nodes": list(nodes.values()), "edges": edges}


def build_risk_profile_delta(customer_id, kyc, facilities):
    """Graph delta revealing a customer's KYC status and loan facilities
    (e.g. from get_customer_risk_profile). Assumes the Customer node itself
    is already on the canvas from an earlier find_customer/find_parent_companies
    call. Facilities in Delinquent status render in the risk color, same
    threshold as build_hierarchy_delta."""
    customer_node_id = _node_id("meridian", customer_id)
    nodes = []
    edges = []

    if kyc:
        kyc_node_id = _node_id("meridian", f"KYC-{customer_id}")
        nodes.append({
            "id": kyc_node_id,
            "label": f"KYC: {kyc.get('riskRating') or 'Unknown'}",
            "group": "meridian",
            "color": _GROUP_COLORS["meridian"],
            "componentId": None,
        })
        edges.append({
            "from": customer_node_id,
            "to": kyc_node_id,
            "label": "HAS_KYC_STATUS",
            "title": "HAS_KYC_STATUS",
            "dashes": False,
        })

    for f in facilities:
        facility_node_id = _node_id("meridian", f["facilityId"])
        is_delinquent = f.get("paymentStatus") == "Delinquent"
        nodes.append({
            "id": facility_node_id,
            "label": f"Loan Facility: {f['facilityId']} ({f.get('paymentStatus')})",
            "group": "meridian",
            "color": _RISK_COLOR if is_delinquent else _GROUP_COLORS["meridian"],
            "componentId": None,
        })
        edges.append({
            "from": customer_node_id,
            "to": facility_node_id,
            "label": "HAS_FACILITY",
            "title": "HAS_FACILITY",
            "dashes": False,
        })

    return {"nodes": nodes, "edges": edges}


def build_credit_score_delta(customer_id, latest_score):
    """Graph delta revealing a customer's latest credit score (from
    get_customer_credit_score). Assumes the Customer node is already on
    the canvas."""
    if not latest_score:
        return {"nodes": [], "edges": []}

    score_id = latest_score.get("scoreId") or f"CS-{customer_id}"
    score_node_id = _node_id("meridian", score_id)
    nodes = [{
        "id": score_node_id,
        "label": f"Credit Score: {latest_score.get('creditScore')} ({latest_score.get('scoreBand')})",
        "group": "meridian",
        "color": _GROUP_COLORS["meridian"],
        "componentId": None,
    }]
    edges = [{
        "from": _node_id("meridian", customer_id),
        "to": score_node_id,
        "label": "HAS_CREDIT_SCORE",
        "title": "HAS_CREDIT_SCORE",
        "dashes": False,
    }]
    return {"nodes": nodes, "edges": edges}


def build_loan_application_delta(customer_id, applications):
    """Graph delta revealing a customer's loan applications (from
    get_customer_loan_applications). Assumes the Customer node is already
    on the canvas."""
    customer_node_id = _node_id("meridian", customer_id)
    nodes = []
    edges = []
    for application in applications:
        app_node_id = _node_id("meridian", application["applicationId"])
        nodes.append({
            "id": app_node_id,
            "label": f"Loan Application: {application['applicationId']} ({application.get('status')})",
            "group": "meridian",
            "color": _GROUP_COLORS["meridian"],
            "componentId": None,
        })
        edges.append({
            "from": customer_node_id,
            "to": app_node_id,
            "label": "APPLIED_FOR",
            "title": "APPLIED_FOR",
            "dashes": False,
        })
    return {"nodes": nodes, "edges": edges}


def build_transaction_summary_delta(customer_id, summary):
    """Graph delta revealing one aggregate transaction-activity node for a
    customer (get_customer_transaction_summary) -- individual transactions
    (there can be hundreds) aren't represented as their own nodes, just this
    one summary. Negative net cash flow renders in the risk color."""
    if not summary or not summary.get("transactionCount"):
        return {"nodes": [], "edges": []}

    net = summary.get("netCashFlow") or 0
    summary_node_id = _node_id("meridian", f"TXN-SUMMARY-{customer_id}")
    nodes = [{
        "id": summary_node_id,
        "label": f"Transactions: {summary['transactionCount']} (net {'-' if net < 0 else '+'}${abs(net):,.2f})",
        "group": "meridian",
        "color": _RISK_COLOR if net < 0 else _GROUP_COLORS["meridian"],
        "componentId": None,
    }]
    edges = [{
        "from": _node_id("meridian", customer_id),
        "to": summary_node_id,
        "label": "HAS_TRANSACTION_SUMMARY",
        "title": "HAS_TRANSACTION_SUMMARY",
        "dashes": False,
    }]
    return {"nodes": nodes, "edges": edges}


def fetch_graph_json(session):
    node_rows = [dict(r) for r in session.run(_FETCH_NODES)]
    edge_rows = [dict(r) for r in session.run(_FETCH_EDGES)]
    return build_vis_graph(node_rows, edge_rows)


def fetch_documents_graph_json(session):
    node_rows = [dict(r) for r in session.run(_FETCH_DOCUMENTS_NODES)]
    edge_rows = [dict(r) for r in session.run(_FETCH_DOCUMENTS_EDGES)]
    return build_vis_graph(node_rows, edge_rows)


def fetch_hierarchy_neighborhood(session, customer_id, max_hops=4):
    query = _FETCH_HIERARCHY_NEIGHBORHOOD.format(max_hops=max_hops)
    return [dict(r) for r in session.run(query, customerId=customer_id)]


def fetch_hierarchy_edges(session, ids):
    return [dict(r) for r in session.run(_FETCH_HIERARCHY_EDGES, ids=list(ids))]
