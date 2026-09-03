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


def test_run_get_customer_risk_profile_handles_customer_with_no_data(fake_session):
    fake_session.when("HAS_KYC_STATUS", [{"customerId": "C002", "riskRating": "Medium", "notes": "x"}])
    fake_session.when("HAS_FACILITY", [])

    result = chat.run_get_customer_risk_profile(fake_session, "C999")

    assert result["kyc"] is None
    assert result["facilities"] == []


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
