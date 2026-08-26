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


def test_match_accounts_exact_on_account_id():
    meridian_accounts = [{"accountId": "ACC-001"}]
    document_accounts = [{"__id__": "doc1", "accountID": "acc001", "accountNumber": None}]

    matches = matching.match_accounts(meridian_accounts, document_accounts)

    assert len(matches) == 1
    assert matches[0]["meridian_id"] == "ACC-001"
    assert matches[0]["documents_id"] == "doc1"
    assert matches[0]["matchType"] == "account_exact"
    assert matches[0]["confidence"] == 1.0
    assert matches[0]["matchedOn"] == "accountID"


def test_match_accounts_falls_back_to_account_number():
    meridian_accounts = [{"accountId": "ACC-002"}]
    document_accounts = [{"__id__": "doc2", "accountID": None, "accountNumber": "acc-002"}]

    matches = matching.match_accounts(meridian_accounts, document_accounts)

    assert len(matches) == 1
    assert matches[0]["matchedOn"] == "accountNumber"


def test_match_accounts_no_match():
    meridian_accounts = [{"accountId": "ACC-003"}]
    document_accounts = [{"__id__": "doc3", "accountID": "different", "accountNumber": "also-different"}]

    assert matching.match_accounts(meridian_accounts, document_accounts) == []


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


def test_fetch_meridian_account_ownership_uses_meridian_constituent(fake_session):
    fake_session.when("OWNS_ACCOUNT", [{"customerId": "C1", "accountId": "A1"}])

    rows = matching.fetch_meridian_account_ownership(fake_session)

    assert rows == [{"customerId": "C1", "accountId": "A1"}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query
    assert "OWNS_ACCOUNT" in query


def test_fetch_document_properties_uses_documents_constituent(fake_session):
    fake_session.when("MATCH (p:Property)", [{"__id__": "pr1", "name": "123 Main St"}])

    rows = matching.fetch_document_properties(fake_session)

    assert rows == [{"__id__": "pr1", "name": "123 Main St"}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.documents" in query


def test_fetch_document_worked_at(fake_session):
    fake_session.when("WORKED_AT", [{"personId": "p1", "organizationId": "o1"}])

    rows = matching.fetch_document_worked_at(fake_session)

    assert rows == [{"personId": "p1", "organizationId": "o1"}]


def test_fetch_document_authorized_for(fake_session):
    fake_session.when("AUTHORIZED_FOR", [{"personId": "p1", "accountId": "a1"}])

    rows = matching.fetch_document_authorized_for(fake_session)

    assert rows == [{"personId": "p1", "accountId": "a1"}]


def test_fetch_document_co_owns(fake_session):
    fake_session.when("CO_OWNS", [{"personId": "p1", "propertyId": "pr1"}])

    rows = matching.fetch_document_co_owns(fake_session)

    assert rows == [{"personId": "p1", "propertyId": "pr1"}]


def test_fetch_meridian_customer_hierarchy_uses_meridian_constituent(fake_session):
    fake_session.when("HAS_PARENT", [{"customerId": "C001", "parentCustomerId": "C082"}])

    rows = matching.fetch_meridian_customer_hierarchy(fake_session)

    assert rows == [{"customerId": "C001", "parentCustomerId": "C082"}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.meridian" in query


def test_fetch_document_ownership_uses_documents_constituent(fake_session):
    fake_session.when(
        "MATCH (p:Person)-[r:OWNS]->(o:Organization)",
        [{"personId": "p1", "organizationId": "o1", "pct": 70, "role": "Founder & CEO"}],
    )

    rows = matching.fetch_document_ownership(fake_session)

    assert rows == [{"personId": "p1", "organizationId": "o1", "pct": 70, "role": "Founder & CEO"}]
    query, _ = fake_session.calls[0]
    assert "USE meridianComposite.documents" in query
