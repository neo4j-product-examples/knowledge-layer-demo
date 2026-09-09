from resolver import chat, graph_data, matching, shadow_nodes


def test_run_get_customer_risk_profile_returns_matching_kyc_and_facilities(fake_session):
    fake_session.when("HAS_KYC_STATUS", [{"customerId": "C001", "riskRating": "Low", "notes": "No flags"}])
    fake_session.when(
        "HAS_FACILITY",
        [{"customerId": "C001", "facilityId": "TL-1001", "paymentStatus": "Current", "daysPastDue": 0}],
    )

    result = chat.run_get_customer_risk_profile(fake_session, "C001")

    assert result["customerId"] == "C001"
    assert result["kyc"]["riskRating"] == "Low"
    assert len(result["facilities"]) == 1
    nodes_by_id = {n["id"]: n for n in result["graph"]["nodes"]}
    assert "meridian:C001" in nodes_by_id
    assert "meridian:KYC-C001" in nodes_by_id
    assert nodes_by_id["meridian:TL-1001"]["color"] != graph_data._RISK_COLOR


def test_run_get_customer_risk_profile_handles_customer_with_no_data(fake_session):
    fake_session.when("HAS_KYC_STATUS", [{"customerId": "C002", "riskRating": "Medium", "notes": "x"}])
    fake_session.when("HAS_FACILITY", [])

    result = chat.run_get_customer_risk_profile(fake_session, "C999")

    assert result["kyc"] is None
    assert result["facilities"] == []
    assert result["graph"] == {"nodes": [], "edges": []}


def test_run_get_customer_risk_profile_flags_delinquent_facility(fake_session):
    fake_session.when("HAS_KYC_STATUS", [])
    fake_session.when(
        "HAS_FACILITY",
        [{"customerId": "C002", "facilityId": "LOC-2002", "paymentStatus": "Delinquent", "daysPastDue": 62}],
    )

    result = chat.run_get_customer_risk_profile(fake_session, "C002")

    nodes_by_id = {n["id"]: n for n in result["graph"]["nodes"]}
    assert nodes_by_id["meridian:LOC-2002"]["color"] == graph_data._RISK_COLOR


def test_run_find_customer_builds_matches_payload_and_applies_matches(monkeypatch, fake_session):
    monkeypatch.setattr(
        matching, "fetch_meridian_customers",
        lambda s: [{"customerId": "C001", "customerName": "Rosas Bakery", "customerType": "Business"}],
    )
    monkeypatch.setattr(matching, "fetch_meridian_accounts", lambda s: [])
    monkeypatch.setattr(matching, "fetch_document_persons", lambda s: [])
    monkeypatch.setattr(
        matching, "fetch_document_organizations",
        lambda s: [{"__id__": "o1", "name": "Rosa's Bakery"}],
    )
    monkeypatch.setattr(matching, "fetch_document_accounts", lambda s: [])

    applied = []
    monkeypatch.setattr(
        shadow_nodes, "apply_document_matches",
        lambda s, matches, label, lookup: applied.append((label, matches)),
    )

    result = chat.run_find_customer(fake_session)

    assert len(result["matches"]) == 1
    match = result["matches"][0]
    assert match["meridianId"] == "C001"
    assert match["meridianName"] == "Rosas Bakery"
    assert match["kind"] == "customer"
    assert result["graph"]["nodes"][0]["id"] == "meridian:C001"
    assert any(label == "Organization" and len(m) == 1 for label, m in applied)


def test_run_find_customer_returns_no_matches_cleanly(monkeypatch, fake_session):
    monkeypatch.setattr(matching, "fetch_meridian_customers", lambda s: [])
    monkeypatch.setattr(matching, "fetch_meridian_accounts", lambda s: [])
    monkeypatch.setattr(matching, "fetch_document_persons", lambda s: [])
    monkeypatch.setattr(matching, "fetch_document_organizations", lambda s: [])
    monkeypatch.setattr(matching, "fetch_document_accounts", lambda s: [])
    monkeypatch.setattr(shadow_nodes, "apply_document_matches", lambda *a, **k: None)

    result = chat.run_find_customer(fake_session)

    assert result["matches"] == []
    assert result["graph"] == {"nodes": [], "edges": []}


