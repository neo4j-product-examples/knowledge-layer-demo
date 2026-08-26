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


def test_build_vis_graph_handles_node_with_no_edges():
    node_rows = [
        {"sourceGraph": "meridian", "sourceId": "C2", "labels": ["Shadow", "Customer"],
         "componentId": 1, "customerName": "Solo Corp", "name": None},
    ]

    graph = graph_data.build_vis_graph(node_rows, [])

    assert len(graph["nodes"]) == 1
    assert graph["edges"] == []
