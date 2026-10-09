from resolver import ontology


def test_fetch_schema_help_with_no_constituent_returns_hub_map(fake_session):
    fake_session.when(
        "MATCH (p:DataProduct)",
        [
            {"productId": "meridian", "name": "Banking Virtual Graph", "backend": "Aura Virtual Graph", "description": "..."},
            {"productId": "context", "name": "Decision History", "backend": "Standalone AuraDB", "description": "..."},
        ],
    )

    result = ontology.fetch_schema_help(fake_session)

    assert "hubs" in result
    assert "entities" not in result
    assert [h["productId"] for h in result["hubs"]] == ["meridian", "context"]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.ontology" in query


def test_fetch_schema_help_with_constituent_returns_entities_and_relationships(fake_session):
    fake_session.when(
        "MATCH (e:SchemaEntity {productId: $constituent})",
        [{"entityId": "context:Decision", "name": "Decision", "description": "..."}],
    )
    fake_session.when(
        "MATCH (a:SchemaEntity {productId: $constituent})-[r:RELATES]->(b:SchemaEntity)",
        [{"fromId": "context:Decision", "label": "ABOUT", "toId": "context:Customer", "description": "..."}],
    )

    result = ontology.fetch_schema_help(fake_session, "context")

    assert result["constituent"] == "context"
    assert result["entities"][0]["entityId"] == "context:Decision"
    assert result["relationships"][0]["label"] == "ABOUT"
    for query, params in fake_session.calls:
        assert "USE meridianComposite.ontology" in query
        assert params["constituent"] == "context"
