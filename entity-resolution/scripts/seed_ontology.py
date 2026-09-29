"""One-time seed script for the `meridianComposite.ontology` constituent (a
standalone AuraDB, aliased into the composite database -- see HANDOFF.md for
how that alias was created).

This is a small meta-graph, not a copy of any real data: one DataProduct
"hub" node per actual composite constituent (meridian, documents,
lendingpolicy, context, shadowDb), describing what it holds and how it's
backed. Each hub branches out into SchemaEntity "leaf" nodes -- the real
node labels that constituent's schema actually contains (pulled straight
from the Cypher in resolver/matching.py), connected by RELATES edges naming
the real relationship types between them. Hubs also connect to each other
(RESOLVES/SUPPLEMENTS/GOVERNS/CITES), describing how the constituents fit
together. This is what the "View Ontology" panel renders -- a static
architecture reveal, separate from the shadow/decision graph the chat tools
build up during a session.

context and shadowdb are thinner in reality (Decision is the only real
label in context; shadowDb's schema is just shadow copies of the other two
plus the SIMILAR_TO match). Their branches include a couple of honestly-
labeled descriptive facets (Outcome/Precedent, Shadow Entity/Similarity
Match) rather than inventing fake Neo4j labels -- called out as such in
their own description text.

All writes are MERGE-based, so this is safe to re-run.

Run from the entity-resolution/ directory:
    ./venv/bin/python scripts/seed_ontology.py
"""
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from resolver import db

DATA_PRODUCTS = [
    {
        "productId": "meridian",
        "name": "Banking Virtual Graph",
        "shortCode": "BANK",
        "backend": "Aura Virtual Graph over Databricks -- read-only, nothing copied",
        "description": (
            "Meridian Bank's own system of record: customers, accounts, credit scores, "
            "loan facilities, transactions, and relationship managers. Exposed as a live, "
            "read-only virtual graph -- the agent queries it directly over Databricks; "
            "none of it is ever copied into Neo4j."
        ),
        "color": "#2B5876",
    },
    {
        "productId": "documents",
        "name": "Business Plan Knowledge Graph",
        "shortCode": "DOCS",
        "backend": "AuraDB, built by Document Intelligence from an uploaded business plan",
        "description": (
            "The applicant's own account of their business and loan ask -- people, the "
            "organization, and the loan request itself -- extracted from an uploaded PDF "
            "into a knowledge graph. This is the applicant's narrative, not Meridian's "
            "system of record."
        ),
        "color": "#D98847",
    },
    {
        "productId": "lendingpolicy",
        "name": "Lending Policy",
        "shortCode": "PLCY",
        "backend": "AuraDB, modeled as a real policy-manual graph",
        "description": (
            "Meridian's underwriting manual as a graph: sections, citable rules (minimum "
            "credit score, DSCR, loan-to-value, delinquency checks), and the escalation "
            "path a rule triggers when it fails. A recommendation is checked against these "
            "rules by section number, not reasoned about in the abstract."
        ),
        "color": "#4FA9B8",
    },
    {
        "productId": "context",
        "name": "Decision History",
        "shortCode": "HIST",
        "backend": "AuraDB, written to at decision time",
        "description": (
            "Meridian's own record of past loan recommendations -- what was decided, why, "
            "and which policy rules drove it. Grounds new recommendations in precedent "
            "instead of reasoning about each application in isolation, and every decision "
            "made here becomes precedent for the next one."
        ),
        "color": "#7A5C99",
    },
    {
        "productId": "shadowdb",
        "name": "Resolution Layer",
        "shortCode": "RES",
        "backend": "AuraDB, the composite database's own write target",
        "description": (
            "Composite databases can't hold relationships that span constituents, and the "
            "Banking Virtual Graph is read-only -- so this is where matched entities from "
            "the banking data and the business plan get shadowed side by side and linked, "
            "the only place a cross-source connection physically exists."
        ),
        "color": "#5B6B73",
    },
]

