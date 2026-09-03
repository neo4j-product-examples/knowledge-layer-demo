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


def test_build_vis_graph_handles_node_with_no_edges():
    node_rows = [
        {"sourceGraph": "meridian", "sourceId": "C2", "labels": ["Shadow", "Customer"],
         "componentId": 1, "customerName": "Solo Corp", "name": None},
    ]

    graph = graph_data.build_vis_graph(node_rows, [])

    assert len(graph["nodes"]) == 1
    assert graph["edges"] == []
