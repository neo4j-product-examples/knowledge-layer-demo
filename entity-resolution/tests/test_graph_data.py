from resolver import graph_data, matching


def test_build_vis_graph_dedupes_nodes_and_preserves_edge_direction():
    node_rows = [
        {
            "sourceGraph": "meridian", "sourceId": "C1", "labels": ["Shadow", "Customer"],
            "name": "Jane Doe",
        },
        {
            "sourceGraph": "documents", "sourceId": "p1", "labels": ["Shadow", "Person"],
            "name": "Jane Doe",
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
         "name": "Jane Doe"},
        {"sourceGraph": "meridian", "sourceId": "A1", "labels": ["Shadow", "Account"],
         "name": None},
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
         "name": "Jane Doe"},
        {"sourceGraph": "documents", "sourceId": "p1", "labels": ["Shadow", "Person"],
         "name": "Jane Doe"},
    ]
    edge_rows = [
        {"fromSourceGraph": "meridian", "fromSourceId": "C1",
         "toSourceGraph": "documents", "toSourceId": "p1",
         "relType": "SIMILAR_TO", "confidence": 0.9, "matchType": "name_fuzzy"},
    ]

    graph = graph_data.build_vis_graph(node_rows, edge_rows)

    assert graph["edges"][0]["dashes"] is True
    assert graph["edges"][0]["title"] == "confidence: 0.9"


def test_fetch_hierarchy_neighborhood_walks_has_parent_one_hop_at_a_time(fake_session):
    # The meridian Virtual Graph doesn't support variable-length relationship
    # patterns, so this walks hop-by-hop in Python instead of one `*1..n`
    # Cypher query -- the single-hop query is reused unchanged on every hop.
    fake_session.when("HAS_PARENT", [{"sourceId": "C082", "customerName": "Alvarez Family Holdings LLC"}])

    rows = graph_data.fetch_hierarchy_neighborhood(fake_session, "C001", max_hops=4)

    assert rows == [{"sourceId": "C082", "customerName": "Alvarez Family Holdings LLC"}]
    query, params = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query
    assert params["customerIds"] == ["C001"]


def test_fetch_hierarchy_neighborhood_discovers_a_second_hop_without_revisiting(monkeypatch):
    hop_responses = {
        frozenset({"C001"}): [{"sourceId": "C082", "customerName": "Alvarez Family Holdings LLC"}],
        frozenset({"C082"}): [
            {"sourceId": "C001", "customerName": "Rosa's Bakery"},
            {"sourceId": "C083", "customerName": "Cedarville Investment Group"},
        ],
        frozenset({"C083"}): [{"sourceId": "C082", "customerName": "Alvarez Family Holdings LLC"}],
    }
    calls = []

    def fake_fetch(session, customer_ids):
        calls.append(set(customer_ids))
        return hop_responses.get(frozenset(customer_ids), [])

    monkeypatch.setattr(matching, "fetch_meridian_customer_hierarchy_neighbors_for", fake_fetch)

    rows = graph_data.fetch_hierarchy_neighborhood(None, "C001", max_hops=4)

    assert {r["sourceId"] for r in rows} == {"C082", "C083"}
    # Stops once a hop discovers nothing new, well short of max_hops.
    assert calls == [{"C001"}, {"C082"}, {"C083"}]


def test_fetch_hierarchy_edges_passes_id_list(fake_session):
    fake_session.when("HAS_PARENT", [{"fromId": "C001", "toId": "C082"}])

    rows = graph_data.fetch_hierarchy_edges(fake_session, {"C001", "C082"})

    assert rows == [{"fromId": "C001", "toId": "C082"}]
    _, params = fake_session.calls[0]
    assert set(params["ids"]) == {"C001", "C082"}


