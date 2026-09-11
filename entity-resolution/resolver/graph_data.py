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

_GROUP_COLORS = {"meridian": "#2B5876", "documents": "#D98847", "policy": "#4FA9B8", "context": "#7A5C99"}
_RISK_COLOR = "#D6483F"


def _node_id(source_graph, source_id):
    return f"{source_graph}:{source_id}"


def _customer_stub_node(customer_id):
    """A minimal Customer node, included in every per-tool delta below so
    the edge back to it always resolves. Without this, asking about a
    customer's risk profile/credit score/etc. by id directly (skipping
    find_customer, which is what normally puts the Customer node on
    canvas) leaves that entity's node floating with no edge -- the
    frontend has to drop dangling edges rather than crash, so the node
    just renders disconnected. If find_customer/find_parent_companies also
    ran, their nicer name-labeled node for the same id simply overwrites
    this stub client-side (both keyed by the same node id)."""
    return {
        "id": _node_id("meridian", customer_id),
        "label": f"Customer: {customer_id}",
        "group": "meridian",
        "color": _GROUP_COLORS["meridian"],
        "componentId": None,
    }


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
    (e.g. from get_customer_risk_profile). Includes a Customer stub node
    (see _customer_stub_node) so this renders connected even if
    find_customer hasn't put the real one on canvas yet. Facilities in
    Delinquent status render in the risk color, same threshold as
    build_hierarchy_delta."""
    if not kyc and not facilities:
        return {"nodes": [], "edges": []}

    customer_node_id = _node_id("meridian", customer_id)
    nodes = [_customer_stub_node(customer_id)]
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
    get_customer_credit_score). Includes a Customer stub node (see
    _customer_stub_node) so this renders connected even if find_customer
    hasn't put the real one on canvas yet."""
    if not latest_score:
        return {"nodes": [], "edges": []}

    score_id = latest_score.get("scoreId") or f"CS-{customer_id}"
    score_node_id = _node_id("meridian", score_id)
    nodes = [_customer_stub_node(customer_id), {
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
    get_customer_loan_applications). Includes a Customer stub node (see
    _customer_stub_node) so this renders connected even if find_customer
    hasn't put the real one on canvas yet."""
    if not applications:
        return {"nodes": [], "edges": []}

    customer_node_id = _node_id("meridian", customer_id)
    nodes = [_customer_stub_node(customer_id)]
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
    nodes = [_customer_stub_node(customer_id), {
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


def build_relationship_manager_delta(customer_id, relationship_manager):
    """Graph delta revealing the Employee who covers this customer as its
    relationship manager (get_relationship_manager). Includes a Customer
    stub node (see _customer_stub_node) so this renders connected even if
    find_customer hasn't put the real one on canvas yet."""
    if not relationship_manager:
        return {"nodes": [], "edges": []}

    employee_id = relationship_manager["employeeId"]
    employee_node_id = _node_id("meridian", employee_id)
    name = relationship_manager.get("fullName") or employee_id
    role = relationship_manager.get("role")
    nodes = [_customer_stub_node(customer_id), {
        "id": employee_node_id,
        "label": f"{name} ({role})" if role else name,
        "group": "meridian",
        "color": _GROUP_COLORS["meridian"],
        "componentId": None,
    }]
    edges = [{
        "from": _node_id("meridian", customer_id),
        "to": employee_node_id,
        "label": "MANAGED_BY",
        "title": "MANAGED_BY",
        "dashes": False,
    }]
    return {"nodes": nodes, "edges": edges}


def build_lending_policy_delta(customer_id, product_type_code, rules):
    """Graph delta revealing the policy section and rules checked against
    this customer's loan (get_lending_policy) -- and any escalation path a
    rule requires, flagged in the risk color since it means a human has to
    sign off before the loan can proceed. Includes a Customer stub node
    (see _customer_stub_node) so this renders connected even if
    find_customer hasn't put the real one on canvas yet."""
    if not rules:
        return {"nodes": [], "edges": []}

    first = rules[0]
    section_number = first.get("sectionNumber") or product_type_code
    section_node_id = _node_id("policy", section_number)
    section_label = f"{section_number} {first['sectionTitle']}" if first.get("sectionTitle") else section_number

    nodes = [
        _customer_stub_node(customer_id),
        {
            "id": section_node_id,
            "label": section_label,
            "group": "policy",
            "color": _GROUP_COLORS["policy"],
            "componentId": None,
        },
    ]
    edges = [{
        "from": _node_id("meridian", customer_id),
        "to": section_node_id,
        "label": "SUBJECT_TO_POLICY",
        "title": "SUBJECT_TO_POLICY",
        "dashes": False,
    }]

    for rule in rules:
        rule_node_id = _node_id("policy", rule["ruleId"])
        nodes.append({
            "id": rule_node_id,
            "label": f"{rule['ruleId']}: {rule.get('criterion')}",
            "group": "policy",
            "color": _GROUP_COLORS["policy"],
            "componentId": None,
        })
        edges.append({
            "from": section_node_id,
            "to": rule_node_id,
            "label": "HAS_RULE",
            "title": "HAS_RULE",
            "dashes": False,
        })

        if rule.get("escalationRole"):
            escalation_node_id = _node_id("policy", f"escalation:{rule['ruleId']}")
            nodes.append({
                "id": escalation_node_id,
                "label": rule["escalationRole"],
                "group": "policy",
                "color": _RISK_COLOR,
                "componentId": None,
            })
            edges.append({
                "from": rule_node_id,
                "to": escalation_node_id,
                "label": "REQUIRES_ESCALATION",
                "title": "REQUIRES_ESCALATION",
                "dashes": False,
            })

    return {"nodes": nodes, "edges": edges}


def build_decision_delta(decisions, current_customer_id=None):
    """Graph delta revealing past loan decisions from the context constituent
    (get_decision_history / record_decision). Each Decision connects to a
    Customer stub node (see _customer_stub_node) for whichever customer it
    was actually about, so precedent decisions about other customers render
    attached to their own customer rather than conflated with whoever is
    currently under discussion. Escalated decisions render in the risk
    color, same convention as build_lending_policy_delta.

    When current_customer_id is given (get_decision_history was scoped to a
    customer), any decision about a *different* customer also gets a dashed
    "CITED_AS_PRECEDENT" edge from the current customer -- otherwise a
    precedent decision would render as an unexplained, fully disconnected
    island with no visual link to the case it's actually informing."""
    if not decisions:
        return {"nodes": [], "edges": []}

    nodes = {}
    edges = []
    if current_customer_id:
        current_customer_node = _customer_stub_node(current_customer_id)
        nodes[current_customer_node["id"]] = current_customer_node

    for decision in decisions:
        customer_id = decision["customerId"]
        customer_node = _customer_stub_node(customer_id)
        nodes[customer_node["id"]] = customer_node

        decision_node_id = _node_id("context", decision["decisionId"])
        is_escalated = bool(decision.get("escalationRole"))
        nodes[decision_node_id] = {
            "id": decision_node_id,
            "label": f"{decision['recommendation']}: {decision.get('customerName') or customer_id}",
            "group": "context",
            "color": _RISK_COLOR if is_escalated else _GROUP_COLORS["context"],
            "componentId": None,
        }
        edges.append({
            "from": customer_node["id"],
            "to": decision_node_id,
            "label": "HAS_DECISION",
            "title": decision.get("reasoning") or "HAS_DECISION",
            "dashes": False,
        })

        if current_customer_id and customer_id != current_customer_id:
            edges.append({
                "from": _node_id("meridian", current_customer_id),
                "to": decision_node_id,
                "label": "CITED_AS_PRECEDENT",
                "title": "CITED_AS_PRECEDENT",
                "dashes": True,
            })

    return {"nodes": list(nodes.values()), "edges": edges}


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
