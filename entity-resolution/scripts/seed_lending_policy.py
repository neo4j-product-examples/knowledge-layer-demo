"""One-time seed script for the `meridianComposite.lendingpolicy` constituent
(a standalone AuraDB, aliased into the composite database -- see HANDOFF.md
for how that alias was created).

Builds the full policy-manual structure directly:

    PolicyDocument -[:HAS_SECTION]-> PolicySection -[:HAS_RULE]-> PolicyRule
    PolicySection -[:APPLIES_TO]-> ProductType
    PolicyRule -[:REQUIRES_ESCALATION]-> EscalationPath   (only on rules that need one)

All writes are MERGE-based, so this is safe to re-run against the same
instance (e.g. after editing a rule's wording below).

Run from the entity-resolution/ directory:
    ./venv/bin/python scripts/seed_lending_policy.py
"""
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from resolver import db

POLICY_DOCUMENT = {
    "title": "Meridian Bank Commercial Lending Policy Manual",
    "version": "3.2",
    "effectiveDate": "2026-01-01",
    "owner": "Credit Risk & Underwriting",
}

SECTIONS = [
    {
        "sectionNumber": "§4", "title": "Term Loans", "productTypeCode": "LN-TERM",
        "summary": "Underwriting criteria for fixed-term commercial loans used for expansion, equipment, and working capital.",
    },
    {
        "sectionNumber": "§5", "title": "SBA Loans", "productTypeCode": "LN-SBA",
        "summary": "Underwriting criteria for loans originated under SBA guarantee programs.",
    },
    {
        "sectionNumber": "§6", "title": "Lines of Credit", "productTypeCode": "LN-LOC",
        "summary": "Underwriting criteria for revolving commercial lines of credit.",
    },
    {
        "sectionNumber": "§7", "title": "Commercial Real Estate Loans", "productTypeCode": "LN-CRE",
        "summary": "Underwriting criteria for loans secured by commercial real property.",
    },
    {
        "sectionNumber": "§8", "title": "Equipment Loans", "productTypeCode": "LN-EQP",
        "summary": "Underwriting criteria for loans secured by business equipment.",
    },
]

PRODUCT_TYPES = [
    {"code": "LN-TERM", "name": "Term Loan"},
    {"code": "LN-SBA", "name": "SBA Loan"},
    {"code": "LN-LOC", "name": "Line of Credit"},
    {"code": "LN-CRE", "name": "Commercial Real Estate Loan"},
    {"code": "LN-EQP", "name": "Equipment Loan"},
]

RULES = [
    {
        "productTypeCode": "LN-TERM", "ruleId": "POL-001",
        "criterion": "Minimum Credit Score", "comparison": ">=", "threshold": 650, "unit": "score",
        "section": "§4.1",
        "description": "Applicants must maintain a business or personal credit score of at least 650 to qualify for a term loan.",
    },
    {
        "productTypeCode": "LN-TERM", "ruleId": "POL-002",
        "criterion": "Minimum Debt Service Coverage Ratio", "comparison": ">=", "threshold": 1.25, "unit": "ratio",
        "section": "§4.2",
        "description": "Projected annual net cash flow must cover the proposed loan's annual debt service by at least 1.25x.",
    },
    {
        "productTypeCode": "LN-TERM", "ruleId": "POL-003",
        "criterion": "Maximum Loan Amount to Annual Cash Flow", "comparison": "<=", "threshold": 3.5, "unit": "ratio",
        "section": "§4.3",
        "description": "The requested loan amount may not exceed 3.5x the applicant's trailing-twelve-month net cash flow.",
    },
    {
        "productTypeCode": "LN-TERM", "ruleId": "POL-004",
        "criterion": "Maximum KYC Risk Rating", "comparison": "<=", "threshold": "Medium", "unit": "rating",
        "section": "§4.4",
        "description": "Applicant's KYC risk rating must be Low or Medium; High-risk applicants require senior underwriter escalation.",
    },
    {
        "productTypeCode": "LN-TERM", "ruleId": "POL-005",
        "criterion": "No Delinquent Facility (Applicant or Affiliate)", "comparison": "=", "threshold": 0, "unit": "count",
        "section": "§4.5",
        "description": (
            "Neither the applicant nor any affiliate under common ownership may have a "
            "loan facility in Delinquent payment status at time of application. To check "
            "this, look up the applicant's corporate ownership hierarchy and check every "
            "related company's facilities, not just the applicant's own."
        ),
    },
    {
        "productTypeCode": "LN-SBA", "ruleId": "POL-006",
        "criterion": "Minimum Credit Score", "comparison": ">=", "threshold": 680, "unit": "score",
        "section": "§5.1",
        "description": "SBA loan applicants must maintain a credit score of at least 680.",
    },
    {
        "productTypeCode": "LN-SBA", "ruleId": "POL-007",
        "criterion": "Maximum Loan-to-Value", "comparison": "<=", "threshold": 90, "unit": "percent",
        "section": "§5.2",
        "description": "SBA-guaranteed loans may not exceed 90% loan-to-value on the financed asset.",
    },
    {
        "productTypeCode": "LN-LOC", "ruleId": "POL-008",
        "criterion": "Minimum Credit Score", "comparison": ">=", "threshold": 620, "unit": "score",
        "section": "§6.1",
        "description": "Line of credit applicants must maintain a credit score of at least 620.",
    },
    {
        "productTypeCode": "LN-LOC", "ruleId": "POL-009",
        "criterion": "Minimum Debt Service Coverage Ratio", "comparison": ">=", "threshold": 1.15, "unit": "ratio",
        "section": "§6.2",
        "description": "Projected net cash flow must cover the proposed facility's debt service by at least 1.15x.",
    },
    {
        "productTypeCode": "LN-CRE", "ruleId": "POL-010",
        "criterion": "Maximum Loan-to-Value", "comparison": "<=", "threshold": 80, "unit": "percent",
        "section": "§7.1",
        "description": "Commercial real estate loans may not exceed 80% loan-to-value on the underlying property.",
    },
    {
        "productTypeCode": "LN-EQP", "ruleId": "POL-011",
        "criterion": "Minimum Credit Score", "comparison": ">=", "threshold": 640, "unit": "score",
        "section": "§8.1",
        "description": "Equipment loan applicants must maintain a credit score of at least 640.",
    },
]