def test_build_match_delta_labels_customer_matches():
    matches = [
        {"meridian_id": "C001", "documents_id": "o1", "matchType": "name_fuzzy", "confidence": 1.0},
    ]
    meridian_customer_by_id = {"C001": {"customerName": "Rosas Bakery"}}

    delta = graph_data.build_match_delta(matches, meridian_customer_by_id)

    assert len(delta["nodes"]) == 1
    assert len(delta["edges"]) == 1
    labels = {n["id"]: n["label"] for n in delta["nodes"]}
    assert labels["meridian:C001"] == "Customer: Rosas Bakery"
    edge = delta["edges"][0]
    assert edge["from"] == "meridian:C001"
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
        "group": "meridian", "color": graph_data._GROUP_COLORS["meridian"],
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


def test_build_policy_failure_delta_flags_failed_rule():
    failed_rules = [
        {"ruleId": "POL-003", "criterion": "Maximum Loan Amount to Annual Cash Flow"},
    ]

    delta = graph_data.build_policy_failure_delta("C001", failed_rules)

    nodes_by_id = {n["id"]: n for n in delta["nodes"]}
    assert nodes_by_id["meridian:C001"]["label"] == "Customer: C001"
    assert nodes_by_id["policy:POL-003"]["color"] == graph_data._RISK_COLOR
    assert "Failed" in nodes_by_id["policy:POL-003"]["label"]

    edges = {(e["from"], e["to"], e["label"]) for e in delta["edges"]}
    assert ("meridian:C001", "policy:POL-003", "FAILS_POLICY") in edges


def test_build_policy_failure_delta_handles_no_failed_rules():
    delta = graph_data.build_policy_failure_delta("C001", [])

    assert delta == {"nodes": [], "edges": []}


def test_build_decision_delta_colors_by_outcome_with_no_customer_edge():
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
    assert nodes_by_id["context:DEC-C005-SEED"]["label"] == "Escalate: Snyder, Campos and Callahan"
    # Escalate counts as a fail outcome (it only happens because a rule
    # failed) -- red. Approve is a pass -- green. No customer node at all:
    # which customer a decision was about is a property, not a rendered edge.
    assert nodes_by_id["context:DEC-C005-SEED"]["color"] == graph_data._RISK_COLOR
    assert nodes_by_id["context:DEC-C002-SEED"]["color"] == graph_data._PASS_COLOR
    assert "meridian:C005" not in nodes_by_id
    assert "meridian:C002" not in nodes_by_id
    assert delta["edges"] == []


def test_build_decision_delta_handles_no_decisions():
    delta = graph_data.build_decision_delta([])

    assert delta == {"nodes": [], "edges": []}


def _flatten_steps(steps):
    nodes = {}
    edges = []
    for step in steps:
        for n in step["graph"]["nodes"]:
            nodes[n["id"]] = n
        edges.extend(step["graph"]["edges"])
    return nodes, edges


def test_build_rule_precedent_steps_cites_rule_then_case_then_outcome():
    precedents = [
        {
            "decisionId": "DEC-C009-SEED", "customerId": "C009", "customerName": "Cannon, Anderson and Alvarez",
            "recommendation": "Decline", "reasoning": "Over the cap too.", "escalationRole": None,
            "ruleId": "POL-003", "ruleCriterion": "Maximum Loan Amount to Annual Cash Flow",
        },
    ]

    steps = graph_data.build_rule_precedent_steps(precedents)
    nodes_by_id, edge_list = _flatten_steps(steps)
    edges = {(e["from"], e["to"], e["label"]) for e in edge_list}

    # The real rule -[:SAME_AS]-> its shadow copy in context.
    assert ("policy:POL-003", "context:policy:POL-003", "SAME_AS") in edges
    # The shadow copy -[:HAS_PRECEDENT]-> the case (not the decision).
    assert ("context:policy:POL-003", "context:case:DEC-C009-SEED", "HAS_PRECEDENT") in edges
    # The case -[:HAS_DECISION]-> its own separate decision/outcome node.
    assert ("context:case:DEC-C009-SEED", "context:decision:DEC-C009-SEED", "HAS_DECISION") in edges

    assert not any(nid.startswith("meridian:") for nid in nodes_by_id)
    # Only the real PolicyRule node (in the policy graph) flags red --
    # its context shadow copy stays plain context-purple.
    assert nodes_by_id["context:policy:POL-003"]["color"] == graph_data._GROUP_COLORS["context"]
    assert nodes_by_id["context:case:DEC-C009-SEED"]["color"] == graph_data._GROUP_COLORS["context"]
    assert nodes_by_id["context:decision:DEC-C009-SEED"]["color"] == graph_data._RISK_COLOR
    assert nodes_by_id["context:decision:DEC-C009-SEED"]["label"] == "Decline"

    labels = [s["label"] for s in steps]
    assert labels == [
        "Citing POL-003 in context graph",
        "Found precedent: Cannon, Anderson and Alvarez",
        "Precedent outcome: Decline",
    ]


