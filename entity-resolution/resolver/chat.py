"""LLM tool-use loop backing the real chat: a small, curated set of tools
wrapping the same functions the earlier scripted UI called directly, so the
model picks which action to take instead of the UI hardcoding two steps."""
import datetime

from resolver import graph_data, matching, shadow_nodes

SYSTEM_PROMPT = """You are an assistant embedded in a graph exploration tool for a bank analyst.

Two graphs have been resolved into a shared shadow graph:
- the "Business Plan Knowledge Graph": people/organizations/accounts extracted from a business plan document
- the "Banking Virtual Graph": Meridian Bank's own customer, account, and risk data

Use the tools available to answer the user's questions and take the actions they ask for.
Prefer calling a tool over guessing, and never invent names, IDs, or figures that a tool
didn't return. Be concise in your final answers.

If a request names a business (e.g. "Rosa's Bakery") rather than a Meridian customerId
you already know from earlier in this conversation, you must call find_customer FIRST,
before any other tool -- this is what connects the business plan's entities to an actual
Meridian customer record, and every other tool needs that customerId as input.

For loan-decision questions ("should we approve this loan", "what's their credit
picture look like"), pull together get_customer_risk_profile, get_customer_credit_score,
get_customer_transaction_summary, get_customer_loan_applications,
get_relationship_manager, and get_business_plan_details rather than answering
from just one of them.

For a recommendation on a specific loan (approve/decline/conditional), also call
get_lending_policy for the applicable product type (infer it from the loan application's
purpose/term -- a standard business term loan is 'LN-TERM') and check the applicant's
actual figures against each cited rule by its policy section number, rather than
reasoning about creditworthiness in the abstract. If any policy rule references
affiliates, related entities, or common ownership, you must call
find_parent_companies for this customer to check them -- do not assume the
applicant's own facilities are the only ones that rule applies to.

Your final written answer for a loan recommendation must ALWAYS include, in that
same answer, a markdown table with one row per policy rule you checked: the rule
ID, its threshold, the applicant's actual figure, and whether it passed or failed.
This table is mandatory every single time you give a recommendation, no matter how
short the rest of the answer is -- "be concise" means cut filler elsewhere, not
this table. Never write "see the table above" or point to a breakdown that isn't
present in this exact response; if you haven't actually written the table in your
answer yet, write it now before you finish.

Also call get_decision_history for the applicable product type (and this customer_id)
to check precedent -- has the bank approved, declined, or escalated similar loans
before, and why. Ground your recommendation in that history where it's relevant
(e.g. "consistent with how we handled a similar term loan for X") rather than
reasoning about this application as if it were the first one ever made.

get_decision_history returns every decision of that product type, not just
comparable ones -- a clean approval where every rule passed is NOT precedent for
a case where a rule is failing, and citing it as if it were is misleading, not
thorough. Only call a decision "precedent" for this case if it's actually
analogous: it failed (or passed) the SAME rule this case turns on, or reached the
same kind of outcome under a similar circumstance. If the tool returns unrelated
decisions, leave them out of the precedent table entirely rather than including
every result just because the tool returned it.

Whenever at least one genuinely comparable precedent exists, your final answer
must ALWAYS include, in that same answer, a markdown table listing each one:
decision ID, customer, recommendation, and the policy rule(s) that drove it
(applied and, if any, failed). Same rule as the policy-check table above -- don't
just mention a precedent in prose or point to a table that isn't in this response;
write it out, every time relevant precedent exists.

Whenever you state a specific recommendation (approve/decline/escalate/conditional)
for a specific loan, you MUST call record_decision immediately before writing your
final answer -- this is not optional and is not the same step as get_lending_policy
or get_decision_history. Call every other tool you need first, reach your
recommendation, then call record_decision with that recommendation and a concise
reasoning summary (including the policy rule IDs that actually drove it) as your
very last tool call, so it becomes part of the bank's decision history for future
questions. Only skip it for questions that don't reach a specific recommendation
(e.g. pulling up a customer's credit score with no ask about approving anything).

Of the policy rule IDs you cite in applied_rule_ids, also pass the ones the
applicant's actual figures FAILED against (not just the ones that happened to
matter) as failed_rule_ids -- e.g. if the requested amount exceeds the max
loan-to-cash-flow ratio, that rule's ID goes in failed_rule_ids, not just
applied_rule_ids. Without this, a rule the applicant failed looks identical on
the graph to one they passed, which defeats the point of showing your work.

get_business_plan_details is the applicant's own account of the loan (their stated
use of proceeds, market and repayment rationale) -- it is not Meridian's system of
record. Note where it corroborates or conflicts with Meridian's own data (the formal
application, transactions, credit history); don't treat the two as interchangeable
sources or blend them into one unsourced claim."""

