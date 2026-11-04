from resolver import matching


def test_normalize_id_strips_whitespace_dashes_and_leading_zeros():
    assert matching.normalize_id(" 00A-123 ") == "a123"
    assert matching.normalize_id("A123") == "a123"
    assert matching.normalize_id(None) is None


def test_normalize_name_lowercases_and_strips_punctuation():
    assert matching.normalize_name("Acme, Inc.") == "acme inc"
    assert matching.normalize_name("  Jane   Doe ") == "jane doe"


def test_strip_legal_suffixes():
    assert matching.strip_legal_suffixes("acme inc") == "acme"
    assert matching.strip_legal_suffixes("acme llc") == "acme"
    assert matching.strip_legal_suffixes("jane doe") == "jane doe"


def test_is_business_detects_business_customer_types():
    assert matching.is_business("Business")
    assert matching.is_business("commercial")
    assert not matching.is_business("Individual")
    assert not matching.is_business(None)


def test_name_similarity_identical_names_is_one():
    assert matching.name_similarity("acme", "acme") == 1.0


def test_name_similarity_dissimilar_names_is_low():
    assert matching.name_similarity("acme corp", "totally different") < 0.5


def test_match_customers_exact_on_customer_id():
    customers = [{"customerId": "CUST-1", "customerName": "Jane Doe", "customerType": "Individual"}]
    persons = [{"__id__": "p1", "customerID": "cust-1", "name": "Someone Else"}]

    matches = matching.match_customers(customers, persons, [])

    assert len(matches) == 1
    assert matches[0]["matchType"] == "customer_exact"
    assert matches[0]["confidence"] == 1.0
    assert matches[0]["documents_id"] == "p1"


def test_match_customers_fuzzy_person_when_individual():
    customers = [{"customerId": "CUST-2", "customerName": "Jane Doe", "customerType": "Individual"}]
    persons = [{"__id__": "p2", "customerID": None, "name": "Jane Doe"}]

    matches = matching.match_customers(customers, persons, [])

    assert len(matches) == 1
    assert matches[0]["matchType"] == "name_fuzzy"
    assert matches[0]["documents_id"] == "p2"


def test_match_customers_fuzzy_organization_when_business():
    customers = [{"customerId": "CUST-3", "customerName": "Acme Inc.", "customerType": "Business"}]
    organizations = [{"__id__": "o1", "name": "Acme LLC"}]

    matches = matching.match_customers(customers, [], organizations)

    assert len(matches) == 1
    assert matches[0]["matchType"] == "name_fuzzy"
    assert matches[0]["documents_id"] == "o1"


def test_match_customers_no_match_below_threshold():
    customers = [{"customerId": "CUST-4", "customerName": "Zebra Holdings", "customerType": "Business"}]
    organizations = [{"__id__": "o2", "name": "Totally Unrelated Co"}]

    assert matching.match_customers(customers, [], organizations) == []