def test_build_rule_precedent_steps_groups_by_rule():
    precedents = [
        {
            "decisionId": "DEC-A", "customerId": "C005", "customerName": "A", "recommendation": "Decline",
            "reasoning": "...", "escalationRole": None, "ruleId": "POL-003", "ruleCriterion": "...",
        },
        {
            "decisionId": "DEC-B", "customerId": "C006", "customerName": "B", "recommendation": "Decline",
            "reasoning": "...", "escalationRole": None, "ruleId": "POL-003", "ruleCriterion": "...",
        },
    ]

    steps = graph_data.build_rule_precedent_steps(precedents)
    _, edge_list = _flatten_steps(steps)

    same_as_edges = [e for e in edge_list if e["label"] == "SAME_AS"]
    assert len(same_as_edges) == 1
    found_labels = [s["label"] for s in steps if s["label"].startswith("Found precedent")]
    assert len(found_labels) == 2


def test_build_rule_precedent_steps_handles_no_precedents():
    assert graph_data.build_rule_precedent_steps([]) == []


def test_build_new_case_steps_links_every_failed_rule_with_one_final_outcome():
    new_decision = {
        "decisionId": "DEC-C001-1", "customerId": "C001", "customerName": "Rosas Bakery",
        "recommendation": "Decline", "reasoning": "...", "escalationRole": None,
    }
    failed_rules = [
        {"ruleId": "POL-003", "criterion": "Maximum Loan Amount to Annual Cash Flow"},
        {"ruleId": "POL-005", "criterion": "No Delinquent Facility"},
    ]

    steps = graph_data.build_new_case_steps(new_decision, failed_rules)
    nodes_by_id, edge_list = _flatten_steps(steps)
    edges = {(e["from"], e["to"], e["label"]) for e in edge_list}

    # Both shadow rules (and their SAME_AS edges) get created fresh here,
    # since no precedent lookup necessarily ran for either.
    assert ("policy:POL-003", "context:policy:POL-003", "SAME_AS") in edges
    assert ("policy:POL-005", "context:policy:POL-005", "SAME_AS") in edges
    assert ("context:policy:POL-003", "context:case:DEC-C001-1", "HAS_PRECEDENT") in edges
    assert ("context:policy:POL-005", "context:case:DEC-C001-1", "HAS_PRECEDENT") in edges
    assert ("context:case:DEC-C001-1", "context:decision:DEC-C001-1", "HAS_DECISION") in edges

    assert not any(nid.startswith("meridian:") for nid in nodes_by_id)
    assert nodes_by_id["context:case:DEC-C001-1"]["color"] == graph_data._GROUP_COLORS["context"]
    assert nodes_by_id["context:decision:DEC-C001-1"]["color"] == graph_data._RISK_COLOR

    # Only one final outcome step, even though two rules failed.
    outcome_steps = [s for s in steps if s["label"].startswith("Outcome:")]
    assert len(outcome_steps) == 1
    labels = [s["label"] for s in steps]
    assert labels == ["Linking this case to POL-003", "Linking this case to POL-005", "Outcome: Decline"]


def test_build_new_case_steps_handles_no_failed_rules():
    steps = graph_data.build_new_case_steps({"decisionId": "DEC-C001-1", "recommendation": "Approve"}, [])

    assert steps == []


