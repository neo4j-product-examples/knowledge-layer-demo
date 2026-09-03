from resolver import wcc


def test_compute_components_connects_matched_pair():
    nodes = [("meridian", "C1"), ("documents", "p1")]
    edges = [(("meridian", "C1"), ("documents", "p1"))]

    components = wcc.compute_components(nodes, edges)

    assert components[wcc.node_key("meridian", "C1")] == components[wcc.node_key("documents", "p1")]


def test_compute_components_keeps_unconnected_nodes_separate():
    nodes = [("meridian", "C1"), ("meridian", "C2")]
    edges = []

    components = wcc.compute_components(nodes, edges)

    assert components[wcc.node_key("meridian", "C1")] != components[wcc.node_key("meridian", "C2")]


def test_compute_components_transitively_links_a_chain():
    nodes = [("meridian", "C1"), ("documents", "p1"), ("documents", "a1")]
    edges = [
        (("meridian", "C1"), ("documents", "p1")),
        (("documents", "p1"), ("documents", "a1")),
    ]

    components = wcc.compute_components(nodes, edges)

    keys = [wcc.node_key(*n) for n in nodes]
    assert len({components[k] for k in keys}) == 1


def test_try_gds_wcc_returns_true_on_success(fake_session):
    fake_session.when("gds.graph.project", [{"componentCount": 1}])
    assert wcc.try_gds_wcc(fake_session) is True


def test_try_gds_wcc_returns_false_when_procedure_missing(fake_session):
    fake_session.when("gds.graph.project", Exception("no procedure gds.graph.project"))
    assert wcc.try_gds_wcc(fake_session) is False


def test_run_wcc_falls_back_to_python_when_gds_unavailable(fake_session):
    fake_session.when("gds.graph.project", Exception("no such procedure"))
    fake_session.when("OPTIONAL MATCH", [
        {"sourceGraph": "meridian", "sourceId": "C1", "otherSourceGraph": "documents", "otherSourceId": "p1"},
        {"sourceGraph": "documents", "sourceId": "p1", "otherSourceGraph": "meridian", "otherSourceId": "C1"},
    ])

    wcc.run_wcc(fake_session)

    write_calls = [c for c in fake_session.calls if "SET n.componentId" in c[0]]
    assert len(write_calls) == 2
    component_ids = {params["componentId"] for _, params in write_calls}
    assert len(component_ids) == 1
