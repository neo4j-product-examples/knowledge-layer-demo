"""Entity matching logic between the `meridian` and `documents` graphs.

Design note: Aura Virtual Graph (the `meridian` constituent) only supports a
narrow Cypher subset (simple MATCH...RETURN, no complex WHERE expressions).
So matching itself is done in plain Python after fetching raw candidate
rows from each side with the simplest possible Cypher — this also keeps the
matching logic fully unit-testable without a live database.
"""
import re

from rapidfuzz import fuzz

FUZZY_THRESHOLD = 0.85

_BUSINESS_KEYWORDS = ("business", "commercial", "corporate", "company", "organization", "org")

_LEGAL_SUFFIXES = (
    "inc", "incorporated", "llc", "l.l.c", "corp", "corporation",
    "co", "company", "ltd", "limited", "lp", "llp",
)


def normalize_id(value):
    """Normalize an identifier for exact comparison: strip whitespace,
    dashes, and leading zeros, and lowercase."""
    if value is None:
        return None
    cleaned = re.sub(r"[\s\-]", "", str(value)).lower()
    cleaned = cleaned.lstrip("0") or "0"
    return cleaned


def normalize_name(value):
    """Lowercase, strip punctuation/extra whitespace for name comparison."""
    if value is None:
        return None
    cleaned = re.sub(r"[^\w\s]", "", str(value)).lower()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def strip_legal_suffixes(name):
    """Remove common legal-entity suffixes from a normalized name."""
    if not name:
        return name
    tokens = [t for t in name.split(" ") if t not in _LEGAL_SUFFIXES]
    return " ".join(tokens).strip()


def name_similarity(a, b):
    """Token-set similarity between two names, scaled to 0-1."""
    if not a or not b:
        return 0.0
    return fuzz.token_sort_ratio(a, b) / 100.0


def is_business(customer_type):
    if not customer_type:
        return False
    lowered = str(customer_type).lower()
    return any(keyword in lowered for keyword in _BUSINESS_KEYWORDS)


def match_accounts(meridian_accounts, document_accounts):
    """Exact match on normalized account identifiers.

    meridian_accounts: list of dicts with at least 'accountId'
    document_accounts: list of dicts with 'accountID' and/or 'accountNumber'
    """
    matches = []
    for m in meridian_accounts:
        m_norm = normalize_id(m.get("accountId"))
        if not m_norm:
            continue
        for d in document_accounts:
            candidates = [
                ("accountID", d.get("accountID")),
                ("accountNumber", d.get("accountNumber")),
            ]
            for field, raw in candidates:
                if normalize_id(raw) == m_norm:
                    matches.append({
                        "meridian_id": m.get("accountId"),
                        "documents_id": d.get("__id__"),
                        "matchType": "account_exact",
                        "confidence": 1.0,
                        "matchedOn": field,
                    })
                    break
    return matches


def match_customers(meridian_customers, document_persons, document_organizations):
    """Match meridian Customers against documents Person/Organization nodes.

    Priority 1: exact customerId == Person.customerID.
    Priority 2: fuzzy name match — Person if not business, Organization if
    business, based on Customer.customerType.
    """
    matches = []
    for c in meridian_customers:
        c_id_norm = normalize_id(c.get("customerId"))
        matched = False

        if c_id_norm:
            for p in document_persons:
                if normalize_id(p.get("customerID")) == c_id_norm and p.get("customerID") is not None:
                    matches.append({
                        "meridian_id": c.get("customerId"),
                        "documents_id": p.get("__id__"),
                        "matchType": "customer_exact",
                        "confidence": 1.0,
                        "matchedOn": "customerID",
                    })
                    matched = True
        if matched:
            continue

        c_name = strip_legal_suffixes(normalize_name(c.get("customerName")))
        if not c_name:
            continue

        if is_business(c.get("customerType")):
            for o in document_organizations:
                o_name = strip_legal_suffixes(normalize_name(o.get("name")))
                score = name_similarity(c_name, o_name)
                if score >= FUZZY_THRESHOLD:
                    matches.append({
                        "meridian_id": c.get("customerId"),
                        "documents_id": o.get("__id__"),
                        "matchType": "name_fuzzy",
                        "confidence": score,
                        "matchedOn": "name",
                    })
        else:
            for p in document_persons:
                p_name = normalize_name(p.get("name"))
                score = name_similarity(c_name, p_name)
                if score >= FUZZY_THRESHOLD:
                    matches.append({
                        "meridian_id": c.get("customerId"),
                        "documents_id": p.get("__id__"),
                        "matchType": "name_fuzzy",
                        "confidence": score,
                        "matchedOn": "name",
                    })
    return matches