def test_run_find_parent_companies_flags_delinquent_related_company(monkeypatch, fake_session):
    monkeypatch.setattr(
        graph_data, "fetch_hierarchy_neighborhood",
        lambda s, cid: [{"sourceId": "C002", "customerName": "Alvarez Distribution Co"}],
    )
    monkeypatch.setattr(graph_data, "fetch_hierarchy_edges", lambda s, ids: [{"fromId": "C001", "toId": "C002"}])
    monkeypatch.setattr(
        matching, "fetch_meridian_customer_facilities",
        lambda s: [{"customerId": "C002", "facilityId": "LOC-2002", "paymentStatus": "Delinquent", "daysPastDue": 62}],
    )

    result = chat.run_find_parent_companies(fake_session, "C001")

    assert result["relatedCompanies"] == [{"customerId": "C002", "customerName": "Alvarez Distribution Co"}]
    assert result["delinquentFacilities"][0]["facilityId"] == "LOC-2002"
    assert result["graph"]["nodes"][0]["color"] == graph_data._RISK_COLOR


def test_describe_tool_call_includes_customer_id_when_present():
    label = chat.describe_tool_call("get_customer_credit_score", {"customer_id": "C001"})

    assert label == "Pulling credit score from virtual graph (C001)"


def test_describe_tool_call_handles_no_customer_id():
    label = chat.describe_tool_call("find_customer", {})

    assert label == "Finding matching Meridian customer"


def test_describe_tool_call_falls_back_for_unknown_tool():
    label = chat.describe_tool_call("some_new_tool", {})

    assert label == "Running some_new_tool"


def test_run_get_customer_credit_score_returns_latest_and_history(monkeypatch, fake_session):
    monkeypatch.setattr(
        matching, "fetch_meridian_customer_credit_scores",
        lambda s: [
            {"customerId": "C001", "creditScore": 687, "scoreBand": "Good", "scoreDate": "2024-01-01"},
            {"customerId": "C001", "creditScore": 721, "scoreBand": "Good", "scoreDate": "2024-06-01"},
            {"customerId": "C002", "creditScore": 550, "scoreBand": "Fair", "scoreDate": "2024-06-01"},
        ],
    )

    result = chat.run_get_customer_credit_score(fake_session, "C001")

    assert result["latestScore"]["creditScore"] == 721
    assert len(result["scoreHistory"]) == 2
    score_node = next(n for n in result["graph"]["nodes"] if n["label"] == "Credit Score: 721 (Good)")
    assert result["graph"]["edges"][0] == {
        "from": "meridian:C001", "to": score_node["id"],
        "label": "HAS_CREDIT_SCORE", "title": "HAS_CREDIT_SCORE", "dashes": False,
    }


def test_run_get_customer_credit_score_handles_no_history(monkeypatch, fake_session):
    monkeypatch.setattr(matching, "fetch_meridian_customer_credit_scores", lambda s: [])

    result = chat.run_get_customer_credit_score(fake_session, "C999")

    assert result["latestScore"] is None
    assert result["scoreHistory"] == []
    assert result["graph"] == {"nodes": [], "edges": []}


def test_run_get_customer_loan_applications_filters_by_customer(monkeypatch, fake_session):
    monkeypatch.setattr(
        matching, "fetch_meridian_customer_loan_applications",
        lambda s: [
            {"customerId": "C001", "applicationId": "APP-3001", "status": "Under Review", "applicationDate": "2024-01-01"},
            {"customerId": "C002", "applicationId": "APP-3002", "status": "Approved", "applicationDate": "2024-01-01"},
        ],
    )

    result = chat.run_get_customer_loan_applications(fake_session, "C001")

    assert result["applications"] == [
        {"customerId": "C001", "applicationId": "APP-3001", "status": "Under Review", "applicationDate": "2024-01-01"}
    ]
    nodes_by_id = {n["id"]: n for n in result["graph"]["nodes"]}
    assert nodes_by_id["meridian:C001"]["label"] == "Customer: C001"
    assert nodes_by_id["meridian:APP-3001"] == {
        "id": "meridian:APP-3001", "label": "Loan Application: APP-3001 (Under Review)",
        "group": "meridian", "color": graph_data._GROUP_COLORS["meridian"], "componentId": None,
    }
    assert result["graph"]["edges"] == [{
        "from": "meridian:C001", "to": "meridian:APP-3001",
        "label": "APPLIED_FOR", "title": "APPLIED_FOR", "dashes": False,
    }]


