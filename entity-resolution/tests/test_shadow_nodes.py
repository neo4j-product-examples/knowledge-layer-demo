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
    assert params["rows"] == [{"sourceId": "C1", "properties": {"customerName": "Jane Doe", "customerType": "Individual"}}]


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


def test_create_shadow_relationship_merges_directed_edge(fake_session):
    shadow_nodes.create_shadow_relationship(fake_session, "OWNS_ACCOUNT", "meridian", "C1", "meridian", "A1")

    query, params = fake_session.calls[0]
    assert "MERGE (a)-[r:OWNS_ACCOUNT]->(b)" in query
    assert "USE meridianComposite.shadowDb" in query
    assert params == {
        "fromSourceGraph": "meridian",
        "fromSourceId": "C1",
        "toSourceGraph": "meridian",
        "toSourceId": "A1",
        "properties": {},
    }


def test_create_shadow_relationship_sets_given_properties(fake_session):
    shadow_nodes.create_shadow_relationship(
        fake_session, "OWNS", "documents", "p1", "documents", "o1", properties={"pct": 70, "role": "Founder & CEO"}
    )

    query, params = fake_session.calls[0]
    assert "SET r += $properties" in query
    assert params["properties"] == {"pct": 70, "role": "Founder & CEO"}


def test_seed_meridian_account_ownership_batches_all_edges_into_one_call(fake_session):
    edges = [{"customerId": "C1", "accountId": "A1"}, {"customerId": "C2", "accountId": "A2"}]

    shadow_nodes.seed_meridian_account_ownership(fake_session, edges)

    assert len(fake_session.calls) == 1
    query, params = fake_session.calls[0]
    assert "UNWIND $rows AS row" in query
    assert "OWNS_ACCOUNT" in query
    assert len(params["rows"]) == 2
    assert params["rows"][0] == {
        "fromSourceGraph": "meridian", "fromSourceId": "C1",
        "toSourceGraph": "meridian", "toSourceId": "A1",
        "properties": {},
    }


def test_seed_meridian_account_ownership_skips_missing_ids(fake_session):
    shadow_nodes.seed_meridian_account_ownership(fake_session, [{"customerId": None, "accountId": "A1"}])
    assert fake_session.calls == []


def test_seed_meridian_customer_hierarchy_batches_all_edges_into_one_call(fake_session):
    edges = [{"customerId": "C001", "parentCustomerId": "C082"}, {"customerId": "C002", "parentCustomerId": "C083"}]

    shadow_nodes.seed_meridian_customer_hierarchy(fake_session, edges)

    assert len(fake_session.calls) == 1
    query, params = fake_session.calls[0]
    assert "MERGE (a)-[r:HAS_PARENT]->(b)" in query
    assert len(params["rows"]) == 2
    assert params["rows"][0]["fromSourceId"] == "C001"
    assert params["rows"][0]["toSourceId"] == "C082"


def test_seed_meridian_customer_hierarchy_skips_missing_ids(fake_session):
    shadow_nodes.seed_meridian_customer_hierarchy(fake_session, [{"customerId": "C001", "parentCustomerId": None}])
    assert fake_session.calls == []


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
    assert params["rows"][0]["properties"]["name"] == "$400,000 10-yr Fixed Loan Request"
    assert params["rows"][0]["properties"]["applicationId"] == "APP-3001"


def test_seed_document_relationships_creates_requests_edge(fake_session):
    shadow_nodes.seed_document_relationships(
        fake_session,
        worked_at_edges=[], authorized_for_edges=[], co_owns_edges=[],
        requests_edges=[{"organizationId": "o1", "__id__": "lr1"}],
    )

    assert len(fake_session.calls) == 1
    query, params = fake_session.calls[0]
    assert "MERGE (a)-[r:REQUESTS]->(b)" in query
    assert params["rows"][0] == {
        "fromSourceGraph": "documents", "fromSourceId": "o1",
        "toSourceGraph": "documents", "toSourceId": "lr1",
        "properties": {},
    }


def test_seed_document_relationships_creates_one_call_per_edge_type(fake_session):
    shadow_nodes.seed_document_relationships(
        fake_session,
        worked_at_edges=[{"personId": "p1", "organizationId": "o1"}],
        authorized_for_edges=[{"personId": "p1", "accountId": "a1"}],
        co_owns_edges=[{"personId": "p1", "propertyId": "pr1"}],
    )

    assert len(fake_session.calls) == 3
    queries = [q for q, _ in fake_session.calls]
    assert any("WORKED_AT" in q for q in queries)
    assert any("AUTHORIZED_FOR" in q for q in queries)
    assert any("CO_OWNS" in q for q in queries)


def test_seed_document_relationships_skips_missing_ids(fake_session):
    shadow_nodes.seed_document_relationships(
        fake_session,
        worked_at_edges=[{"personId": None, "organizationId": "o1"}],
        authorized_for_edges=[],
        co_owns_edges=[],
    )
    assert fake_session.calls == []


def test_seed_document_relationships_creates_ownership_edge_with_properties(fake_session):
    shadow_nodes.seed_document_relationships(
        fake_session,
        worked_at_edges=[],
        authorized_for_edges=[],
        co_owns_edges=[],
        ownership_edges=[{"personId": "p1", "organizationId": "o1", "pct": 70, "role": "Founder & CEO"}],
    )

    assert len(fake_session.calls) == 1
    query, params = fake_session.calls[0]
    assert "MERGE (a)-[r:OWNS]->(b)" in query
    assert params["rows"][0]["properties"] == {"pct": 70, "role": "Founder & CEO"}


def test_seed_document_relationships_skips_ownership_edges_with_missing_ids(fake_session):
    shadow_nodes.seed_document_relationships(
        fake_session,
        worked_at_edges=[],
        authorized_for_edges=[],
        co_owns_edges=[],
        ownership_edges=[{"personId": None, "organizationId": "o1"}],
    )
    assert fake_session.calls == []


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
