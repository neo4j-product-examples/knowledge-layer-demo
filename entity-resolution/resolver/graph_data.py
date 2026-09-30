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
_PASS_COLOR = "#4C8C5B"
# Recommendations that count as a real "fail" outcome for coloring a
# Decision node -- Escalate is included because it only ever happens as a
# consequence of a rule actually failing (see chat.run_record_decision),
# not a clean pass. PolicyRule nodes get the same _RISK_COLOR treatment
# when they fail (see build_policy_failure_delta/_shadow_rule_node), but
# based on a plain failed flag/membership, not this recommendation set.
_FAIL_RECOMMENDATIONS = {"Decline", "Escalate"}


def _decision_color(decision):
    return _RISK_COLOR if decision["recommendation"] in _FAIL_RECOMMENDATIONS else _PASS_COLOR


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


def build_policy_failure_delta(customer_id, failed_rules):
    """Graph delta flagging which policy rules the customer's actual
    figures FAILED against (record_decision) -- get_lending_policy only
    reveals the rules that were checked, not the verdict, so a rule the
    applicant fails (e.g. loan-to-cash-flow) never showed up any
    differently on the canvas than one they passed. Reuses the same
    policy:<ruleId> node id build_lending_policy_delta already put on
    screen, recoloring it red in place, plus a direct customer -> rule
    edge so the failure is visually obvious without having to trace back
    through the section."""
    if not failed_rules:
        return {"nodes": [], "edges": []}

    nodes = [_customer_stub_node(customer_id)]
    edges = []
    for rule in failed_rules:
        rule_node_id = _node_id("policy", rule["ruleId"])
        nodes.append({
            "id": rule_node_id,
            "label": f"{rule['ruleId']}: {rule.get('criterion')} (Failed)",
            "group": "policy",
            "color": _RISK_COLOR,
            "componentId": None,
        })
        edges.append({
            "from": _node_id("meridian", customer_id),
            "to": rule_node_id,
            "label": "FAILS_POLICY",
            "title": "FAILS_POLICY",
            "dashes": False,
        })
    return {"nodes": nodes, "edges": edges}


def build_decision_delta(decisions):
    """Graph delta revealing a plain, non-precedent loan decision -- used
    by chat.run_record_decision's clean-approval branch, when nothing
    failed and there's no shadow-rule chain to hang it off of (see
    build_new_case_steps for the failed-rule case). Just the Decision
    node itself, colored red or green by outcome (see _decision_color).
    No edge to a customer stub: which customer a decision was about is
    already a property on the Decision node itself (customerId/
    customerName, see matching.record_decision), not something the
    canvas needs a line for."""
    if not decisions:
        return {"nodes": [], "edges": []}

    nodes = {}
    for decision in decisions:
        decision_node_id = _node_id("context", decision["decisionId"])
        nodes[decision_node_id] = {
            "id": decision_node_id,
            "label": f"{decision['recommendation']}: {decision.get('customerName') or decision['customerId']}",
            "group": "context",
            "color": _decision_color(decision),
            "componentId": None,
        }
    return {"nodes": list(nodes.values()), "edges": []}


def _case_node(decision):
    """The citation itself -- which customer, which case -- as its own
    node, distinct from the outcome (see _outcome_node). Plain
    context-purple: a case isn't red or green, only its decision is."""
    return {
        "id": _node_id("context", f"case:{decision['decisionId']}"),
        "label": f"Case: {decision.get('customerName') or decision['customerId']}",
        "group": "context",
        "color": _GROUP_COLORS["context"],
        "componentId": None,
    }


def _outcome_node(decision):
    """Just the verdict -- a fact about the case (see _case_node), colored
    red or green (see _decision_color), connected FROM its case by
    HAS_DECISION."""
    return {
        "id": _node_id("context", f"decision:{decision['decisionId']}"),
        "label": decision["recommendation"],
        "group": "context",
        "color": _decision_color(decision),
        "componentId": None,
    }


def _shadow_rule_node(rule_id, criterion):
    """Every caller only ever creates this for a rule that actually
    failed (build_rule_precedent_steps's precedents and
    build_new_case_steps's failed_rules are both discovered/passed in
    precisely because the rule failed), so it's colored red like its real
    counterpart (see build_policy_failure_delta) rather than plain
    context-purple -- the SAME_AS pair should read as the same fact."""
    return {
        "id": _node_id("context", f"policy:{rule_id}"),
        "label": f"{rule_id}: {criterion or rule_id}",
        "group": "context",
        "color": _RISK_COLOR,
        "componentId": None,
    }