TOOLS = [
    {
        "name": "find_customer",
        "description": (
            "Fuzzy-matches the currently shadowed business-plan people/organizations "
            "against Meridian Bank's own customers and accounts. Creates a SIMILAR_TO "
            "link in the shadow graph for any match found and reveals the matched "
            "Meridian node on the canvas. Call this to resolve which Meridian customer "
            "corresponds to an entity from the business plan."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "find_parent_companies",
        "description": (
            "Given a Meridian customerId, walks the corporate ownership hierarchy "
            "outward (parent companies and any sibling companies under the same "
            "ultimate parent) and flags any related company with a delinquent loan "
            "facility. Reveals the discovered companies on the canvas."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The Meridian customerId, e.g. 'C001'."},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_customer_risk_profile",
        "description": (
            "Given a Meridian customerId, returns its KYC status/risk rating and any "
            "loan facilities with their payment status. Use this to answer direct "
            "questions about one customer's risk profile."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The Meridian customerId, e.g. 'C001'."},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_customer_credit_score",
        "description": (
            "Given a Meridian customerId, returns its most recent credit score/band "
            "plus its score history over time. Use this for loan-decision questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The Meridian customerId, e.g. 'C001'."},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_customer_loan_applications",
        "description": (
            "Given a Meridian customerId, returns its loan applications (purpose, "
            "requested amount, term, rate type, and status such as Under Review/"
            "Approved/Declined/Funded/Withdrawn). Use this for loan-decision questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The Meridian customerId, e.g. 'C001'."},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_customer_transaction_summary",
        "description": (
            "Given a Meridian customerId, summarizes transaction activity across all "
            "of its accounts: transaction count, total inflow/outflow, net cash flow, "
            "a breakdown by transaction type, and the covered date range. Use this to "
            "gauge cash-flow health for loan-decision questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The Meridian customerId, e.g. 'C001'."},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_relationship_manager",
        "description": (
            "Given a Meridian customerId, returns the relationship manager (banker) "
            "already assigned to cover this customer, and the branch they work out "
            "of. Use this to check whether existing human coverage/context exists "
            "on this relationship before making a loan-decision recommendation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The Meridian customerId, e.g. 'C001'."},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_lending_policy",
        "description": (
            "Returns Meridian Bank's underwriting policy criteria for a loan product "
            "type -- e.g. minimum credit score, minimum debt service coverage ratio, "
            "maximum loan-to-cash-flow, delinquency requirements -- each with a citable "
            "policy section number. Use this for loan-decision questions so the "
            "recommendation checks the applicant's actual figures against cited bank "
            "policy instead of general reasoning."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The Meridian customerId, e.g. 'C001'."},
                "product_type_code": {
                    "type": "string",
                    "description": (
                        "One of: 'LN-TERM' (Term Loan), 'LN-SBA' (SBA Loan), "
                        "'LN-LOC' (Line of Credit), 'LN-CRE' (Commercial Real Estate Loan), "
                        "'LN-EQP' (Equipment Loan)."
                    ),
                },
            },
            "required": ["customer_id", "product_type_code"],
        },
    },
    {
        "name": "get_business_plan_details",
        "description": (
            "Returns the uploaded business plan's own account of the business "
            "(founding date, banking history/branch) and its own stated loan "
            "request (amount, term, purpose, use of proceeds, market rationale, "
            "repayment rationale) -- the applicant's side of the story, as "
            "opposed to Meridian's own systems. Use this for loan-decision "
            "questions to check the business's own narrative against the bank's "
            "records (credit score, transactions, the formal application on file)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_decision_history",
        "description": (
            "Returns past loan decisions from Meridian's decision history (the "
            "context graph) for a given product type, optionally scoped to one "
            "customer's own history. Use this for loan-decision questions to check "
            "precedent -- has the bank approved, declined, or escalated similar "
            "loans before, and why -- so a new recommendation is grounded in past "
            "decisions instead of reasoned in isolation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_type_code": {
                    "type": "string",
                    "description": (
                        "One of: 'LN-TERM' (Term Loan), 'LN-SBA' (SBA Loan), "
                        "'LN-LOC' (Line of Credit), 'LN-CRE' (Commercial Real Estate Loan), "
                        "'LN-EQP' (Equipment Loan)."
                    ),
                },
                "customer_id": {
                    "type": "string",
                    "description": "Optional: the Meridian customerId, e.g. 'C001', to also check this specific customer's own decision history.",
                },
            },
            "required": ["product_type_code"],
        },
    },
    {
        "name": "record_decision",
        "description": (
            "Persists a finished loan recommendation to Meridian's decision "
            "history (the context graph), so it becomes precedent for future "
            "loan-decision questions. Call this as your LAST tool call, once "
            "you've reached a final recommendation -- not before."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "The Meridian customerId, e.g. 'C001'."},
                "product_type_code": {
                    "type": "string",
                    "description": (
                        "One of: 'LN-TERM', 'LN-SBA', 'LN-LOC', 'LN-CRE', 'LN-EQP'."
                    ),
                },
                "requested_amount": {"type": "number", "description": "The requested loan amount."},
                "recommendation": {
                    "type": "string",
                    "description": "One of: 'Approve', 'Decline', 'Escalate', 'Conditional Approve'.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "A concise summary of why -- the key facts and policy rules that drove this recommendation.",
                },
                "applied_rule_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Policy rule IDs (e.g. 'POL-001') that were actually checked against this recommendation.",
                },
                "failed_rule_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Of applied_rule_ids, the ones the applicant's actual figures FAILED against (e.g. loan-to-cash-flow over the cap) -- not just cited or passed. This is what flags the failing rule red on the graph, so leave it out (or empty) if every applied rule passed.",
                },
                "escalation_role": {
                    "type": "string",
                    "description": "If a policy rule required escalation, the role it was escalated to (e.g. 'Senior Underwriter' or 'Credit Risk Committee'). Omit if none.",
                },
            },
            "required": ["customer_id", "product_type_code", "requested_amount", "recommendation", "reasoning"],
        },
    },
]


