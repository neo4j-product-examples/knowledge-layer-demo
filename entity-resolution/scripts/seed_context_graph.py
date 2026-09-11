"""One-time seed script for the `meridianComposite.context` constituent (a
standalone AuraDB, aliased into the composite database -- see HANDOFF.md
for how that alias was created).

Populates it with a handful of historical loan decisions for other Meridian
customers, so `get_decision_history` has real precedent to find on day one
instead of an empty graph. Rosa's Bakery's own decision is written at
runtime by the `record_decision` chat tool, not by this script.

    (:Decision {decisionId, customerId, customerName, productTypeCode,
                requestedAmount, recommendation, reasoning, appliedRuleIds,
                escalationRole, decidedAt})

No native relationship to the customer -- composite databases forbid
relationships that span constituents, so customerId/customerName are just
properties here; the app draws the visual link to a Customer stub node at
render time (see graph_data.build_decision_delta).

All writes are MERGE-based on decisionId, so this is safe to re-run.

Run from the entity-resolution/ directory:
    ./venv/bin/python scripts/seed_context_graph.py
"""
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from resolver import db

DECISIONS = [
    {
        "decisionId": "DEC-C002-SEED",
        "customerId": "C002",
        "customerName": "Alvarez Distribution Co",
        "productTypeCode": "LN-TERM",
        "requestedAmount": 150000,
        "recommendation": "Approve",
        "reasoning": (
            "Credit score 712 (>= 650, POL-001), DSCR 1.41x (>= 1.25, POL-002), "
            "loan-to-cash-flow 2.1x (<= 3.5, POL-003). KYC risk rating Low. No "
            "delinquent facilities on the applicant or any affiliate."
        ),
        "appliedRuleIds": ["POL-001", "POL-002", "POL-003"],
        "escalationRole": None,
        "decidedAt": "2025-11-03",
    },
    {
        "decisionId": "DEC-C003-SEED",
        "customerId": "C003",
        "customerName": "Watts, Robinson and Nguyen",
        "productTypeCode": "LN-SBA",
        "requestedAmount": 320000,
        "recommendation": "Decline",
        "reasoning": (
            "Credit score 641, below the 680 minimum for SBA loans (POL-006). "
            "No further criteria evaluated once the credit-score threshold failed."
        ),
        "appliedRuleIds": ["POL-006"],
        "escalationRole": None,
        "decidedAt": "2025-12-11",
    },
    {
        "decisionId": "DEC-C004-SEED",
        "customerId": "C004",
        "customerName": "Edwards, Rios and Foster",
        "productTypeCode": "LN-LOC",
        "requestedAmount": 90000,
        "recommendation": "Approve",
        "reasoning": (
            "Credit score 668 (>= 620, POL-008), DSCR 1.22x (>= 1.15, POL-009). "
            "Line of credit sized conservatively relative to trailing cash flow."
        ),
        "appliedRuleIds": ["POL-008", "POL-009"],
        "escalationRole": None,
        "decidedAt": "2026-01-22",
    },
    {
        "decisionId": "DEC-C005-SEED",
        "customerId": "C005",
        "customerName": "Snyder, Campos and Callahan",
        "productTypeCode": "LN-TERM",
        "requestedAmount": 500000,
        "recommendation": "Escalate",
        "reasoning": (
            "Applicant's own credit score and DSCR clear POL-001/POL-002, but a "
            "sibling company under common ownership was found delinquent on an "
            "existing facility (POL-005) -- escalated to Credit Risk Committee "
            "for exception review rather than declined outright, given the "
            "applicant's own standing."
        ),
        "appliedRuleIds": ["POL-001", "POL-002", "POL-005"],
        "escalationRole": "Credit Risk Committee",
        "decidedAt": "2026-02-18",
    },
    {
        "decisionId": "DEC-C006-SEED",
        "customerId": "C006",
        "customerName": "Rice-Maddox",
        "productTypeCode": "LN-CRE",
        "requestedAmount": 1200000,
        "recommendation": "Approve",
        "reasoning": (
            "Loan-to-value 72% on the underlying property, within the 80% maximum "
            "for commercial real estate loans (POL-010)."
        ),
        "appliedRuleIds": ["POL-010"],
        "escalationRole": None,
        "decidedAt": "2026-03-30",
    },
    {
        "decisionId": "DEC-C007-SEED",
        "customerId": "C007",
        "customerName": "Chavez Ltd",
        "productTypeCode": "LN-EQP",
        "requestedAmount": 60000,
        "recommendation": "Conditional Approve",
        "reasoning": (
            "Credit score 646, just above the 640 minimum for equipment loans "
            "(POL-011). Approved conditional on the equipment purchase invoice "
            "being provided before disbursement."
        ),
        "appliedRuleIds": ["POL-011"],
        "escalationRole": None,
        "decidedAt": "2026-05-14",
    },
]

driver = db.get_driver()
with db.get_session(driver) as session:
    session.run(
        """
        USE meridianComposite.context
        UNWIND $rows AS row
        MERGE (d:Decision {decisionId: row.decisionId})
        SET d.customerId = row.customerId, d.customerName = row.customerName,
            d.productTypeCode = row.productTypeCode, d.requestedAmount = row.requestedAmount,
            d.recommendation = row.recommendation, d.reasoning = row.reasoning,
            d.appliedRuleIds = row.appliedRuleIds, d.escalationRole = row.escalationRole,
            d.decidedAt = row.decidedAt
        """,
        rows=DECISIONS,
    )

    result = session.run(
        """
        USE meridianComposite.context
        MATCH (d:Decision)
        RETURN d.productTypeCode AS productType, d.recommendation AS recommendation, count(*) AS count
        ORDER BY productType
        """
    )
    for row in result:
        print(dict(row))
driver.close()