def fetch_meridian_customers(session):
    result = session.run(
        """
        USE meridianComposite.meridian
        MATCH (c:Customer)
        RETURN c.customerId AS customerId, c.customerName AS customerName,
               c.customerType AS customerType
        """
    )
    return [dict(r) for r in result]


def fetch_meridian_accounts(session):
    result = session.run(
        """
        USE meridianComposite.meridian
        MATCH (a:Account)
        RETURN a.accountId AS accountId
        """
    )
    return [dict(r) for r in result]


def fetch_document_persons(session):
    # Different extraction runs have stored the person's name under either
    # `name` or `fullName` (e.g. the Rosa's Bakery extraction uses
    # `fullName`) — coalesce so matching doesn't silently see null names.
    result = session.run(
        """
        USE meridianComposite.documents
        MATCH (p:Person)
        RETURN p.__id__ AS __id__, p.customerID AS customerID,
               coalesce(p.name, p.fullName) AS name
        """
    )
    return [dict(r) for r in result]


def fetch_document_organizations(session):
    result = session.run(
        """
        USE meridianComposite.documents
        MATCH (o:Organization)
        RETURN o.__id__ AS __id__, o.name AS name
        """
    )
    return [dict(r) for r in result]


def fetch_document_accounts(session):
    result = session.run(
        """
        USE meridianComposite.documents
        MATCH (a:Account)
        RETURN a.__id__ AS __id__, a.accountID AS accountID, a.accountNumber AS accountNumber
        """
    )
    return [dict(r) for r in result]


def fetch_document_properties(session):
    result = session.run(
        """
        USE meridianComposite.documents
        MATCH (p:Property)
        RETURN p.__id__ AS __id__, p.name AS name
        """
    )
    return [dict(r) for r in result]


def fetch_meridian_customer_hierarchy(session):
    """Customer-[:HAS_PARENT]->Customer pairs (corporate ownership hierarchy,
    e.g. Rosa's Bakery -> Alvarez Family Holdings LLC -> Cedarville
    Investment Group). Needed for WCC to surface hidden connections between
    customers that share an ultimate parent several hops up."""
    result = session.run(
        """
        USE meridianComposite.meridian
        MATCH (c:Customer)-[:HAS_PARENT]->(p:Customer)
        RETURN c.customerId AS customerId, p.customerId AS parentCustomerId
        """
    )
    return [dict(r) for r in result]


def fetch_meridian_account_ownership(session):
    """Customer-[:OWNS_ACCOUNT]->Account pairs, for shadowing the banking
    graph's own structure alongside its identity nodes."""
    result = session.run(
        """
        USE meridianComposite.meridian
        MATCH (c:Customer)-[:OWNS_ACCOUNT]->(a:Account)
        RETURN c.customerId AS customerId, a.accountId AS accountId
        """
    )
    return [dict(r) for r in result]


def fetch_document_worked_at(session):
    result = session.run(
        """
        USE meridianComposite.documents
        MATCH (p:Person)-[:WORKED_AT]->(o:Organization)
        RETURN p.__id__ AS personId, o.__id__ AS organizationId
        """
    )
    return [dict(r) for r in result]


def fetch_document_authorized_for(session):
    result = session.run(
        """
        USE meridianComposite.documents
        MATCH (p:Person)-[:AUTHORIZED_FOR]->(a:Account)
        RETURN p.__id__ AS personId, a.__id__ AS accountId
        """
    )
    return [dict(r) for r in result]


def fetch_document_co_owns(session):
    result = session.run(
        """
        USE meridianComposite.documents
        MATCH (p:Person)-[:CO_OWNS]->(pr:Property)
        RETURN p.__id__ AS personId, pr.__id__ AS propertyId
        """
    )
    return [dict(r) for r in result]


def fetch_meridian_customer_facilities(session):
    """Customer-[:HAS_FACILITY]->LoanFacility rows, for spotting delinquency
    on a customer discovered via the corporate hierarchy."""
    result = session.run(
        """
        USE meridianComposite.meridian
        MATCH (c:Customer)-[:HAS_FACILITY]->(f:LoanFacility)
        RETURN c.customerId AS customerId, f.facilityId AS facilityId,
               f.paymentStatus AS paymentStatus, f.daysPastDue AS daysPastDue
        """
    )
    return [dict(r) for r in result]


def fetch_meridian_customer_kyc(session):
    result = session.run(
        """
        USE meridianComposite.meridian
        MATCH (c:Customer)-[:HAS_KYC_STATUS]->(k:KYCStatus)
        RETURN c.customerId AS customerId, k.riskRating AS riskRating, k.notes AS notes
        """
    )
    return [dict(r) for r in result]


