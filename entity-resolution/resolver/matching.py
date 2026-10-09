"""Entity matching logic between the `meridian` and `documents` graphs.

Design note: Aura Virtual Graph (the `meridian` constituent) only supports a
narrow Cypher subset (simple MATCH...RETURN, no complex WHERE expressions).
So matching itself is done in plain Python after fetching raw candidate
rows from each side with the simplest possible Cypher — this also keeps the
matching logic fully unit-testable without a live database.
"""
import re

from neo4j.graph import Node, Path, Relationship
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


def fetch_document_loan_requests(session):
    """Organization-[:REQUESTS]->LoanRequest rows, for shadowing the loan
    request onto the canvas alongside the Organization that made it (see
    fetch_document_business_plan for the fuller narrative used by the
    get_business_plan_details chat tool -- this is just the shadow-able
    node/edge shape)."""
    result = session.run(
        """
        USE meridianComposite.documents
        MATCH (o:Organization)-[:REQUESTS]->(lr:LoanRequest)
        RETURN lr.__id__ AS __id__, o.__id__ AS organizationId,
               lr.requestedAmount AS requestedAmount, lr.termYears AS termYears,
               lr.rateType AS rateType, lr.applicationId AS applicationId,
               lr.purpose AS purpose
        """
    )
    return [dict(r) for r in result]