def test_build_vis_graph_handles_node_with_no_edges():
    node_rows = [
        {"sourceGraph": "meridian", "sourceId": "C2", "labels": ["Shadow", "Customer"],
        "name": "Solo Corp"},
    ]

    graph = graph_data.build_vis_graph(node_rows, [])

    assert len(graph["nodes"]) == 1
    assert graph["edges"] == []


def test_ids_by_source_and_label_buckets_by_entity_label_not_sourcegraph_alone():
    node_rows = [
        {"sourceGraph": "meridian", "sourceId": "C1", "labels": ["Shadow", "Customer"]},
        {"sourceGraph": "meridian", "sourceId": "A1", "labels": ["Shadow", "Account"]},
        {"sourceGraph": "documents", "sourceId": "a1", "labels": ["Shadow", "Account"]},
    ]

    ids = graph_data._ids_by_source_and_label(node_rows)

    assert ids[("meridian", "Customer")] == ["C1"]
    assert ids[("meridian", "Account")] == ["A1"]
    assert ids[("documents", "Account")] == ["a1"]


def test_fetch_graph_json_merges_similar_to_with_a_live_structural_edge(fake_session):
    fake_session.when(
        "MATCH (n:Shadow)\nRETURN",
        [
            {"sourceGraph": "meridian", "sourceId": "C1", "labels": ["Shadow", "Customer"], "name": "Rosa's Bakery"},
            {"sourceGraph": "meridian", "sourceId": "C2", "labels": ["Shadow", "Customer"], "name": "Alvarez Holdings"},
        ],
    )
    fake_session.when("[r:SIMILAR_TO]", [])
    fake_session.when("HAS_PARENT", [{"customerId": "C1", "parentCustomerId": "C2"}])

    graph = graph_data.fetch_graph_json(fake_session)

    assert {n["id"] for n in graph["nodes"]} == {"meridian:C1", "meridian:C2"}
    assert graph["edges"] == [{
        "from": "meridian:C1", "to": "meridian:C2",
        "label": "HAS_PARENT", "title": "HAS_PARENT", "dashes": False,
    }]


def test_fetch_documents_graph_json_is_built_live_not_from_shadowdb(fake_session):
    persons = [{"__id__": "p1", "name": "Rosa Alvarez"}]
    organizations = [{"__id__": "o1", "name": "Rosa's Bakery"}]
    fake_session.when("WORKED_AT", [{"personId": "p1", "organizationId": "o1"}])

    graph = graph_data.fetch_documents_graph_json(fake_session, persons, organizations)

    assert {n["id"] for n in graph["nodes"]} == {"documents:p1", "documents:o1"}
    assert graph["edges"] == [{
        "from": "documents:p1", "to": "documents:o1",
        "label": "WORKED_AT", "title": "WORKED_AT", "dashes": False,
    }]
    # No read of shadowDb at all -- every call here targets documents/meridian live.
    assert not any("shadowDb" in q for q, _ in fake_session.calls)


def test_build_documents_graph_labels_persons_organizations_and_loan_requests():
    persons = [{"__id__": "p1", "name": "Rosa Alvarez"}]
    organizations = [{"__id__": "o1", "name": "Rosa's Bakery"}]
    loan_requests = [{"__id__": "lr1", "requestedAmount": 400000, "termYears": 10, "rateType": "Fixed"}]
    edge_rows = [{
        "fromSourceGraph": "documents", "fromSourceId": "p1",
        "toSourceGraph": "documents", "toSourceId": "o1",
        "relType": "WORKED_AT", "confidence": None, "matchType": None,
    }]

    graph = graph_data.build_documents_graph(persons, organizations, loan_requests, edge_rows)

    labels = {n["id"]: n["label"] for n in graph["nodes"]}
    assert labels["documents:p1"] == "Person: Rosa Alvarez"
    assert labels["documents:o1"] == "Organization: Rosa's Bakery"
    assert labels["documents:lr1"] == "LoanRequest: $400,000 10-yr Fixed Loan Request"
    assert graph["edges"] == [{
        "from": "documents:p1", "to": "documents:o1",
        "label": "WORKED_AT", "title": "WORKED_AT", "dashes": False,
    }]