def fetch_meridian_customer_credit_scores(session):
    """Customer-[:HAS_CREDIT_SCORE]->CreditScore rows (a customer has a
    history of scores over time) -- used for loan-decision questions."""
    result = session.run(
        """
        USE meridianComposite.meridian
        MATCH (c:Customer)-[:HAS_CREDIT_SCORE]->(s:CreditScore)
        RETURN c.customerId AS customerId, s.scoreId AS scoreId, s.creditScore AS creditScore,
               s.scoreBand AS scoreBand, s.scoreDate AS scoreDate
        """
    )
    return [dict(r) for r in result]


def fetch_meridian_customer_loan_applications(session):
    """Customer-[:APPLIED_FOR]->LoanApplication rows -- pending/past loan
    requests, for loan-decision questions."""
    result = session.run(
        """
        USE meridianComposite.meridian
        MATCH (c:Customer)-[:APPLIED_FOR]->(l:LoanApplication)
        RETURN c.customerId AS customerId, l.applicationId AS applicationId,
               l.status AS status, l.purpose AS purpose,
               l.requestedAmount AS requestedAmount, l.requestedRateType AS requestedRateType,
               l.termYears AS termYears, l.applicationDate AS applicationDate
        """
    )
    return [dict(r) for r in result]


def fetch_meridian_customer_transactions(session):
    """Customer-[:OWNS_ACCOUNT]->Account-[:HAS_TRANSACTION]->Transaction rows,
    for summarizing cash-flow behavior on loan-decision questions."""
    result = session.run(
        """
        USE meridianComposite.meridian
        MATCH (c:Customer)-[:OWNS_ACCOUNT]->(a:Account)-[:HAS_TRANSACTION]->(t:Transaction)
        RETURN c.customerId AS customerId, t.transactionId AS transactionId,
               t.transactionType AS transactionType, t.amount AS amount,
               t.transactionDate AS transactionDate
        """
    )
    return [dict(r) for r in result]


def fetch_meridian_customer_relationship_managers(session):
    """Customer-[:MANAGED_BY]->Employee rows -- which relationship manager
    (if any) already covers this customer, for loan-decision questions
    (is there existing human context/coverage on this relationship)."""
    result = session.run(
        """
        USE meridianComposite.meridian
        MATCH (c:Customer)-[:MANAGED_BY]->(e:Employee)
        RETURN c.customerId AS customerId, e.employeeId AS employeeId,
               e.fullName AS fullName, e.role AS role
        """
    )
    return [dict(r) for r in result]


def fetch_meridian_employee_branches(session):
    """Employee-[:WORKS_AT]->Branch rows, for showing which branch a
    customer's relationship manager works out of."""
    result = session.run(
        """
        USE meridianComposite.meridian
        MATCH (e:Employee)-[:WORKS_AT]->(b:Branch)
        RETURN e.employeeId AS employeeId, b.branchName AS branchName,
               b.city AS city, b.state AS state
        """
    )
    return [dict(r) for r in result]


def fetch_lending_policy_rules(session, product_type_code):
    """ProductType-[:HAS_POLICY_RULE]->PolicyRule rows for one product type,
    from the lendingpolicy constituent (separate AuraDB, not the meridian
    banking data) -- the bank's own underwriting criteria, so a loan
    recommendation can be checked against cited policy rather than
    reasoned freeform."""
    result = session.run(
        """
        USE meridianComposite.lendingpolicy
        MATCH (p:ProductType {productTypeCode: $productTypeCode})-[:HAS_POLICY_RULE]->(r:PolicyRule)
        RETURN r.ruleId AS ruleId, r.criterion AS criterion, r.comparison AS comparison,
               r.threshold AS threshold, r.unit AS unit, r.section AS section, r.description AS description
        """,
        productTypeCode=product_type_code,
    )
    return [dict(r) for r in result]


def fetch_document_ownership(session):
    """Person-[:OWNS {pct, role}]->Organization pairs (e.g. Rosa/Marcus
    Alvarez owning Rosa's Bakery) — mirrors fetch_meridian_account_ownership
    but for the documents graph's own ownership structure."""
    result = session.run(
        """
        USE meridianComposite.documents
        MATCH (p:Person)-[r:OWNS]->(o:Organization)
        RETURN p.__id__ AS personId, o.__id__ AS organizationId,
               r.pct AS pct, r.role AS role
        """
    )
    return [dict(r) for r in result]
