from resolver import graph_data


def test_build_vis_graph_dedupes_nodes_and_preserves_edge_direction():
    node_rows = [
        {
            "sourceGraph": "meridian", "sourceId": "C1", "labels": ["Shadow", "Customer"],
            "componentId": 0, "customerName": "Jane Doe", "name": None,
        },
        {
            "sourceGraph": "documents", "sourceId": "p1", "labels": ["Shadow", "Person"],
            "componentId": 0, "customerName": None, "name": "Jane Doe",
        },
    ]
    edge_rows = [
        {
            "fromSourceGraph": "meridian", "fromSourceId": "C1",
            "toSourceGraph": "documents", "toSourceId": "p1",
            "relType": "SIMILAR_TO", "confidence": 1.0, "matchType": "customer_exact",
        },
    ]

    graph = graph_data.build_vis_graph(node_rows, edge_rows)

    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 1
    node_ids = {n["id"] for n in graph["nodes"]}
    assert node_ids == {"meridian:C1", "documents:p1"}
    assert graph["edges"][0]["from"] == "meridian:C1"
    assert graph["edges"][0]["to"] == "documents:p1"


def test_build_vis_graph_keeps_structural_edge_direction_even_when_ids_sort_the_other_way():
    # Account id sorts before Customer id alphabetically, but the real
    # relationship is Customer -[:OWNS_ACCOUNT]-> Account.
    node_rows = [
        {"sourceGraph": "meridian", "sourceId": "C1", "labels": ["Shadow", "Customer"],
         "componentId": 0, "customerName": "Jane Doe", "name": None},
        {"sourceGraph": "meridian", "sourceId": "A1", "labels": ["Shadow", "Account"],
         "componentId": 0, "customerName": None, "name": None},
    ]
    edge_rows = [
        {"fromSourceGraph": "meridian", "fromSourceId": "C1",
         "toSourceGraph": "meridian", "toSourceId": "A1",
         "relType": "OWNS_ACCOUNT", "confidence": None, "matchType": None},
    ]

    graph = graph_data.build_vis_graph(node_rows, edge_rows)

    assert graph["edges"][0]["from"] == "meridian:C1"
    assert graph["edges"][0]["to"] == "meridian:A1"
    assert graph["edges"][0]["dashes"] is False


def test_build_vis_graph_marks_match_edges_as_dashed():
    node_rows = [
        {"sourceGraph": "meridian", "sourceId": "C1", "labels": ["Shadow", "Customer"],
         "componentId": 0, "customerName": "Jane Doe", "name": None},
        {"sourceGraph": "documents", "sourceId": "p1", "labels": ["Shadow", "Person"],
         "componentId": 0, "customerName": None, "name": "Jane Doe"},
    ]
    edge_rows = [
        {"fromSourceGraph": "meridian", "fromSourceId": "C1",
         "toSourceGraph": "documents", "toSourceId": "p1",
         "relType": "SIMILAR_TO", "confidence": 0.9, "matchType": "name_fuzzy"},
    ]

    graph = graph_data.build_vis_graph(node_rows, edge_rows)

    assert graph["edges"][0]["dashes"] is True
    assert graph["edges"][0]["title"] == "confidence: 0.9"


def test_fetch_hierarchy_neighborhood_uses_shadowdb_and_max_hops(fake_session):
    fake_session.when("HAS_PARENT", [{"sourceId": "C082", "customerName": "Alvarez Family Holdings LLC"}])

    rows = graph_data.fetch_hierarchy_neighborhood(fake_session, "C001", max_hops=4)

    assert rows == [{"sourceId": "C082", "customerName": "Alvarez Family Holdings LLC"}]
    query, params = fake_session.calls[0]
    assert "USE meridianComposite.shadowDb" in query
    assert "*1..4" in query
    assert params["customerId"] == "C001"


def test_fetch_hierarchy_edges_passes_id_list(fake_session):
    fake_session.when("HAS_PARENT", [{"fromId": "C001", "toId": "C082"}])

    rows = graph_data.fetch_hierarchy_edges(fake_session, {"C001", "C082"})

    assert rows == [{"fromId": "C001", "toId": "C082"}]
    _, params = fake_session.calls[0]
    assert set(params["ids"]) == {"C001", "C082"}