# The real node labels each constituent's schema actually contains -- one
# SchemaEntity per label, taken straight from the MATCH clauses in
# resolver/matching.py. context and shadowdb get a couple of honestly-framed
# descriptive facets instead, since their real schema is thinner (see
# their own description text for what's real vs. descriptive).
SCHEMA_ENTITIES = [
    # -- meridian --
    {"entityId": "meridian:Customer", "productId": "meridian", "name": "Customer",
     "description": "A Meridian banking customer -- the entity every other meridian record hangs off of."},
    {"entityId": "meridian:Account", "productId": "meridian", "name": "Account",
     "description": "A deposit account a customer holds with Meridian."},
    {"entityId": "meridian:LoanFacility", "productId": "meridian", "name": "Loan Facility",
     "description": "An existing loan facility, with a payment status (Current/Delinquent) that lending-policy rules check."},
    {"entityId": "meridian:KYCStatus", "productId": "meridian", "name": "KYC Status",
     "description": "The customer's know-your-customer risk rating (Low/Medium/High)."},
    {"entityId": "meridian:CreditScore", "productId": "meridian", "name": "Credit Score",
     "description": "A dated credit-score reading, kept as history so a trend can be read, not just a single number."},
    {"entityId": "meridian:LoanApplication", "productId": "meridian", "name": "Loan Application",
     "description": "A formal application on file with Meridian -- the bank's own record of a loan ask, as opposed to the business plan's account of it."},
    {"entityId": "meridian:Transaction", "productId": "meridian", "name": "Transaction",
     "description": "One posted transaction on an account; rolled up into cash-flow summaries rather than shown individually."},
    {"entityId": "meridian:Employee", "productId": "meridian", "name": "Employee",
     "description": "A Meridian employee -- covers relationship managers assigned to a customer."},
    {"entityId": "meridian:Branch", "productId": "meridian", "name": "Branch",
     "description": "The physical branch an employee works out of."},
    # -- documents --
    {"entityId": "documents:Person", "productId": "documents", "name": "Person",
     "description": "A person named in the business plan -- an owner, officer, or other principal."},
    {"entityId": "documents:Organization", "productId": "documents", "name": "Organization",
     "description": "The applicant business itself, as described in its own business plan."},
    {"entityId": "documents:Account", "productId": "documents", "name": "Account",
     "description": "An account the business plan mentions -- matched against Meridian's own Account records."},
    {"entityId": "documents:Property", "productId": "documents", "name": "Property",
     "description": "A property named in the business plan, e.g. one a principal co-owns."},
    {"entityId": "documents:LoanRequest", "productId": "documents", "name": "Loan Request",
     "description": "The applicant's own stated ask -- amount, term, purpose, and their market/repayment rationale."},
    # -- lendingpolicy --
    {"entityId": "lendingpolicy:PolicyDocument", "productId": "lendingpolicy", "name": "Policy Document",
     "description": "The lending policy manual as a whole, with a title and version."},
    {"entityId": "lendingpolicy:PolicySection", "productId": "lendingpolicy", "name": "Policy Section",
     "description": "One numbered section of the manual (e.g. §4 Term Loans), scoped to a product type."},
    {"entityId": "lendingpolicy:ProductType", "productId": "lendingpolicy", "name": "Product Type",
     "description": "A loan product (Term Loan, SBA Loan, Line of Credit, CRE Loan, Equipment Loan)."},
    {"entityId": "lendingpolicy:PolicyRule", "productId": "lendingpolicy", "name": "Policy Rule",
     "description": "One citable underwriting rule -- a criterion, a comparison, and a threshold -- e.g. POL-001."},
    {"entityId": "lendingpolicy:EscalationPath", "productId": "lendingpolicy", "name": "Escalation Path",
     "description": "Who a rule escalates to, and under what trigger, when it fails."},
    # -- context (Decision is the anchor; Customer/PolicyRule/Escalation are
    # shadow copies of entities that live in meridian/lendingpolicy -- same
    # reasoning as shadowdb's ShadowEntity below, not references into those
    # constituents directly, since composite databases forbid that) --
    {"entityId": "context:Decision", "productId": "context", "name": "Decision",
     "description": "One per recorded loan recommendation: the recommendation, reasoning, and which policy rules applied/failed."},
    {"entityId": "context:Customer", "productId": "context", "name": "Customer",
     "description": "A shadow copy of who the decision was about -- just customerId/customerName, not a reference into meridian."},
    {"entityId": "context:PolicyRule", "productId": "context", "name": "Policy Rule",
     "description": "A shadow copy of a cited rule -- just ruleId/criterion, not a reference into lendingpolicy. Shared across every decision that ever cited it, so precedent is a real graph traversal, not a property comparison."},
    {"entityId": "context:Escalation", "productId": "context", "name": "Escalation",
     "description": "A shadow copy of the role a decision escalated to (e.g. Credit Risk Committee), shared across every decision that ever triggered it."},
    # -- shadowdb (also descriptive facets -- shadowDb's real labels are
    # just Shadow copies of documents/meridian labels, e.g. Shadow:Customer) --
    {"entityId": "shadowdb:ShadowEntity", "productId": "shadowdb", "name": "Shadow Entity",
     "description": "A :Shadow-labeled copy of one matched meridian or documents node, living here so a cross-source relationship has somewhere to physically exist."},
    {"entityId": "shadowdb:SimilarityMatch", "productId": "shadowdb", "name": "Similarity Match",
     "description": "The SIMILAR_TO relationship (and its confidence/matchType) linking two shadow entities that were matched to the same real-world thing."},
]