def test_run_get_customer_transaction_summary_computes_cash_flow(monkeypatch, fake_session):
    monkeypatch.setattr(
        matching, "fetch_meridian_customer_transactions",
        lambda s: [
            {"customerId": "C001", "transactionId": "T1", "transactionType": "Deposit", "amount": 500.0, "transactionDate": "2024-01-01"},
            {"customerId": "C001", "transactionId": "T2", "transactionType": "Withdrawal", "amount": -200.0, "transactionDate": "2024-02-01"},
            {"customerId": "C002", "transactionId": "T3", "transactionType": "Deposit", "amount": 1000.0, "transactionDate": "2024-01-01"},
        ],
    )

    result = chat.run_get_customer_transaction_summary(fake_session, "C001")

    assert result["transactionCount"] == 2
    assert result["totalInflow"] == 500.0
    assert result["totalOutflow"] == 200.0
    assert result["netCashFlow"] == 300.0
    assert result["transactionTypeBreakdown"] == {"Deposit": 1, "Withdrawal": 1}
    assert result["earliestDate"] == "2024-01-01"
    assert result["latestDate"] == "2024-02-01"
    summary_node = next(n for n in result["graph"]["nodes"] if n["id"] == "meridian:TXN-SUMMARY-C001")
    assert summary_node["color"] == graph_data._GROUP_COLORS["meridian"]
    assert result["graph"]["edges"][0]["from"] == "meridian:C001"


def test_run_get_customer_transaction_summary_flags_negative_cash_flow(monkeypatch, fake_session):
    monkeypatch.setattr(
        matching, "fetch_meridian_customer_transactions",
        lambda s: [
            {"customerId": "C002", "transactionId": "T1", "transactionType": "Withdrawal", "amount": -500.0, "transactionDate": "2024-01-01"},
        ],
    )

    result = chat.run_get_customer_transaction_summary(fake_session, "C002")

    summary_node = next(n for n in result["graph"]["nodes"] if n["id"] == "meridian:TXN-SUMMARY-C002")
    assert summary_node["color"] == graph_data._RISK_COLOR


def test_run_get_relationship_manager_joins_branch_info(monkeypatch, fake_session):
    monkeypatch.setattr(
        matching, "fetch_meridian_customer_relationship_managers",
        lambda s: [{"customerId": "C001", "employeeId": "EMP002", "fullName": "Jamie Arnold", "role": "Relationship Manager"}],
    )
    monkeypatch.setattr(
        matching, "fetch_meridian_employee_branches",
        lambda s: [{"employeeId": "EMP002", "branchName": "Cedarville Main", "city": "Cedarville", "state": "OH"}],
    )

    result = chat.run_get_relationship_manager(fake_session, "C001")

    assert result["relationshipManager"] == {
        "employeeId": "EMP002", "fullName": "Jamie Arnold", "role": "Relationship Manager",
        "branchName": "Cedarville Main", "city": "Cedarville", "state": "OH",
    }
    node_ids = {n["id"] for n in result["graph"]["nodes"]}
    assert node_ids == {"meridian:C001", "meridian:EMP002"}


def test_run_get_relationship_manager_handles_no_coverage(monkeypatch, fake_session):
    monkeypatch.setattr(matching, "fetch_meridian_customer_relationship_managers", lambda s: [])
    monkeypatch.setattr(matching, "fetch_meridian_employee_branches", lambda s: [])

    result = chat.run_get_relationship_manager(fake_session, "C999")

    assert result["relationshipManager"] is None
    assert result["graph"] == {"nodes": [], "edges": []}


def test_run_get_lending_policy_returns_rules_for_product_type(monkeypatch, fake_session):
    monkeypatch.setattr(
        matching, "fetch_lending_policy_rules",
        lambda s, code: [{"ruleId": "POL-001", "criterion": "Minimum Credit Score", "threshold": 650}],
    )

    result = chat.run_get_lending_policy(fake_session, "LN-TERM")

    assert result == {
        "productTypeCode": "LN-TERM",
        "rules": [{"ruleId": "POL-001", "criterion": "Minimum Credit Score", "threshold": 650}],
    }