ESCALATIONS = [
    {
        "ruleId": "POL-004",
        "role": "Senior Underwriter",
        "trigger": "Applicant KYC risk rating is High",
        "requiredAction": "Manual escalation and senior underwriter sign-off required before proceeding.",
    },
    {
        "ruleId": "POL-005",
        "role": "Credit Risk Committee",
        "trigger": "Applicant or an affiliate under common ownership has a delinquent facility",
        "requiredAction": "Exception review by Credit Risk Committee; requires documented justification and committee approval to proceed.",
    },
]

driver = db.get_driver()
with db.get_session(driver) as session:
    session.run(
        """
        USE meridianComposite.lendingpolicy
        MERGE (d:PolicyDocument {title: $title})
        SET d += $props
        """,
        title=POLICY_DOCUMENT["title"], props=POLICY_DOCUMENT,
    )

    session.run(
        """
        USE meridianComposite.lendingpolicy
        UNWIND $rows AS row
        MERGE (p:ProductType {productTypeCode: row.code})
        SET p.productTypeName = row.name
        """,
        rows=PRODUCT_TYPES,
    )

    session.run(
        """
        USE meridianComposite.lendingpolicy
        MATCH (d:PolicyDocument {title: $docTitle})
        UNWIND $rows AS row
        MERGE (s:PolicySection {sectionNumber: row.sectionNumber})
        SET s.title = row.title, s.summary = row.summary
        MERGE (d)-[:HAS_SECTION]->(s)
        WITH s, row
        MATCH (p:ProductType {productTypeCode: row.productTypeCode})
        MERGE (s)-[:APPLIES_TO]->(p)
        """,
        docTitle=POLICY_DOCUMENT["title"], rows=SECTIONS,
    )

    session.run(
        """
        USE meridianComposite.lendingpolicy
        UNWIND $rows AS row
        MATCH (p:ProductType {productTypeCode: row.productTypeCode})
        MATCH (s:PolicySection)-[:APPLIES_TO]->(p)
        MERGE (s)-[:HAS_RULE]->(r:PolicyRule {ruleId: row.ruleId})
        SET r.criterion = row.criterion, r.comparison = row.comparison, r.threshold = row.threshold,
            r.unit = row.unit, r.section = row.section, r.description = row.description
        """,
        rows=RULES,
    )

    session.run(
        """
        USE meridianComposite.lendingpolicy
        UNWIND $rows AS row
        MATCH (r:PolicyRule {ruleId: row.ruleId})
        MERGE (r)-[:REQUIRES_ESCALATION]->(e:EscalationPath {role: row.role})
        SET e.trigger = row.trigger, e.requiredAction = row.requiredAction
        """,
        rows=ESCALATIONS,
    )

    result = session.run(
        """
        USE meridianComposite.lendingpolicy
        MATCH (d:PolicyDocument)-[:HAS_SECTION]->(s:PolicySection)-[:HAS_RULE]->(r:PolicyRule)
        OPTIONAL MATCH (r)-[:REQUIRES_ESCALATION]->(e:EscalationPath)
        RETURN s.sectionNumber AS section, count(DISTINCT r) AS rules, count(DISTINCT e) AS escalations
        ORDER BY section
        """
    )
    for row in result:
        print(dict(row))
driver.close()