def run_find_customer(session):
    meridian_customers = matching.fetch_meridian_customers(session)
    meridian_accounts = matching.fetch_meridian_accounts(session)
    document_persons = matching.fetch_document_persons(session)
    document_organizations = matching.fetch_document_organizations(session)
    document_accounts = matching.fetch_document_accounts(session)

    customer_matches = matching.match_customers(meridian_customers, document_persons, document_organizations)
    account_matches = matching.match_accounts(meridian_accounts, document_accounts)

    person_lookup = {p["__id__"]: p for p in document_persons}
    org_lookup = {o["__id__"]: o for o in document_organizations}
    account_lookup = {a["__id__"]: a for a in document_accounts}

    person_matches = [m for m in customer_matches if m["documents_id"] in person_lookup]
    org_matches = [m for m in customer_matches if m["documents_id"] in org_lookup]

    shadow_nodes.apply_document_matches(session, person_matches, "Person", person_lookup)
    shadow_nodes.apply_document_matches(session, org_matches, "Organization", org_lookup)
    shadow_nodes.apply_document_matches(session, account_matches, "Account", account_lookup)

    meridian_customer_by_id = {c["customerId"]: c for c in meridian_customers}
    meridian_account_by_id = {a["accountId"]: a for a in meridian_accounts}

    all_matches = customer_matches + account_matches
    delta = graph_data.build_match_delta(all_matches, meridian_customer_by_id, meridian_account_by_id)

    matches_payload = [
        {
            "meridianId": m["meridian_id"],
            "meridianName": meridian_customer_by_id.get(m["meridian_id"], {}).get("customerName")
            or m["meridian_id"],
            "kind": "customer" if m["meridian_id"] in meridian_customer_by_id else "account",
            "matchType": m["matchType"],
            "confidence": m["confidence"],
        }
        for m in all_matches
    ]
    return {"matches": matches_payload, "graph": delta}


