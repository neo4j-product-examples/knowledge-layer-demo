"""LLM tool-use loop backing the real chat: a small, curated set of tools
wrapping the same functions the earlier scripted UI called directly, so the
model picks which action to take instead of the UI hardcoding two steps."""
from resolver import graph_data, matching, shadow_nodes

SYSTEM_PROMPT = """You are an assistant embedded in a graph exploration tool for a bank analyst.

Two graphs have been resolved into a shared shadow graph:
- the "Business Plan Knowledge Graph": people/organizations/accounts extracted from a business plan document
- the "Banking Virtual Graph": Meridian Bank's own customer, account, and risk data

Use the tools available to answer the user's questions and take the actions they ask for.
Prefer calling a tool over guessing, and never invent names, IDs, or figures that a tool
didn't return. Be concise in your final answers.

If a request needs a Meridian customerId you don't already know (from an earlier tool
result in this conversation), call find_customer first to resolve one from the business
plan's entities before calling any tool that requires a customer_id."""

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


def run_get_customer_risk_profile(session, customer_id):
    kyc_rows = matching.fetch_meridian_customer_kyc(session)
    facility_rows = matching.fetch_meridian_customer_facilities(session)
    kyc = next((k for k in kyc_rows if k["customerId"] == customer_id), None)
    facilities = [f for f in facility_rows if f["customerId"] == customer_id]
    return {"customerId": customer_id, "kyc": kyc, "facilities": facilities}


def run_tool(name, tool_input, session):
    if name == "find_customer":
        return run_find_customer(session)
    if name == "find_parent_companies":
        return run_find_parent_companies(session, tool_input["customer_id"])
    if name == "get_customer_risk_profile":
        return run_get_customer_risk_profile(session, tool_input["customer_id"])
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