def test_build_match_delta_labels_customer_and_account_matches():
    matches = [
        {"meridian_id": "C001", "documents_id": "o1", "matchType": "name_fuzzy", "confidence": 1.0},
        {"meridian_id": "A00001", "documents_id": "a1", "matchType": "account_exact", "confidence": 1.0},
    ]
    meridian_customer_by_id = {"C001": {"customerName": "Rosas Bakery"}}
    meridian_account_by_id = {"A00001": {"accountId": "A00001"}}

    delta = graph_data.build_match_delta(matches, meridian_customer_by_id, meridian_account_by_id)

    assert len(delta["nodes"]) == 2
    assert len(delta["edges"]) == 2
    labels = {n["id"]: n["label"] for n in delta["nodes"]}
    assert labels["meridian:C001"] == "Customer: Rosas Bakery"
    assert labels["meridian:A00001"] == "Account: A00001"
    edge = next(e for e in delta["edges"] if e["from"] == "meridian:C001")
    assert edge["to"] == "documents:o1"
    assert edge["dashes"] is True


def test_build_hierarchy_delta_flags_risk_customers():
    hierarchy_rows = [
        {"sourceId": "C082", "customerName": "Alvarez Family Holdings LLC"},
        {"sourceId": "C002", "customerName": "Alvarez Distribution Co"},
    ]
    edge_rows = [{"fromId": "C001", "toId": "C082"}, {"fromId": "C002", "toId": "C083"}]

    delta = graph_data.build_hierarchy_delta(hierarchy_rows, edge_rows, risk_customer_ids={"C002"})

    colors = {n["id"]: n["color"] for n in delta["nodes"]}
    assert colors["meridian:C002"] == graph_data._RISK_COLOR
    assert colors["meridian:C082"] == graph_data._GROUP_COLORS["meridian"]
    assert len(delta["edges"]) == 2
    assert delta["edges"][0]["label"] == "HAS_PARENT"


def test_build_hierarchy_delta_with_no_risk_customers():
    hierarchy_rows = [{"sourceId": "C082", "customerName": "Alvarez Family Holdings LLC"}]

    delta = graph_data.build_hierarchy_delta(hierarchy_rows, [])

    assert delta["nodes"][0]["color"] == graph_data._GROUP_COLORS["meridian"]
    assert delta["edges"] == []


def test_build_risk_profile_delta_flags_delinquent_facility():
    kyc = {"customerId": "C001", "riskRating": "Low", "notes": "No flags"}
    facilities = [
        {"customerId": "C001", "facilityId": "TL-1001", "paymentStatus": "Current", "daysPastDue": 0},
        {"customerId": "C001", "facilityId": "LOC-2002", "paymentStatus": "Delinquent", "daysPastDue": 62},
    ]

    delta = graph_data.build_risk_profile_delta("C001", kyc, facilities)

    colors = {n["id"]: n["color"] for n in delta["nodes"]}
    assert colors["meridian:KYC-C001"] == graph_data._GROUP_COLORS["meridian"]
    assert colors["meridian:TL-1001"] == graph_data._GROUP_COLORS["meridian"]
    assert colors["meridian:LOC-2002"] == graph_data._RISK_COLOR
    assert {e["to"] for e in delta["edges"]} == {"meridian:KYC-C001", "meridian:TL-1001", "meridian:LOC-2002"}


def test_build_risk_profile_delta_handles_no_kyc_or_facilities():
    delta = graph_data.build_risk_profile_delta("C999", None, [])

    assert delta == {"nodes": [], "edges": []}


def test_build_credit_score_delta_labels_score_and_band():
    latest_score = {"scoreId": "CS0000010", "creditScore": 721, "scoreBand": "Good"}

    delta = graph_data.build_credit_score_delta("C001", latest_score)

    nodes_by_id = {n["id"]: n for n in delta["nodes"]}
    assert nodes_by_id["meridian:C001"]["label"] == "Customer: C001"
    assert nodes_by_id["meridian:CS0000010"]["label"] == "Credit Score: 721 (Good)"
    assert delta["edges"] == [{
        "from": "meridian:C001", "to": "meridian:CS0000010",
        "label": "HAS_CREDIT_SCORE", "title": "HAS_CREDIT_SCORE", "dashes": False,
    }]


def test_build_credit_score_delta_handles_no_score():
    delta = graph_data.build_credit_score_delta("C999", None)

    assert delta == {"nodes": [], "edges": []}


