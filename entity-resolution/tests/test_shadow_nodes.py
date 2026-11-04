from resolver import shadow_nodes


def test_apply_document_matches_merges_both_endpoints_then_the_edge(fake_session):
    matches = [{
        "meridian_id": "C1",
        "documents_id": "p1",
        "matchType": "customer_exact",
        "confidence": 1.0,
        "matchedOn": "customerID",
    }]
    documents_lookup = {"p1": {"name": "Jane Doe"}}
    meridian_lookup = {"C1": {"customerId": "C1", "customerName": "Jane Doe Holdings"}}

    shadow_nodes.apply_document_matches(fake_session, matches, "Person", documents_lookup, meridian_lookup)

    assert len(fake_session.calls) == 3
    meridian_query, meridian_params = fake_session.calls[0]
    document_query, document_params = fake_session.calls[1]
    edge_query, edge_params = fake_session.calls[2]

    assert "MERGE (n:Shadow:Customer" in meridian_query
    assert meridian_params["sourceGraph"] == "meridian"
    assert meridian_params["rows"][0]["properties"] == {"name": "Jane Doe Holdings"}

    assert "MERGE (n:Shadow:Person" in document_query
    assert document_params["sourceGraph"] == "documents"
    assert document_params["rows"][0]["properties"] == {"name": "Jane Doe"}

    assert "SIMILAR_TO" in edge_query
    assert edge_params["rows"][0]["meridianId"] == "C1"
    assert edge_params["rows"][0]["documentsId"] == "p1"


def test_apply_document_matches_does_nothing_for_no_matches(fake_session):
    shadow_nodes.apply_document_matches(fake_session, [], "Organization", {}, {})
    assert fake_session.calls == []


def test_create_similar_to_batch_sets_match_properties(fake_session):
    matches = [{
        "meridian_id": "C1",
        "documents_id": "p1",
        "matchType": "customer_exact",
        "confidence": 1.0,
        "matchedOn": "customerID",
    }]

    shadow_nodes.create_similar_to_batch(fake_session, matches)

    assert len(fake_session.calls) == 1
    query, params = fake_session.calls[0]
    assert "MERGE (m)-[r:SIMILAR_TO]-(d)" in query
    assert params["rows"][0]["meridianId"] == "C1"
    assert params["rows"][0]["documentsId"] == "p1"
    assert params["rows"][0]["matchType"] == "customer_exact"
    assert params["rows"][0]["confidence"] == 1.0


def test_create_similar_to_batch_does_nothing_for_no_matches(fake_session):
    shadow_nodes.create_similar_to_batch(fake_session, [])
    assert fake_session.calls == []


def test_clear_orphaned_shadow_nodes_deletes_nodes_with_no_similar_to(fake_session):
    shadow_nodes.clear_orphaned_shadow_nodes(fake_session)

    assert len(fake_session.calls) == 1
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.shadowDb" in query
    assert "MATCH (n:Shadow)" in query
    assert "WHERE NOT (n)-[:SIMILAR_TO]-()" in query
    assert "DETACH DELETE n" in query