def test_run_tool_dispatches_get_lending_policy(monkeypatch, fake_session):
    monkeypatch.setattr(chat, "run_get_lending_policy", lambda session, code: {"productTypeCode": code})

    result = chat.run_tool("get_lending_policy", {"product_type_code": "LN-TERM"}, fake_session)

    assert result == {"productTypeCode": "LN-TERM"}


def test_describe_tool_call_includes_product_type_code_when_present():
    label = chat.describe_tool_call("get_lending_policy", {"product_type_code": "LN-TERM"})

    assert label == "Checking lending policy (LN-TERM)"


def test_run_tool_dispatches_get_relationship_manager(monkeypatch, fake_session):
    monkeypatch.setattr(chat, "run_get_relationship_manager", lambda session, customer_id: {"customerId": customer_id})

    result = chat.run_tool("get_relationship_manager", {"customer_id": "C001"}, fake_session)

    assert result == {"customerId": "C001"}


def test_run_tool_dispatches_get_customer_credit_score(monkeypatch, fake_session):
    monkeypatch.setattr(chat, "run_get_customer_credit_score", lambda session, customer_id: {"customerId": customer_id})

    result = chat.run_tool("get_customer_credit_score", {"customer_id": "C001"}, fake_session)

    assert result == {"customerId": "C001"}


def test_run_tool_dispatches_get_customer_loan_applications(monkeypatch, fake_session):
    monkeypatch.setattr(chat, "run_get_customer_loan_applications", lambda session, customer_id: {"customerId": customer_id})

    result = chat.run_tool("get_customer_loan_applications", {"customer_id": "C001"}, fake_session)

    assert result == {"customerId": "C001"}


def test_run_tool_dispatches_get_customer_transaction_summary(monkeypatch, fake_session):
    monkeypatch.setattr(chat, "run_get_customer_transaction_summary", lambda session, customer_id: {"customerId": customer_id})

    result = chat.run_tool("get_customer_transaction_summary", {"customer_id": "C001"}, fake_session)

    assert result == {"customerId": "C001"}


def test_run_tool_dispatches_find_customer(monkeypatch, fake_session):
    monkeypatch.setattr(chat, "run_find_customer", lambda session: {"matches": [], "graph": {}})

    result = chat.run_tool("find_customer", {}, fake_session)

    assert result == {"matches": [], "graph": {}}


def test_run_tool_dispatches_find_parent_companies_with_customer_id(monkeypatch, fake_session):
    monkeypatch.setattr(chat, "run_find_parent_companies", lambda session, customer_id: {"customerId": customer_id})

    result = chat.run_tool("find_parent_companies", {"customer_id": "C001"}, fake_session)

    assert result == {"customerId": "C001"}


def test_run_tool_dispatches_get_customer_risk_profile(monkeypatch, fake_session):
    monkeypatch.setattr(chat, "run_get_customer_risk_profile", lambda session, customer_id: {"customerId": customer_id})

    result = chat.run_tool("get_customer_risk_profile", {"customer_id": "C002"}, fake_session)

    assert result == {"customerId": "C002"}


def test_run_tool_unknown_tool_returns_error(fake_session):
    result = chat.run_tool("not_a_real_tool", {}, fake_session)

    assert "error" in result


def test_merge_graph_deltas_dedupes_nodes_and_concatenates_edges():
    delta1 = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"from": "a", "to": "b"}]}
    delta2 = {"nodes": [{"id": "b", "updated": True}, {"id": "c"}], "edges": [{"from": "b", "to": "c"}]}

    merged = chat.merge_graph_deltas([delta1, delta2])

    assert [n["id"] for n in merged["nodes"]] == ["a", "b", "c"]
    node_b = next(n for n in merged["nodes"] if n["id"] == "b")
    assert node_b["updated"] is True
    assert len(merged["edges"]) == 2


def test_merge_graph_deltas_skips_none_entries():
    merged = chat.merge_graph_deltas([None, {"nodes": [{"id": "a"}], "edges": []}])

    assert merged["nodes"] == [{"id": "a"}]