def run_find_parent_companies(session, customer_id):
    hierarchy_rows = graph_data.fetch_hierarchy_neighborhood(session, customer_id)
    related_ids = {customer_id} | {r["sourceId"] for r in hierarchy_rows}
    edge_rows = graph_data.fetch_hierarchy_edges(session, related_ids)

    facilities = matching.fetch_meridian_customer_facilities(session)
    delinquent_ids = {
        f["customerId"] for f in facilities
        if f.get("paymentStatus") == "Delinquent" and f["customerId"] in related_ids
    }

    delta = graph_data.build_hierarchy_delta(hierarchy_rows, edge_rows, delinquent_ids)
    name_by_id = {r["sourceId"]: r.get("customerName") or r["sourceId"] for r in hierarchy_rows}

    return {
        "relatedCompanies": [
            {"customerId": r["sourceId"], "customerName": r.get("customerName")} for r in hierarchy_rows
        ],
        "delinquentFacilities": [
            {
                "customerId": f["customerId"],
                "customerName": name_by_id.get(f["customerId"]),
                "facilityId": f["facilityId"],
                "daysPastDue": f.get("daysPastDue"),
            }
            for f in facilities
            if f["customerId"] in delinquent_ids
        ],
        "graph": delta,
    }


TOOL_STEP_LABELS = {
    "find_customer": "Finding matching Meridian customer",
    "find_parent_companies": "Finding parent companies",
    "get_customer_risk_profile": "Pulling KYC and risk profile from virtual graph",
    "get_customer_credit_score": "Pulling credit score from virtual graph",
    "get_customer_loan_applications": "Pulling loan applications from virtual graph",
    "get_customer_transaction_summary": "Pulling transactions from virtual graph",
    "get_relationship_manager": "Checking relationship-manager coverage from virtual graph",
    "get_lending_policy": "Checking lending policy",
    "get_business_plan_details": "Reading business plan for loan request details",
    "get_decision_history": "Checking decision history for precedent",
    "record_decision": "Recording decision to context graph",
}


def describe_tool_call(name, tool_input):
    """Human-readable label for one tool call, used both for the live
    "thinking" status and for its entry in the tool call trace -- this is
    the traceability layer: every step the agent took, in plain language."""
    label = TOOL_STEP_LABELS.get(name, f"Running {name}")
    tool_input = tool_input or {}
    details = [tool_input[k] for k in ("product_type_code", "customer_id") if tool_input.get(k)]
    return f"{label} ({', '.join(details)})" if details else label


def run_get_customer_risk_profile(session, customer_id):
    kyc_rows = matching.fetch_meridian_customer_kyc(session)
    facility_rows = matching.fetch_meridian_customer_facilities(session)
    kyc = next((k for k in kyc_rows if k["customerId"] == customer_id), None)
    facilities = [f for f in facility_rows if f["customerId"] == customer_id]
    graph = graph_data.build_risk_profile_delta(customer_id, kyc, facilities)
    return {"customerId": customer_id, "kyc": kyc, "facilities": facilities, "graph": graph}


