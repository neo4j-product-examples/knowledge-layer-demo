"""One-time seed script for the `meridianComposite.context` constituent (a
standalone AuraDB, aliased into the composite database -- see HANDOFF.md
for how that alias was created).

Populates it with a handful of historical loan decisions for other Meridian
customers, so `get_decision_history` has real precedent to find on day one
instead of an empty graph. Rosa's Bakery's own decision is written at
runtime by the `record_decision` chat tool, not by this script.

    (:Decision {decisionId, customerId, customerName, productTypeCode,
                requestedAmount, recommendation, reasoning, appliedRuleIds,
                failedRuleIds, escalationRole, decidedAt})
        -[:ABOUT]-> (:Customer {customerId, customerName})
        -[:APPLIED_POLICY {failed}]-> (:PolicyRule {ruleId, criterion})

Composite databases forbid relationships that span constituents, so the
Customer and PolicyRule nodes above are lightweight shadow copies living
inside `context` itself (same pattern used for shadowDb), not references
into meridian or lendingpolicy directly -- but the ABOUT and APPLIED_POLICY
edges themselves are real, native relationships, not just properties. The
app also still draws a visual link at render time for its own graph pane
(see graph_data.build_decision_delta); that's a separate, UI-only concern
from the persisted schema here.

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
        "failedRuleIds": ["POL-006"],
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
        "failedRuleIds": [],
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
        "failedRuleIds": ["POL-005"],
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
        "failedRuleIds": [],
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
        "failedRuleIds": [],
        "escalationRole": None,
        "decidedAt": "2026-05-14",
    },
    {
        "decisionId": "DEC-C009-SEED",
        "customerId": "C009",
        "customerName": "Cannon, Anderson and Alvarez",
        "productTypeCode": "LN-TERM",
        "requestedAmount": 450000,
        "recommendation": "Decline",
        "reasoning": (
            "Credit score 701 and KYC risk rating Low both cleared policy "
            "(POL-001, POL-004), but the requested $450,000 came in at roughly "
            "4.1x trailing annual net cash flow, over the 3.5x loan-to-cash-flow "
            "cap (POL-003). Declined as structured; invited to reapply at an "
            "amount consistent with the cap."
        ),
        "appliedRuleIds": ["POL-001", "POL-003", "POL-004"],
        "failedRuleIds": ["POL-003"],
        "escalationRole": None,
        "decidedAt": "2026-04-10",
    },
    {
        "decisionId": "DEC-C010-SEED",
        "customerId": "C010",
        "customerName": "Santos, Kim and Holmes",
        "productTypeCode": "LN-TERM",
        "requestedAmount": 380000,
        "recommendation": "Approve",
        "reasoning": (
            "Credit score 735 (Good), DSCR 1.38x (>= 1.25, POL-002), "
            "loan-to-cash-flow 2.6x (<= 3.5, POL-003). KYC risk rating Low, "
            "no delinquent facilities on the applicant or any affiliate. "
            "Approved as requested."
        ),
        "appliedRuleIds": ["POL-001", "POL-002", "POL-003", "POL-004", "POL-005"],
        "failedRuleIds": [],
        "escalationRole": None,
        "decidedAt": "2026-04-25",
    },
]

driver = db.get_driver()
with db.get_session(driver) as session:
    # DEC-C002-SEED (Alvarez Distribution Co, Approve) was retired -- Alvarez
    # is the delinquent affiliate in Rosa's own case, and a clean historical
    # approval for that same company read as a contradiction. MERGE only
    # adds/updates, so it has to be deleted explicitly.
    session.run(
        """
        USE meridianComposite.context
        MATCH (d:Decision {decisionId: 'DEC-C002-SEED'})
        DETACH DELETE d
        """
    )

    session.run(
        """
        USE meridianComposite.context
        UNWIND $rows AS row
        MERGE (d:Decision {decisionId: row.decisionId})
        SET d.customerId = row.customerId, d.customerName = row.customerName,
            d.productTypeCode = row.productTypeCode, d.requestedAmount = row.requestedAmount,
            d.recommendation = row.recommendation, d.reasoning = row.reasoning,
            d.appliedRuleIds = row.appliedRuleIds, d.escalationRole = row.escalationRole,
            d.failedRuleIds = row.failedRuleIds, d.decidedAt = row.decidedAt
        MERGE (c:Customer {customerId: row.customerId})
        SET c.customerName = row.customerName
        MERGE (d)-[:ABOUT]->(c)
        """,
        rows=DECISIONS,
    )

    # Real APPLIED_POLICY edges to shadow PolicyRule nodes living inside
    # `context` itself (same shadow-node pattern used for shadowDb) --
    # composite databases forbid relationships that cross into the
    # separate lendingpolicy constituent, so this is a lightweight copy
    # (just ruleId + criterion), not a reference into it directly. Pull
    # the real criterion text from lendingpolicy so these shadow nodes
    # aren't just bare rule IDs.
    rule_rows = session.run(
        """
        USE meridianComposite.lendingpolicy
        MATCH (r:PolicyRule)
        RETURN r.ruleId AS ruleId, r.criterion AS criterion
        """
    )
    criterion_by_rule_id = {row["ruleId"]: row["criterion"] for row in rule_rows}

    applied_policy_rows = [
        {
            "decisionId": decision["decisionId"],
            "ruleId": rule_id,
            "criterion": criterion_by_rule_id.get(rule_id, rule_id),
            "failed": rule_id in decision["failedRuleIds"],
        }
        for decision in DECISIONS
        for rule_id in decision["appliedRuleIds"]
    ]
    session.run(
        """
        USE meridianComposite.context
        UNWIND $rows AS row
        MATCH (d:Decision {decisionId: row.decisionId})
        MERGE (r:PolicyRule {ruleId: row.ruleId})
        SET r.criterion = row.criterion
        MERGE (d)-[rel:APPLIED_POLICY]->(r)
        SET rel.failed = row.failed
        """,
        rows=applied_policy_rows,
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