# Real relationship types between two labels in the SAME constituent, taken
# straight from the MATCH clauses in resolver/matching.py.
ENTITY_RELATIONSHIPS = [
    # -- meridian --
    {"fromId": "meridian:Customer", "toId": "meridian:Account", "label": "OWNS_ACCOUNT",
     "description": "A customer owns one or more accounts."},
    {"fromId": "meridian:Customer", "toId": "meridian:LoanFacility", "label": "HAS_FACILITY",
     "description": "A customer's existing loan facilities."},
    {"fromId": "meridian:Customer", "toId": "meridian:KYCStatus", "label": "HAS_KYC_STATUS",
     "description": "A customer's current KYC risk rating."},
    {"fromId": "meridian:Customer", "toId": "meridian:CreditScore", "label": "HAS_CREDIT_SCORE",
     "description": "A customer's credit-score history."},
    {"fromId": "meridian:Customer", "toId": "meridian:LoanApplication", "label": "APPLIED_FOR",
     "description": "A customer's formal loan applications on file."},
    {"fromId": "meridian:Account", "toId": "meridian:Transaction", "label": "HAS_TRANSACTION",
     "description": "Transactions posted to an account."},
    {"fromId": "meridian:Customer", "toId": "meridian:Employee", "label": "MANAGED_BY",
     "description": "The relationship manager assigned to a customer."},
    {"fromId": "meridian:Employee", "toId": "meridian:Branch", "label": "WORKS_AT",
     "description": "The branch an employee works out of."},
    {"fromId": "meridian:Customer", "toId": "meridian:Customer", "label": "HAS_PARENT",
     "description": "Corporate ownership hierarchy -- a customer's parent company, walked outward to find affiliates."},
    # -- documents --
    {"fromId": "documents:Organization", "toId": "documents:LoanRequest", "label": "REQUESTS",
     "description": "The business plan's own stated loan ask."},
    {"fromId": "documents:Person", "toId": "documents:Organization", "label": "WORKED_AT",
     "description": "A person's employment at the business."},
    {"fromId": "documents:Person", "toId": "documents:Account", "label": "AUTHORIZED_FOR",
     "description": "A person's signing authority on an account."},
    {"fromId": "documents:Person", "toId": "documents:Property", "label": "CO_OWNS",
     "description": "A person's co-ownership of a property."},
    {"fromId": "documents:Person", "toId": "documents:Organization", "label": "OWNS",
     "description": "A person's ownership stake in the business."},
    # -- lendingpolicy --
    {"fromId": "lendingpolicy:PolicyDocument", "toId": "lendingpolicy:PolicySection", "label": "HAS_SECTION",
     "description": "The manual is organized into numbered sections."},
    {"fromId": "lendingpolicy:PolicySection", "toId": "lendingpolicy:ProductType", "label": "APPLIES_TO",
     "description": "Each section is scoped to one loan product type."},
    {"fromId": "lendingpolicy:PolicySection", "toId": "lendingpolicy:PolicyRule", "label": "HAS_RULE",
     "description": "Each section contains one or more citable rules."},
    {"fromId": "lendingpolicy:PolicyRule", "toId": "lendingpolicy:EscalationPath", "label": "REQUIRES_ESCALATION",
     "description": "Some rules require escalation to a specific role when they fail."},
    # -- context --
    {"fromId": "context:Decision", "toId": "context:Customer", "label": "ABOUT",
     "description": "Which customer this decision was about."},
    {"fromId": "context:Decision", "toId": "context:PolicyRule", "label": "APPLIED_POLICY",
     "description": "Which policy rule was checked, and whether the applicant's figures failed it (failed property)."},
    {"fromId": "context:Decision", "toId": "context:Escalation", "label": "TRIGGERED",
     "description": "Which escalation path this decision required, if any."},
    {"fromId": "context:Decision", "toId": "context:Decision", "label": "PRECEDENT_FOR",
     "description": "Written automatically, not by judgment: an earlier decision that failed the same policy rule as a later one."},
    # -- shadowdb --
    {"fromId": "shadowdb:ShadowEntity", "toId": "shadowdb:SimilarityMatch", "label": "PRODUCES",
     "description": "Matching two shadow entities produces a SIMILAR_TO match linking them."},
]