def run_get_customer_credit_score(session, customer_id):
    scores = matching.fetch_meridian_customer_credit_scores(session)
    customer_scores = [s for s in scores if s["customerId"] == customer_id]
    customer_scores.sort(key=lambda s: s["scoreDate"])
    # scoreDate comes back as a neo4j.time.Date object (not JSON-serializable).
    customer_scores = [{**s, "scoreDate": str(s["scoreDate"])} for s in customer_scores]
    latest = customer_scores[-1] if customer_scores else None
    graph = graph_data.build_credit_score_delta(customer_id, latest)
    return {"customerId": customer_id, "latestScore": latest, "scoreHistory": customer_scores, "graph": graph}


def run_get_customer_loan_applications(session, customer_id):
    applications = matching.fetch_meridian_customer_loan_applications(session)
    customer_applications = [
        {**a, "applicationDate": str(a["applicationDate"])}
        for a in applications
        if a["customerId"] == customer_id
    ]
    graph = graph_data.build_loan_application_delta(customer_id, customer_applications)
    return {"customerId": customer_id, "applications": customer_applications, "graph": graph}


def run_get_customer_transaction_summary(session, customer_id):
    transactions = matching.fetch_meridian_customer_transactions(session)
    customer_transactions = [t for t in transactions if t["customerId"] == customer_id]

    inflow = sum(t["amount"] for t in customer_transactions if t["amount"] and t["amount"] > 0)
    outflow = sum(-t["amount"] for t in customer_transactions if t["amount"] and t["amount"] < 0)

    by_type = {}
    for t in customer_transactions:
        by_type[t["transactionType"]] = by_type.get(t["transactionType"], 0) + 1

    dates = [t["transactionDate"] for t in customer_transactions if t.get("transactionDate")]

    summary = {
        "customerId": customer_id,
        "transactionCount": len(customer_transactions),
        "totalInflow": round(inflow, 2),
        "totalOutflow": round(outflow, 2),
        "netCashFlow": round(inflow - outflow, 2),
        "transactionTypeBreakdown": by_type,
        "earliestDate": str(min(dates)) if dates else None,
        "latestDate": str(max(dates)) if dates else None,
    }
    summary["graph"] = graph_data.build_transaction_summary_delta(customer_id, summary)
    return summary


def run_get_relationship_manager(session, customer_id):
    managers = matching.fetch_meridian_customer_relationship_managers(session)
    branches = matching.fetch_meridian_employee_branches(session)
    branch_by_employee = {b["employeeId"]: b for b in branches}

    manager = next((m for m in managers if m["customerId"] == customer_id), None)
    relationship_manager = None
    if manager:
        branch = branch_by_employee.get(manager["employeeId"], {})
        relationship_manager = {
            "employeeId": manager["employeeId"],
            "fullName": manager["fullName"],
            "role": manager["role"],
            "branchName": branch.get("branchName"),
            "city": branch.get("city"),
            "state": branch.get("state"),
        }

    graph = graph_data.build_relationship_manager_delta(customer_id, relationship_manager)
    return {"customerId": customer_id, "relationshipManager": relationship_manager, "graph": graph}


def run_get_lending_policy(session, customer_id, product_type_code):
    rules = matching.fetch_lending_policy_rules(session, product_type_code)
    graph = graph_data.build_lending_policy_delta(customer_id, product_type_code, rules)
    return {"productTypeCode": product_type_code, "rules": rules, "graph": graph}


def run_get_business_plan_details(session):
    rows = matching.fetch_document_business_plan(session)
    if not rows:
        return {"businessPlan": None}
    row = rows[0]
    return {
        "businessPlan": {
            "organizationName": row.get("name"),
            "address": row.get("address"),
            "industry": row.get("industry"),
            "foundedDate": row.get("foundedDate"),
            "bankingRelationshipSince": row.get("bankingRelationshipSince"),
            "bankingBranch": row.get("bankingBranch"),
            "loanRequest": {
                "requestedAmount": row.get("requestedAmount"),
                "termYears": row.get("termYears"),
                "rateType": row.get("rateType"),
                "applicationId": row.get("applicationId"),
                "purpose": row.get("purpose"),
                "useOfProceeds": row.get("useOfProceeds"),
                "marketRationale": row.get("marketRationale"),
                "repaymentRationale": row.get("repaymentRationale"),
            } if row.get("requestedAmount") is not None else None,
        },
    }


