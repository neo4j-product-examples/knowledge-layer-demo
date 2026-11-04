from resolver import shadow_nodes


def test_meridian_shadow_nodes_exist_true(fake_session):
    fake_session.when("count(n)", [{"count": 3}])
    assert shadow_nodes.meridian_shadow_nodes_exist(fake_session) is True


def test_meridian_shadow_nodes_exist_false(fake_session):
    fake_session.when("count(n)", [{"count": 0}])
    assert shadow_nodes.meridian_shadow_nodes_exist(fake_session) is False


def test_seed_meridian_customers_merges_on_source_graph_and_id(fake_session):
    customers = [{"customerId": "C1", "customerName": "Jane Doe", "customerType": "Individual"}]

    shadow_nodes.seed_meridian_customers(fake_session, customers)

    assert len(fake_session.calls) == 1
    query, params = fake_session.calls[0]
    assert "UNWIND $rows AS row" in query
    assert "MERGE (n:Shadow:Customer" in query
    assert "USE meridianComposite.shadowDb" in query
    assert params["sourceGraph"] == "meridian"
    assert params["rows"] == [{"sourceId": "C1", "properties": {"name": "Jane Doe"}}]


def test_seed_meridian_customers_skips_missing_id(fake_session):
    shadow_nodes.seed_meridian_customers(fake_session, [{"customerId": None, "customerName": "X"}])
    assert fake_session.calls == []


def test_seed_meridian_accounts_merges_shadow_account(fake_session):
    shadow_nodes.seed_meridian_accounts(fake_session, [{"accountId": "A1"}])

    query, params = fake_session.calls[0]
    assert "MERGE (n:Shadow:Account" in query
    assert params["sourceGraph"] == "meridian"
    assert params["rows"] == [{"sourceId": "A1", "properties": {}}]


def test_create_document_shadow_node(fake_session):
    shadow_nodes.create_document_shadow_node(fake_session, "Person", "p1", {"name": "Jane"})

    query, params = fake_session.calls[0]
    assert "MERGE (n:Shadow:Person" in query
    assert params["sourceGraph"] == "documents"
    assert params["sourceId"] == "p1"
    assert params["properties"] == {"name": "Jane"}


def test_create_similar_to_sets_match_properties(fake_session):
    match = {
        "meridian_id": "C1",
        "documents_id": "p1",
        "matchType": "customer_exact",
        "confidence": 1.0,
        "matchedOn": "customerID",
    }

    shadow_nodes.create_similar_to(fake_session, match)

    query, params = fake_session.calls[0]
    assert "MERGE (m)-[r:SIMILAR_TO]-(d)" in query
    assert params["meridianId"] == "C1"
    assert params["documentsId"] == "p1"
    assert params["matchType"] == "customer_exact"
    assert params["confidence"] == 1.0


def test_clear_document_shadow_data_deletes_documents_shadow_nodes(fake_session):
    shadow_nodes.clear_document_shadow_data(fake_session)

    assert len(fake_session.calls) == 1
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.shadowDb" in query
    assert "MATCH (n:Shadow {sourceGraph: 'documents'})" in query
    assert "DETACH DELETE n" in query


def test_seed_document_shadow_nodes_creates_one_call_per_entity(fake_session):
    persons = [{"__id__": "p1", "customerID": None, "name": "Jane"}]
    organizations = [{"__id__": "o1", "name": "Acme"}]
    accounts = [{"__id__": "a1", "accountID": "1", "accountNumber": None}]
    properties = [{"__id__": "pr1", "name": "123 Main St"}]

    shadow_nodes.seed_document_shadow_nodes(fake_session, persons, organizations, accounts, properties)

    assert len(fake_session.calls) == 4
    labels = [q for q, _ in fake_session.calls]
    assert any("MERGE (n:Shadow:Person" in q for q in labels)
    assert any("MERGE (n:Shadow:Organization" in q for q in labels)
    assert any("MERGE (n:Shadow:Account" in q for q in labels)
    assert any("MERGE (n:Shadow:Property" in q for q in labels)


def test_seed_document_shadow_nodes_skips_missing_ids(fake_session):
    shadow_nodes.seed_document_shadow_nodes(
        fake_session,
        persons=[{"__id__": None, "name": "Jane"}],
        organizations=[],
        accounts=[],
        properties=[],
    )
    assert fake_session.calls == []


def test_seed_document_shadow_nodes_keeps_only_identity_properties(fake_session):
    persons = [{"__id__": "p1", "customerID": "CUST-1", "name": "Jane"}]
    accounts = [{"__id__": "a1", "accountID": "1", "accountNumber": "0001"}]

    shadow_nodes.seed_document_shadow_nodes(fake_session, persons, [], accounts, [])

    calls_by_label = {q.split("Shadow:")[1].split(" ")[0]: params for q, params in fake_session.calls}
    assert calls_by_label["Person"]["rows"][0]["properties"] == {"name": "Jane"}
    assert calls_by_label["Account"]["rows"][0]["properties"] == {}


def test_seed_document_shadow_nodes_seeds_loan_request_with_readable_name(fake_session):
    shadow_nodes.seed_document_shadow_nodes(
        fake_session,
        persons=[], organizations=[], accounts=[], properties=[],
        loan_requests=[{
            "__id__": "lr1", "requestedAmount": 400000, "termYears": 10,
            "rateType": "Fixed", "applicationId": "APP-3001", "purpose": "Expansion",
        }],
    )

    assert len(fake_session.calls) == 1
    query, params = fake_session.calls[0]
    assert "MERGE (n:Shadow:LoanRequest" in query
    assert params["rows"][0]["properties"] == {"name": "$400,000 10-yr Fixed Loan Request"}


def test_apply_document_matches_creates_node_then_edge_batch(fake_session):
    matches = [{
        "meridian_id": "C1",
        "documents_id": "p1",
        "matchType": "customer_exact",
        "confidence": 1.0,
        "matchedOn": "customerID",
    }]
    lookup = {"p1": {"name": "Jane Doe"}}

    shadow_nodes.apply_document_matches(fake_session, matches, "Person", lookup)

    assert len(fake_session.calls) == 2
    node_query, node_params = fake_session.calls[0]
    edge_query, edge_params = fake_session.calls[1]
    assert "MERGE (n:Shadow:Person" in node_query
    assert node_params["rows"][0]["properties"] == {"name": "Jane Doe"}
    assert "SIMILAR_TO" in edge_query
    assert edge_params["rows"][0]["meridianId"] == "C1"