def build_rule_precedent_steps(precedents):
    """Ordered list of small graph deltas revealing real precedent for a
    set of failed policy rules, one hop at a time -- meant to be revealed
    live (see chat.run_get_decision_history / app.py's streaming loop).
    This is now called BEFORE a recommendation is written (get_decision_history's
    whole job), so it can actually inform the recommendation instead of
    just citing it afterward -- see build_new_case_steps for the second
    half, attaching the new decision once it's actually written.

    Each entry is {"label": <human-readable step label>, "graph": <delta>}.
    The chain so far, three hops:

        (PolicyRule, failed, in lendingpolicy -- colored red)
            -[:SAME_AS]->
        (PolicyRule shadow copy, in context -- also colored red, same fact)
            -[:HAS_PRECEDENT]->
        (Case -- the citation itself: which customer, which loan)
            -[:HAS_DECISION]->
        (Decision -- just the verdict, colored red/green)

    precedents is matching.find_precedents_for_failed_rules's result --
    each row carries the ruleId/ruleCriterion it matched on, grouped here
    by rule so every precedent for POL-003 reveals together before moving
    to POL-005."""
    if not precedents:
        return []

    rules_seen = []
    prior_by_rule = {}
    for prior in precedents:
        rule_id = prior["ruleId"]
        if rule_id not in prior_by_rule:
            prior_by_rule[rule_id] = []
            rules_seen.append(rule_id)
        prior_by_rule[rule_id].append(prior)

    steps = []
    for rule_id in rules_seen:
        priors = prior_by_rule[rule_id]
        shadow_rule_node = _shadow_rule_node(rule_id, priors[0].get("ruleCriterion"))
        shadow_rule_node_id = shadow_rule_node["id"]

        steps.append({
            "label": f"Citing {rule_id} in context graph",
            "graph": {
                "nodes": [shadow_rule_node],
                "edges": [{
                    "from": _node_id("policy", rule_id), "to": shadow_rule_node_id,
                    "label": "SAME_AS", "title": "SAME_AS", "dashes": False,
                }],
            },
        })

        for prior in priors:
            case_node = _case_node(prior)
            steps.append({
                "label": f"Found precedent: {prior.get('customerName') or prior['customerId']}",
                "graph": {
                    "nodes": [case_node],
                    "edges": [{
                        "from": shadow_rule_node_id, "to": case_node["id"],
                        "label": "HAS_PRECEDENT", "title": f"Also failed {rule_id}",
                        "dashes": False,
                    }],
                },
            })
            outcome_node = _outcome_node(prior)
            steps.append({
                "label": f"Precedent outcome: {prior['recommendation']}",
                "graph": {
                    "nodes": [outcome_node],
                    "edges": [{
                        "from": case_node["id"], "to": outcome_node["id"],
                        "label": "HAS_DECISION", "title": prior.get("reasoning") or "HAS_DECISION",
                        "dashes": False,
                    }],
                },
            })

    return steps


def build_new_case_steps(new_decision, failed_rules):
    """Ordered list of small graph deltas linking the just-recorded
    decision into the chain (see chat.run_record_decision, called after
    build_rule_precedent_steps already revealed whatever precedent
    exists) -- one "Linking this case to <rule>" hop per failed rule,
    then exactly one final "Outcome" hop, colored red/green (see
    _decision_color). Each per-rule hop re-sends the shadow rule node and
    its SAME_AS edge too (not just build_rule_precedent_steps's job) --
    harmless if already on screen (NVL just no-ops the repeat), but
    required if this rule had zero precedent, since nothing would have
    put that shadow node there otherwise.

    failed_rules is new_decision's own [{ruleId, criterion}, ...] (see
    chat.run_record_decision)."""
    if not failed_rules:
        return []

    new_case_node = _case_node(new_decision)
    new_case_node_id = new_case_node["id"]
    steps = []
    for rule in failed_rules:
        rule_id = rule["ruleId"]
        shadow_rule_node = _shadow_rule_node(rule_id, rule.get("criterion"))
        shadow_rule_node_id = shadow_rule_node["id"]
        steps.append({
            "label": f"Linking this case to {rule_id}",
            "graph": {
                "nodes": [shadow_rule_node, new_case_node],
                "edges": [
                    {
                        "from": _node_id("policy", rule_id), "to": shadow_rule_node_id,
                        "label": "SAME_AS", "title": "SAME_AS", "dashes": False,
                    },
                    {
                        "from": shadow_rule_node_id, "to": new_case_node_id,
                        "label": "HAS_PRECEDENT", "title": f"Also failed {rule_id}",
                        "dashes": False,
                    },
                ],
            },
        })

    new_outcome_node = _outcome_node(new_decision)
    steps.append({
        "label": f"Outcome: {new_decision['recommendation']}",
        "graph": {
            "nodes": [new_outcome_node],
            "edges": [{
                "from": new_case_node_id, "to": new_outcome_node["id"],
                "label": "HAS_DECISION", "title": new_decision.get("reasoning") or "HAS_DECISION",
                "dashes": False,
            }],
        },
    })

    return steps


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