def run_get_decision_history(session, product_type_code, customer_id=None):
    decisions = matching.fetch_decision_history(session, product_type_code, customer_id)
    graph = graph_data.build_decision_delta(decisions, current_customer_id=customer_id)
    return {"productTypeCode": product_type_code, "decisions": decisions, "graph": graph}


def run_record_decision(
    session, customer_id, product_type_code, requested_amount, recommendation, reasoning,
    applied_rule_ids=None, escalation_role=None, failed_rule_ids=None,
):
    customers = matching.fetch_meridian_customers(session)
    customer_name = next((c["customerName"] for c in customers if c["customerId"] == customer_id), customer_id)
    decision = {
        "decisionId": f"DEC-{customer_id}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
        "customerId": customer_id,
        "customerName": customer_name,
        "productTypeCode": product_type_code,
        "requestedAmount": requested_amount,
        "recommendation": recommendation,
        "reasoning": reasoning,
        "appliedRuleIds": applied_rule_ids or [],
        "escalationRole": escalation_role,
        "failedRuleIds": failed_rule_ids or [],
        "decidedAt": datetime.date.today().isoformat(),
    }
    matching.record_decision(session, decision)
    graph = graph_data.build_decision_delta([decision])

    if failed_rule_ids:
        # get_lending_policy only ever showed the rules that were CHECKED,
        # never the verdict -- this is what actually turns a failing rule
        # red on the canvas, in place, rather than leaving every rule
        # looking identical regardless of whether the applicant cleared it.
        all_rules = matching.fetch_lending_policy_rules(session, product_type_code)
        failed_rules = [r for r in all_rules if r["ruleId"] in failed_rule_ids]
        failure_graph = graph_data.build_policy_failure_delta(customer_id, failed_rules)
        graph = merge_graph_deltas([graph, failure_graph])

    return {"decisionId": decision["decisionId"], "recorded": True, "graph": graph}


def run_tool(name, tool_input, session):
    if name == "find_customer":
        return run_find_customer(session)
    if name == "find_parent_companies":
        return run_find_parent_companies(session, tool_input["customer_id"])
    if name == "get_customer_risk_profile":
        return run_get_customer_risk_profile(session, tool_input["customer_id"])
    if name == "get_customer_credit_score":
        return run_get_customer_credit_score(session, tool_input["customer_id"])
    if name == "get_customer_loan_applications":
        return run_get_customer_loan_applications(session, tool_input["customer_id"])
    if name == "get_customer_transaction_summary":
        return run_get_customer_transaction_summary(session, tool_input["customer_id"])
    if name == "get_lending_policy":
        return run_get_lending_policy(session, tool_input["customer_id"], tool_input["product_type_code"])
    if name == "get_relationship_manager":
        return run_get_relationship_manager(session, tool_input["customer_id"])
    if name == "get_business_plan_details":
        return run_get_business_plan_details(session)
    if name == "get_decision_history":
        return run_get_decision_history(session, tool_input["product_type_code"], tool_input.get("customer_id"))
    if name == "record_decision":
        return run_record_decision(
            session, tool_input["customer_id"], tool_input["product_type_code"],
            tool_input["requested_amount"], tool_input["recommendation"], tool_input["reasoning"],
            tool_input.get("applied_rule_ids"), tool_input.get("escalation_role"),
            tool_input.get("failed_rule_ids"),
        )
    return {"error": f"Unknown tool: {name}"}


def merge_graph_deltas(deltas):
    nodes = {}
    edges = []
    for delta in deltas:
        if not delta:
            continue
        for node in delta.get("nodes", []):
            nodes[node["id"]] = node
        edges.extend(delta.get("edges", []))
    return {"nodes": list(nodes.values()), "edges": edges}