def test_build_loan_application_delta_creates_node_and_edge_per_application():
    applications = [
        {"applicationId": "APP-3001", "status": "Under Review"},
        {"applicationId": "APP-3002", "status": "Approved"},
    ]

    delta = graph_data.build_loan_application_delta("C001", applications)

    assert len(delta["nodes"]) == 3  # customer stub + 2 applications
    assert len(delta["edges"]) == 2
    nodes_by_id = {n["id"]: n for n in delta["nodes"]}
    assert nodes_by_id["meridian:APP-3001"]["label"] == "Loan Application: APP-3001 (Under Review)"
    assert delta["edges"][0] == {
        "from": "meridian:C001", "to": "meridian:APP-3001",
        "label": "APPLIED_FOR", "title": "APPLIED_FOR", "dashes": False,
    }


def test_build_transaction_summary_delta_flags_negative_cash_flow():
    summary = {"transactionCount": 48, "netCashFlow": -83131.13}

    delta = graph_data.build_transaction_summary_delta("C002", summary)

    summary_node = next(n for n in delta["nodes"] if n["id"] == "meridian:TXN-SUMMARY-C002")
    assert summary_node["color"] == graph_data._RISK_COLOR
    assert "48" in summary_node["label"]
    assert delta["edges"][0]["from"] == "meridian:C002"


def test_build_transaction_summary_delta_positive_cash_flow_is_not_flagged():
    summary = {"transactionCount": 120, "netCashFlow": 127506.52}

    delta = graph_data.build_transaction_summary_delta("C001", summary)

    summary_node = next(n for n in delta["nodes"] if n["id"] == "meridian:TXN-SUMMARY-C001")
    assert summary_node["color"] == graph_data._GROUP_COLORS["meridian"]


def test_build_transaction_summary_delta_handles_no_transactions():
    delta = graph_data.build_transaction_summary_delta("C999", {"transactionCount": 0, "netCashFlow": 0})

    assert delta == {"nodes": [], "edges": []}


def test_build_relationship_manager_delta_labels_name_and_role():
    manager = {"employeeId": "EMP002", "fullName": "Jamie Arnold", "role": "Relationship Manager"}

    delta = graph_data.build_relationship_manager_delta("C001", manager)

    nodes_by_id = {n["id"]: n for n in delta["nodes"]}
    assert nodes_by_id["meridian:C001"]["label"] == "Customer: C001"
    assert nodes_by_id["meridian:EMP002"] == {
        "id": "meridian:EMP002", "label": "Jamie Arnold (Relationship Manager)",
        "group": "meridian", "color": graph_data._GROUP_COLORS["meridian"], "componentId": None,
    }
    assert delta["edges"] == [{
        "from": "meridian:C001", "to": "meridian:EMP002",
        "label": "MANAGED_BY", "title": "MANAGED_BY", "dashes": False,
    }]


def test_build_relationship_manager_delta_handles_no_manager():
    delta = graph_data.build_relationship_manager_delta("C999", None)

    assert delta == {"nodes": [], "edges": []}


def test_build_lending_policy_delta_creates_section_and_rule_nodes():
    rules = [
        {
            "ruleId": "POL-001", "criterion": "Minimum Credit Score",
            "sectionNumber": "§4", "sectionTitle": "Term Loans", "escalationRole": None,
        },
        {
            "ruleId": "POL-004", "criterion": "Maximum KYC Risk Rating",
            "sectionNumber": "§4", "sectionTitle": "Term Loans",
            "escalationRole": "Senior Underwriter", "escalationTrigger": "KYC risk is High",
            "escalationRequiredAction": "Sign-off required",
        },
    ]

    delta = graph_data.build_lending_policy_delta("C001", "LN-TERM", rules)

    nodes_by_id = {n["id"]: n for n in delta["nodes"]}
    assert nodes_by_id["meridian:C001"]["label"] == "Customer: C001"
    assert nodes_by_id["policy:§4"]["label"] == "§4 Term Loans"
    assert nodes_by_id["policy:§4"]["color"] == graph_data._GROUP_COLORS["policy"]
    assert nodes_by_id["policy:POL-001"]["label"] == "POL-001: Minimum Credit Score"
    assert nodes_by_id["policy:escalation:POL-004"]["label"] == "Senior Underwriter"
    assert nodes_by_id["policy:escalation:POL-004"]["color"] == graph_data._RISK_COLOR
    assert "policy:escalation:POL-001" not in nodes_by_id

    edges = {(e["from"], e["to"], e["label"]) for e in delta["edges"]}
    assert ("meridian:C001", "policy:§4", "SUBJECT_TO_POLICY") in edges
    assert ("policy:§4", "policy:POL-001", "HAS_RULE") in edges
    assert ("policy:§4", "policy:POL-004", "HAS_RULE") in edges
    assert ("policy:POL-004", "policy:escalation:POL-004", "REQUIRES_ESCALATION") in edges