def fetch_document_business_plan(session):
    """The uploaded business plan's own account of its business and its
    loan ask (Organization enriched with founding/banking-history facts,
    plus its LoanRequest if the document states one) -- as opposed to the
    bank's own systems (meridian), this is what the applicant itself said,
    for the agent to weigh alongside (not instead of) the bank's records."""
    result = session.run(
        """
        USE meridianComposite.documents
        MATCH (o:Organization)
        OPTIONAL MATCH (o)-[:REQUESTS]->(lr:LoanRequest)
        RETURN o.__id__ AS __id__, o.name AS name, o.address AS address,
               o.ein AS ein, o.industry AS industry, o.foundedDate AS foundedDate,
               o.bankingRelationshipSince AS bankingRelationshipSince,
               o.bankingBranch AS bankingBranch,
               lr.requestedAmount AS requestedAmount, lr.termYears AS termYears,
               lr.rateType AS rateType, lr.applicationId AS applicationId,
               lr.purpose AS purpose, lr.useOfProceeds AS useOfProceeds,
               lr.marketRationale AS marketRationale, lr.repaymentRationale AS repaymentRationale
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
    """PolicyDocument-[:HAS_SECTION]->PolicySection-[:HAS_RULE]->PolicyRule
    rows for one product type, from the lendingpolicy constituent (separate
    AuraDB, not the meridian banking data) -- the bank's own underwriting
    manual, so a loan recommendation can be checked against cited policy
    rather than reasoned freeform. Includes each rule's escalation path
    (REQUIRES_ESCALATION), if the policy calls for one."""
    result = session.run(
        """
        USE meridianComposite.lendingpolicy
        MATCH (p:ProductType {productTypeCode: $productTypeCode})<-[:APPLIES_TO]-(s:PolicySection)
        MATCH (d:PolicyDocument)-[:HAS_SECTION]->(s)
        MATCH (s)-[:HAS_RULE]->(r:PolicyRule)
        OPTIONAL MATCH (r)-[:REQUIRES_ESCALATION]->(e:EscalationPath)
        RETURN d.title AS documentTitle, d.version AS documentVersion,
               s.sectionNumber AS sectionNumber, s.title AS sectionTitle,
               r.ruleId AS ruleId, r.criterion AS criterion, r.comparison AS comparison,
               r.threshold AS threshold, r.unit AS unit, r.section AS section, r.description AS description,
               e.role AS escalationRole, e.trigger AS escalationTrigger,
               e.requiredAction AS escalationRequiredAction
        """,
        productTypeCode=product_type_code,
    )
    return [dict(r) for r in result]


def clear_customer_decisions(session, customer_id):
    """Deletes any recorded Decision nodes for one customer from the context
    constituent. Used to reset Rosa's Bakery's own decision to blank on every
    app load (see app.py's index route) so one demo run's recommendation
    never carries over into the next -- seeded historical decisions for
    other customers are untouched."""
    session.run(
        """
        USE meridianComposite.context
        MATCH (d:Decision {customerId: $customerId})
        DETACH DELETE d
        """,
        customerId=customer_id,
    )


def find_precedents_for_failed_rules(session, failed_rule_ids, exclude_decision_id=None):
    """Real precedent lookup: every past Decision with a real
    APPLIED_POLICY {failed: true} edge to any of the given policy rules.
    Pure read -- doesn't need the decision that's asking to exist yet, so
    chat.run_get_decision_history calls this to surface precedent BEFORE
    a recommendation is written (so it can actually inform the
    recommendation), and record_decision calls it again once the new
    decision exists, purely to persist the PRECEDENT_FOR edge for future
    lookups. Returns a list of dicts (decisionId, customerId,
    customerName, recommendation, reasoning, escalationRole, ruleId,
    ruleCriterion) -- one row per shared rule, so a decision that shares
    two rules in common can appear twice. Empty if failed_rule_ids is
    empty or nothing matches."""
    if not failed_rule_ids:
        return []
    result = session.run(
        """
        USE meridianComposite.context
        MATCH (rule:PolicyRule)
        WHERE rule.ruleId IN $failedRuleIds
        MATCH (rule)<-[:APPLIED_POLICY {failed: true}]-(priorDecision:Decision)
        WHERE priorDecision.decisionId <> $excludeDecisionId
        RETURN DISTINCT priorDecision.decisionId AS decisionId, priorDecision.customerId AS customerId,
               priorDecision.customerName AS customerName, priorDecision.recommendation AS recommendation,
               priorDecision.reasoning AS reasoning, priorDecision.escalationRole AS escalationRole,
               rule.ruleId AS ruleId, rule.criterion AS ruleCriterion
        """,
        failedRuleIds=failed_rule_ids, excludeDecisionId=exclude_decision_id or "",
    )
    return [dict(r) for r in result]


def record_decision(session, decision):
    """Persists one recommendation to the context constituent (MERGE on
    decisionId, so re-recording the same decisionId updates it in place
    rather than duplicating).

    Also materializes real ABOUT, APPLIED_POLICY, and TRIGGERED
    relationships to Customer/PolicyRule/Escalation nodes living inside
    `context` itself -- composite databases forbid relationships that
    cross constituents, so these are lightweight shadow copies (just the
    id and a display field, nothing sensitive), not references into
    meridian or lendingpolicy directly. decision's optional "appliedRules"
    key is a list of {ruleId, criterion, failed} dicts (see
    chat.run_record_decision) -- without it, only the Decision node and
    its ABOUT edge are written.

    Also re-runs find_precedents_for_failed_rules (the same lookup
    chat.run_get_decision_history already used, earlier this turn, to
    actually inform the recommendation) and gives each match a real,
    permanent PRECEDENT_FOR edge to this decision (Decision
    -[:PRECEDENT_FOR]-> Decision). This makes precedent a persisted fact
    of the graph rather than something re-derived by judgment on every
    later query. Returns that same list of prior decisions -- empty if
    this decision didn't fail anything a past decision also failed."""
    session.run(
        """
        USE meridianComposite.context
        MERGE (d:Decision {decisionId: $decisionId})
        SET d.customerId = $customerId, d.customerName = $customerName,
            d.productTypeCode = $productTypeCode, d.requestedAmount = $requestedAmount,
            d.recommendation = $recommendation, d.reasoning = $reasoning,
            d.appliedRuleIds = $appliedRuleIds, d.escalationRole = $escalationRole,
            d.failedRuleIds = $failedRuleIds, d.decidedAt = $decidedAt
        MERGE (c:Customer {customerId: $customerId})
        SET c.customerName = $customerName
        MERGE (d)-[:ABOUT]->(c)
        """,
        **decision,
    )
    applied_rules = decision.get("appliedRules") or []
    if applied_rules:
        session.run(
            """
            USE meridianComposite.context
            MATCH (d:Decision {decisionId: $decisionId})
            UNWIND $appliedRules AS rule
            MERGE (r:PolicyRule {ruleId: rule.ruleId})
            SET r.criterion = rule.criterion
            MERGE (d)-[rel:APPLIED_POLICY]->(r)
            SET rel.failed = rule.failed
            """,
            decisionId=decision["decisionId"], appliedRules=applied_rules,
        )

    if decision.get("escalationRole"):
        session.run(
            """
            USE meridianComposite.context
            MATCH (d:Decision {decisionId: $decisionId})
            MERGE (e:Escalation {role: $escalationRole})
            MERGE (d)-[:TRIGGERED]->(e)
            """,
            decisionId=decision["decisionId"], escalationRole=decision["escalationRole"],
        )

    precedents = find_precedents_for_failed_rules(
        session, decision.get("failedRuleIds") or [], exclude_decision_id=decision["decisionId"],
    )
    if precedents:
        session.run(
            """
            USE meridianComposite.context
            MATCH (newDecision:Decision {decisionId: $decisionId})
            UNWIND $priorDecisionIds AS priorDecisionId
            MATCH (priorDecision:Decision {decisionId: priorDecisionId})
            MERGE (priorDecision)-[:PRECEDENT_FOR]->(newDecision)
            """,
            decisionId=decision["decisionId"],
            priorDecisionIds=list({p["decisionId"] for p in precedents}),
        )
    return precedents


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


# The five real data constituents an ontology-guided query may target --
# "ontology" itself is deliberately excluded (that's get_schema_help's own
# job, via ontology.fetch_schema_help) so this tool can't be used to poke
# at the meta-graph instead of real data.
ONTOLOGY_QUERY_CONSTITUENTS = {"meridian", "documents", "lendingpolicy", "context", "shadowdb"}

# A model-authored Cypher fragment is rejected outright if it contains any
# of these, regardless of what it was trying to do -- this tool is
# read-only by construction, not by trusting the caller's intent. CALL is
# blocked wholesale (including the read-only CALL {...} subquery form)
# since telling those apart from a procedure call reliably isn't worth
# the complexity for a demo-scale ad-hoc lookup tool.
_FORBIDDEN_CYPHER_KEYWORDS = ("CREATE", "MERGE", "SET", "DELETE", "REMOVE", "DROP", "CALL", "LOAD CSV", "FOREACH")
_LIMIT_CLAUSE = re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE)
_QUERY_ROW_LIMIT = 25


def query_constituent(session, constituent, cypher):
    """Ad-hoc, read-only lookup against one of the five real data
    constituents, for analyst questions that fall outside the fixed tool
    set (see chat.run_ontology_guided_query) -- meant to be used after
    ontology.fetch_schema_help confirms the labels/relationships involved
    are real, not as a free pass to run anything. Three things this never
    trusts the caller to get right on its own:

    - the USE clause: always prepended here, from the closed
      ONTOLOGY_QUERY_CONSTITUENTS set, so a query can't target a
      different database or the ontology/shadow internals directly;
    - write/procedure keywords: rejected outright (ValueError) -- see
      _FORBIDDEN_CYPHER_KEYWORDS;
    - row count: any existing LIMIT clause is stripped and replaced with
      a hard cap (_QUERY_ROW_LIMIT), so a broad match can't dump an
      unbounded result into the conversation.

    Returns the raw rows as plain dicts, with any neo4j temporal value
    (Date/DateTime/Duration, ...) stringified so the result is always
    JSON-serializable regardless of what the query happened to return."""
    if constituent not in ONTOLOGY_QUERY_CONSTITUENTS:
        raise ValueError(
            f"Unknown constituent {constituent!r} -- must be one of {sorted(ONTOLOGY_QUERY_CONSTITUENTS)}."
        )

    upper = cypher.upper()
    for keyword in _FORBIDDEN_CYPHER_KEYWORDS:
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(keyword) + r"(?![A-Za-z0-9_])"
        if re.search(pattern, upper):
            raise ValueError(
                f"'{keyword}' isn't allowed here -- query_constituent is read-only. "
                "Write a MATCH/RETURN query with no writes or procedure calls."
            )

    capped_cypher = _LIMIT_CLAUSE.sub("", cypher.strip().rstrip(";"))
    full_query = f"USE meridianComposite.{constituent}\n{capped_cypher}\nLIMIT {_QUERY_ROW_LIMIT}"
    result = session.run(full_query)
    return [{key: _serialize_cypher_value(value) for key, value in dict(row).items()} for row in result]


def _serialize_cypher_value(value):
    """An ontology-guided query's RETURN clause is the model's own
    Cypher, not a fixed, known shape like every other query in this file
    -- it might return a whole Node/Relationship/Path (e.g. `RETURN p`
    instead of `RETURN p.name`), a list of them, or a plain temporal
    value, none of which json.dumps can serialize on their own. Recurses
    into lists/dicts so a query returning e.g. collect(p) still works."""
    if isinstance(value, Node):
        return {"__labels__": list(value.labels), **dict(value)}
    if isinstance(value, Relationship):
        return {"__type__": value.type, **dict(value)}
    if isinstance(value, Path):
        return {
            "nodes": [_serialize_cypher_value(n) for n in value.nodes],
            "relationships": [_serialize_cypher_value(r) for r in value.relationships],
        }
    if isinstance(value, list):
        return [_serialize_cypher_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_cypher_value(v) for k, v in value.items()}
    if type(value).__module__.startswith("neo4j.time"):
        return str(value)
    return value