# How the DataProduct hubs themselves fit together (cross-constituent).
RELATIONSHIPS = [
    {
        "fromId": "shadowdb", "toId": "meridian", "type": "RESOLVES",
        "description": (
            "Matches business-plan people/organizations against Meridian customers and "
            "accounts, then shadows the Meridian side so both can be viewed as one "
            "connected graph."
        ),
    },
    {
        "fromId": "shadowdb", "toId": "documents", "type": "RESOLVES",
        "description": "Shadows the business-plan entities so they can be linked to their matched Meridian counterparts.",
    },
    {
        "fromId": "documents", "toId": "meridian", "type": "SUPPLEMENTS",
        "description": (
            "The applicant's stated loan request and business narrative supplement -- and "
            "are checked against -- Meridian's own application, credit, and transaction "
            "records."
        ),
    },
    {
        "fromId": "lendingpolicy", "toId": "meridian", "type": "GOVERNS",
        "description": "A loan recommendation for a Meridian customer is checked against these underwriting rules, cited by section number.",
    },
    {
        "fromId": "context", "toId": "lendingpolicy", "type": "CITES",
        "description": "Every recorded decision names the policy rules that actually drove it.",
    },
    {
        "fromId": "context", "toId": "meridian", "type": "CITES",
        "description": (
            "Every recorded decision is about a specific Meridian customer, and becomes "
            "precedent the next time that customer -- or a similar loan -- comes up."
        ),
    },
]

driver = db.get_driver()
with db.get_session(driver) as session:
    session.run(
        """
        USE meridianComposite.ontology
        UNWIND $rows AS row
        MERGE (p:DataProduct {productId: row.productId})
        SET p.name = row.name, p.shortCode = row.shortCode, p.backend = row.backend,
            p.description = row.description, p.color = row.color
        """,
        rows=DATA_PRODUCTS,
    )

    session.run(
        """
        USE meridianComposite.ontology
        UNWIND $rows AS row
        MERGE (e:SchemaEntity {entityId: row.entityId})
        SET e.productId = row.productId, e.name = row.name, e.description = row.description
        """,
        rows=SCHEMA_ENTITIES,
    )

    session.run(
        """
        USE meridianComposite.ontology
        UNWIND $rows AS row
        MATCH (p:DataProduct {productId: row.productId})
        MATCH (e:SchemaEntity {entityId: row.entityId})
        MERGE (p)-[:HAS_ENTITY]->(e)
        """,
        rows=SCHEMA_ENTITIES,
    )

    session.run(
        """
        USE meridianComposite.ontology
        UNWIND $rows AS row
        MATCH (a:SchemaEntity {entityId: row.fromId})
        MATCH (b:SchemaEntity {entityId: row.toId})
        MERGE (a)-[r:RELATES {label: row.label}]->(b)
        SET r.description = row.description
        """,
        rows=ENTITY_RELATIONSHIPS,
    )

    for rel in RELATIONSHIPS:
        session.run(
            f"""
            USE meridianComposite.ontology
            MATCH (a:DataProduct {{productId: $fromId}})
            MATCH (b:DataProduct {{productId: $toId}})
            MERGE (a)-[r:{rel['type']}]->(b)
            SET r.description = $description
            """,
            fromId=rel["fromId"], toId=rel["toId"], description=rel["description"],
        )

    result = session.run(
        """
        USE meridianComposite.ontology
        MATCH (p:DataProduct)
        OPTIONAL MATCH (p)-[:HAS_ENTITY]->(e:SchemaEntity)
        RETURN p.productId AS product, count(DISTINCT e) AS entityCount
        ORDER BY product
        """
    )
    for row in result:
        print(dict(row))
driver.close()