def test_build_lending_policy_delta_handles_no_rules():
    delta = graph_data.build_lending_policy_delta("C999", "LN-TERM", [])

    assert delta == {"nodes": [], "edges": []}


def test_build_decision_delta_connects_each_decision_to_its_own_customer():
    decisions = [
        {
            "decisionId": "DEC-C005-SEED", "customerId": "C005", "customerName": "Snyder, Campos and Callahan",
            "recommendation": "Escalate", "reasoning": "Affiliate delinquency.", "escalationRole": "Credit Risk Committee",
        },
        {
            "decisionId": "DEC-C002-SEED", "customerId": "C002", "customerName": "Alvarez Distribution Co",
            "recommendation": "Approve", "reasoning": "Clean credit profile.", "escalationRole": None,
        },
    ]

    delta = graph_data.build_decision_delta(decisions)

    nodes_by_id = {n["id"]: n for n in delta["nodes"]}
    assert nodes_by_id["meridian:C005"]["label"] == "Customer: C005"
    assert nodes_by_id["context:DEC-C005-SEED"]["label"] == "Escalate: Snyder, Campos and Callahan"
    assert nodes_by_id["context:DEC-C005-SEED"]["color"] == graph_data._RISK_COLOR
    assert nodes_by_id["context:DEC-C002-SEED"]["color"] == graph_data._GROUP_COLORS["context"]

    edges = {(e["from"], e["to"], e["label"], e["dashes"]) for e in delta["edges"]}
    assert ("meridian:C005", "context:DEC-C005-SEED", "HAS_DECISION", False) in edges
    assert ("meridian:C002", "context:DEC-C002-SEED", "HAS_DECISION", False) in edges
    # No current_customer_id was given, so no CITED_AS_PRECEDENT edges.
    assert all(e[2] != "CITED_AS_PRECEDENT" for e in edges)


def test_build_decision_delta_adds_precedent_edge_for_other_customers():
    decisions = [
        {
            "decisionId": "DEC-C005-SEED", "customerId": "C005", "customerName": "Snyder, Campos and Callahan",
            "recommendation": "Escalate", "reasoning": "Affiliate delinquency.", "escalationRole": "Credit Risk Committee",
        },
    ]

    delta = graph_data.build_decision_delta(decisions, current_customer_id="C001")

    nodes_by_id = {n["id"]: n for n in delta["nodes"]}
    assert "meridian:C001" in nodes_by_id

    edges = {(e["from"], e["to"], e["label"], e["dashes"]) for e in delta["edges"]}
    assert ("meridian:C001", "context:DEC-C005-SEED", "CITED_AS_PRECEDENT", True) in edges


def test_build_decision_delta_skips_precedent_edge_for_same_customer():
    decisions = [
        {
            "decisionId": "DEC-C001-1", "customerId": "C001", "customerName": "Rosas Bakery",
            "recommendation": "Escalate", "reasoning": "...", "escalationRole": "Credit Risk Committee",
        },
    ]

    delta = graph_data.build_decision_delta(decisions, current_customer_id="C001")

    labels = {e["label"] for e in delta["edges"]}
    assert "CITED_AS_PRECEDENT" not in labels


def test_build_decision_delta_handles_no_decisions():
    delta = graph_data.build_decision_delta([])

    assert delta == {"nodes": [], "edges": []}


def test_build_vis_graph_handles_node_with_no_edges():
    node_rows = [
        {"sourceGraph": "meridian", "sourceId": "C2", "labels": ["Shadow", "Customer"],
         "componentId": 1, "customerName": "Solo Corp", "name": None},
    ]

    graph = graph_data.build_vis_graph(node_rows, [])

    assert len(graph["nodes"]) == 1
    assert graph["edges"] == []