def test_fetch_meridian_customers_uses_meridian_constituent(fake_session):
    fake_session.when("MATCH (c:Customer)", [{"customerId": "1", "customerName": "A", "customerType": "Individual"}])

    rows = matching.fetch_meridian_customers(fake_session)

    assert rows == [{"customerId": "1", "customerName": "A", "customerType": "Individual"}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query


def test_fetch_document_persons_uses_documents_constituent(fake_session):
    fake_session.when("MATCH (p:Person)", [{"__id__": "p1", "customerID": None, "name": "A"}])

    rows = matching.fetch_document_persons(fake_session)

    assert rows == [{"__id__": "p1", "customerID": None, "name": "A"}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.documents" in query
    assert "coalesce(p.name, p.fullName)" in query


def test_fetch_document_loan_requests_uses_documents_constituent(fake_session):
    fake_session.when(
        "MATCH (o:Organization)-[:REQUESTS]->(lr:LoanRequest)",
        [{"__id__": "lr1", "organizationId": "o1", "requestedAmount": 400000, "termYears": 10}],
    )

    rows = matching.fetch_document_loan_requests(fake_session)

    assert rows == [{"__id__": "lr1", "organizationId": "o1", "requestedAmount": 400000, "termYears": 10}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.documents" in query


def test_fetch_document_business_plan_uses_documents_constituent(fake_session):
    fake_session.when(
        "MATCH (o:Organization)",
        [{
            "__id__": "o1", "name": "Rosa's Bakery", "address": "214 Maple St", "ein": "84-1023456",
            "industry": "Food & Beverage", "foundedDate": "2018-03", "bankingRelationshipSince": "2020-07",
            "bankingBranch": "Cedarville Main", "requestedAmount": 400000, "termYears": 10,
            "rateType": "Fixed", "applicationId": "APP-3001", "purpose": "Expansion",
            "useOfProceeds": "Build-out", "marketRationale": "Demand", "repaymentRationale": "Cash flow",
        }],
    )

    rows = matching.fetch_document_business_plan(fake_session)

    assert rows[0]["name"] == "Rosa's Bakery"
    assert rows[0]["requestedAmount"] == 400000
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.documents" in query


def test_fetch_document_worked_at_for(fake_session):
    fake_session.when("WORKED_AT", [{"personId": "p1", "organizationId": "o1"}])

    rows = matching.fetch_document_worked_at_for(fake_session, ["p1"], ["o1"])

    assert rows == [{"personId": "p1", "organizationId": "o1"}]


def test_fetch_document_worked_at_for_skips_query_with_no_ids(fake_session):
    assert matching.fetch_document_worked_at_for(fake_session, [], ["o1"]) == []
    assert fake_session.calls == []


def test_fetch_meridian_customer_hierarchy_neighbors_for_uses_meridian_constituent(fake_session):
    fake_session.when("HAS_PARENT", [{"sourceId": "C082", "customerName": "Alvarez Family Holdings LLC"}])

    rows = matching.fetch_meridian_customer_hierarchy_neighbors_for(fake_session, ["C001"])

    assert rows == [{"sourceId": "C082", "customerName": "Alvarez Family Holdings LLC"}]
    query, params = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query
    assert "*" not in query  # no variable-length pattern -- unsupported on the Virtual Graph
    assert params["customerIds"] == ["C001"]


def test_fetch_meridian_customer_hierarchy_neighbors_for_skips_query_with_no_ids(fake_session):
    assert matching.fetch_meridian_customer_hierarchy_neighbors_for(fake_session, []) == []
    assert fake_session.calls == []


def test_fetch_meridian_customer_hierarchy_for_uses_meridian_constituent(fake_session):
    fake_session.when("HAS_PARENT", [{"customerId": "C001", "parentCustomerId": "C082"}])

    rows = matching.fetch_meridian_customer_hierarchy_for(fake_session, ["C001", "C082"])

    assert rows == [{"customerId": "C001", "parentCustomerId": "C082"}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query


def test_fetch_meridian_customer_hierarchy_for_skips_query_with_no_ids(fake_session):
    assert matching.fetch_meridian_customer_hierarchy_for(fake_session, []) == []
    assert fake_session.calls == []


def test_fetch_meridian_customer_facilities_uses_meridian_constituent(fake_session):
    fake_session.when(
        "HAS_FACILITY",
        [{"customerId": "C002", "facilityId": "LOC-2002", "paymentStatus": "Delinquent", "daysPastDue": 62}],
    )

    rows = matching.fetch_meridian_customer_facilities(fake_session)

    assert rows == [{"customerId": "C002", "facilityId": "LOC-2002", "paymentStatus": "Delinquent", "daysPastDue": 62}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query


def test_fetch_meridian_customer_kyc_uses_meridian_constituent(fake_session):
    fake_session.when("HAS_KYC_STATUS", [{"customerId": "C001", "riskRating": "Low", "notes": "No flags"}])

    rows = matching.fetch_meridian_customer_kyc(fake_session)

    assert rows == [{"customerId": "C001", "riskRating": "Low", "notes": "No flags"}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query


def test_fetch_meridian_customer_credit_scores_uses_meridian_constituent(fake_session):
    fake_session.when(
        "HAS_CREDIT_SCORE",
        [{"customerId": "C001", "creditScore": 705, "scoreBand": "Good", "scoreDate": "2024-06-01"}],
    )

    rows = matching.fetch_meridian_customer_credit_scores(fake_session)

    assert rows == [{"customerId": "C001", "creditScore": 705, "scoreBand": "Good", "scoreDate": "2024-06-01"}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query


def test_fetch_meridian_customer_loan_applications_uses_meridian_constituent(fake_session):
    fake_session.when(
        "APPLIED_FOR",
        [{
            "customerId": "C001", "applicationId": "APP-3001", "status": "Under Review",
            "purpose": "Equipment purchase", "requestedAmount": 400000, "requestedRateType": "Fixed",
            "termYears": 10, "applicationDate": "2024-01-01",
        }],
    )

    rows = matching.fetch_meridian_customer_loan_applications(fake_session)

    assert rows[0]["applicationId"] == "APP-3001"
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query


def test_fetch_meridian_customer_transactions_uses_meridian_constituent(fake_session):
    fake_session.when(
        "HAS_TRANSACTION",
        [{
            "customerId": "C001", "transactionId": "T001", "transactionType": "Deposit",
            "amount": 100.0, "transactionDate": "2024-01-01",
        }],
    )

    rows = matching.fetch_meridian_customer_transactions(fake_session)

    assert rows[0]["transactionId"] == "T001"
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query


def test_fetch_meridian_customer_relationship_managers_uses_meridian_constituent(fake_session):
    fake_session.when(
        "MANAGED_BY",
        [{"customerId": "C001", "employeeId": "EMP002", "fullName": "Jamie Arnold", "role": "Relationship Manager"}],
    )

    rows = matching.fetch_meridian_customer_relationship_managers(fake_session)

    assert rows[0]["fullName"] == "Jamie Arnold"
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query


def test_fetch_meridian_employee_branches_uses_meridian_constituent(fake_session):
    fake_session.when(
        "WORKS_AT",
        [{"employeeId": "EMP002", "branchName": "Cedarville Main", "city": "Cedarville", "state": "OH"}],
    )

    rows = matching.fetch_meridian_employee_branches(fake_session)

    assert rows[0]["branchName"] == "Cedarville Main"
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query


def test_fetch_lending_policy_rules_uses_lendingpolicy_constituent(fake_session):
    fake_session.when(
        "HAS_RULE",
        [{
            "documentTitle": "Meridian Bank Commercial Lending Policy Manual", "documentVersion": "3.2",
            "sectionNumber": "§4", "sectionTitle": "Term Loans",
            "ruleId": "POL-001", "criterion": "Minimum Credit Score", "comparison": ">=",
            "threshold": 650, "unit": "score", "section": "§4.1", "description": "...",
            "escalationRole": None, "escalationTrigger": None, "escalationRequiredAction": None,
        }],
    )

    rows = matching.fetch_lending_policy_rules(fake_session, "LN-TERM")

    assert rows[0]["ruleId"] == "POL-001"
    query, params = fake_session.calls[0]
    assert "USE meridianComposite.lendingpolicy" in query
    assert params["productTypeCode"] == "LN-TERM"


def test_fetch_document_ownership_for_uses_documents_constituent(fake_session):
    fake_session.when(
        "MATCH (p:Person)-[:OWNS]->(o:Organization)",
        [{"personId": "p1", "organizationId": "o1"}],
    )

    rows = matching.fetch_document_ownership_for(fake_session, ["p1"], ["o1"])

    assert rows == [{"personId": "p1", "organizationId": "o1"}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.documents" in query


def test_fetch_document_requests_for_uses_documents_constituent(fake_session):
    fake_session.when(
        "MATCH (o:Organization)-[:REQUESTS]->(lr:LoanRequest)",
        [{"organizationId": "o1", "loanRequestId": "lr1"}],
    )

    rows = matching.fetch_document_requests_for(fake_session, ["o1"], ["lr1"])

    assert rows == [{"organizationId": "o1", "loanRequestId": "lr1"}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.documents" in query


def test_query_constituent_rejects_unknown_constituent(fake_session):
    try:
        matching.query_constituent(fake_session, "ontology", "MATCH (n) RETURN n")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "ontology" in str(e)
    assert fake_session.calls == []


def test_query_constituent_rejects_write_keywords(fake_session):
    unsafe_queries = [
        "MATCH (c:Customer) SET c.flag = true RETURN c",
        "CREATE (n:Foo) RETURN n",
        "MATCH (n) DETACH DELETE n",
        "MATCH (n) REMOVE n.foo RETURN n",
        "DROP INDEX foo",
        "CALL db.labels()",
        "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
        "MATCH (n) FOREACH (x IN [1,2] | SET n.y = x) RETURN n",
        "MATCH (a)-[r]->(b) MERGE (a)-[:NEW]->(b) RETURN r",
    ]
    for cypher in unsafe_queries:
        try:
            matching.query_constituent(fake_session, "meridian", cypher)
            assert False, f"expected ValueError for: {cypher}"
        except ValueError:
            pass
    assert fake_session.calls == []


def test_query_constituent_does_not_false_positive_on_substrings(fake_session):
    fake_session.when("RETURN c.offset", [{"offset": 5}])

    # "offset" contains "set" but isn't the SET keyword -- word-boundary
    # checking must not reject it.
    rows = matching.query_constituent(fake_session, "meridian", "MATCH (c:Customer) RETURN c.offset")

    assert rows == [{"offset": 5}]


def test_query_constituent_prepends_use_and_caps_limit(fake_session):
    fake_session.when("RETURN c", [{"c": 1}])

    matching.query_constituent(fake_session, "meridian", "MATCH (c:Customer) RETURN c LIMIT 9999")

    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query
    assert "LIMIT 9999" not in query
    assert query.strip().endswith("LIMIT 25")


def test_query_constituent_strips_trailing_semicolon(fake_session):
    fake_session.when("RETURN c", [{"c": 1}])

    matching.query_constituent(fake_session, "meridian", "MATCH (c:Customer) RETURN c;")

    query, _ = fake_session.calls[0]
    assert query.count(";") == 0


def test_query_constituent_stringifies_temporal_values(fake_session):
    fake_date = type("FakeNeo4jDate", (), {"__str__": lambda self: "2026-01-01"})()
    type(fake_date).__module__ = "neo4j.time"
    fake_session.when("RETURN n", [{"when": fake_date, "amount": 5}])

    rows = matching.query_constituent(fake_session, "meridian", "MATCH (n) RETURN n")

    assert rows == [{"when": "2026-01-01", "amount": 5}]


def test_query_constituent_serializes_whole_node_results(fake_session):
    # A model writing `RETURN p` instead of `RETURN p.name` gets back a
    # whole Node object, not a plain property value -- this must not
    # crash json.dumps downstream (it did, live, before this was handled).
    from neo4j.graph import Graph, Node

    graph = Graph()
    node = Node(graph, "elem-1", 1, n_labels=["Person"], properties={"name": "Marcus Alvarez"})
    fake_session.when("RETURN p", [{"p": node}])

    rows = matching.query_constituent(fake_session, "documents", "MATCH (p:Person) RETURN p")

    assert rows == [{"p": {"__labels__": ["Person"], "name": "Marcus Alvarez"}}]


def test_query_constituent_serializes_nodes_inside_a_list(fake_session):
    from neo4j.graph import Graph, Node

    graph = Graph()
    node = Node(graph, "elem-1", 1, n_labels=["Property"], properties={"name": "123 Main St"})
    fake_session.when("RETURN collect(prop)", [{"properties": [node]}])

    rows = matching.query_constituent(fake_session, "documents", "MATCH (p)-[:CO_OWNS]->(prop) RETURN collect(prop)")

    assert rows == [{"properties": [{"__labels__": ["Property"], "name": "123 Main St"}]}]
