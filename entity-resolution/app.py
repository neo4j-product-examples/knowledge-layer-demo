import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from resolver import db, graph_data, matching, shadow_nodes, wcc

load_dotenv()

app = Flask(__name__)
logger = logging.getLogger(__name__)

BLOOM_URL = os.environ.get("BLOOM_URL", "")

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = db.get_driver()
    return _driver


def ensure_meridian_seeded():
    """Idempotent: seeds shadowDb with Meridian shadow nodes if missing
    (requirements §5.1, §7.1)."""
    with db.get_session(get_driver()) as session:
        if not shadow_nodes.meridian_shadow_nodes_exist(session):
            customers = matching.fetch_meridian_customers(session)
            accounts = matching.fetch_meridian_accounts(session)
            shadow_nodes.seed_meridian_shadow_nodes(session, customers, accounts)

        # MERGE-based and cheap, so it's safe (and necessary) to re-run this
        # even when the node seeding above was skipped as already-done.
        ownership_edges = matching.fetch_meridian_account_ownership(session)
        shadow_nodes.seed_meridian_account_ownership(session, ownership_edges)

        hierarchy_edges = matching.fetch_meridian_customer_hierarchy(session)
        shadow_nodes.seed_meridian_customer_hierarchy(session, hierarchy_edges)


@app.route("/")
def index():
    try:
        ensure_meridian_seeded()
        with db.get_session(get_driver()) as session:
            shadow_nodes.clear_document_shadow_data(session)
    except Exception:
        logger.exception("Failed to seed Meridian shadow nodes")
        return render_template("index.html", error=(
            "Could not reach the composite database to seed shadow nodes. "
            "Check that the meridianComposite DBMS is running."
        ), bloom_url=BLOOM_URL)
    return render_template("index.html", error=None, bloom_url=BLOOM_URL)


@app.route("/api/graph")
def api_graph():
    try:
        with db.get_session(get_driver()) as session:
            graph = graph_data.fetch_graph_json(session)
        return jsonify(graph)
    except Exception:
        logger.exception("Failed to fetch shadow graph")
        return jsonify({"error": "Could not fetch graph data from shadowDb."}), 500


@app.route("/api/upload-business-plan", methods=["POST"])
def upload_business_plan():
    """Shadows the documents graph's entities/relationships (already
    extracted from the business plan into the `documents` Neo4j graph) and
    returns just that documents-only slice for the initial canvas view."""
    try:
        with db.get_session(get_driver()) as session:
            document_persons = matching.fetch_document_persons(session)
            document_organizations = matching.fetch_document_organizations(session)
            document_accounts = matching.fetch_document_accounts(session)
            document_properties = matching.fetch_document_properties(session)

            shadow_nodes.seed_document_shadow_nodes(
                session, document_persons, document_organizations, document_accounts, document_properties
            )
            shadow_nodes.seed_document_relationships(
                session,
                matching.fetch_document_worked_at(session),
                matching.fetch_document_authorized_for(session),
                matching.fetch_document_co_owns(session),
                matching.fetch_document_ownership(session),
            )

            graph = graph_data.fetch_documents_graph_json(session)

        return jsonify({
            "status": "ok",
            "personCount": len(document_persons),
            "organizationCount": len(document_organizations),
            "accountCount": len(document_accounts),
            "propertyCount": len(document_properties),
            "graph": graph,
        })
    except Exception:
        logger.exception("Failed to shadow documents graph")
        return jsonify({"error": "Could not shadow the documents graph."}), 500


@app.route("/api/find-customer", methods=["POST"])
def find_customer():
    """Fuzzy-matches the shadowed documents entities against meridian
    Customers/Accounts and shadows any matches found as SIMILAR_TO edges."""
    try:
        with db.get_session(get_driver()) as session:
            meridian_customers = matching.fetch_meridian_customers(session)
            meridian_accounts = matching.fetch_meridian_accounts(session)
            document_persons = matching.fetch_document_persons(session)
            document_organizations = matching.fetch_document_organizations(session)
            document_accounts = matching.fetch_document_accounts(session)

            customer_matches = matching.match_customers(
                meridian_customers, document_persons, document_organizations
            )
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

        return jsonify({"status": "ok", "matches": matches_payload, "graph": delta})
    except Exception:
        logger.exception("Failed to run customer matching")
        return jsonify({"error": "Could not run customer matching."}), 500


@app.route("/api/find-parent-companies", methods=["POST"])
def find_parent_companies():
    """Walks the (already-shadowed) corporate ownership hierarchy outward
    from a customer and flags any related company with a delinquent
    facility — the hidden connection a shallow join would miss."""
    body = request.get_json(silent=True) or {}
    customer_id = body.get("customerId")
    if not customer_id:
        return jsonify({"error": "customerId is required."}), 400

    try:
        with db.get_session(get_driver()) as session:
            hierarchy_rows = graph_data.fetch_hierarchy_neighborhood(session, customer_id)
            related_ids = {customer_id} | {r["sourceId"] for r in hierarchy_rows}
            edge_rows = graph_data.fetch_hierarchy_edges(session, related_ids)

            facilities = matching.fetch_meridian_customer_facilities(session)
            delinquent_ids = {
                f["customerId"] for f in facilities
                if f.get("paymentStatus") == "Delinquent" and f["customerId"] in related_ids
            }

            delta = graph_data.build_hierarchy_delta(hierarchy_rows, edge_rows, delinquent_ids)

            wcc.run_wcc(session)

        name_by_id = {r["sourceId"]: r.get("customerName") or r["sourceId"] for r in hierarchy_rows}
        delinquent_facilities = [
            f for f in facilities
            if f["customerId"] in delinquent_ids
        ]

        if delinquent_facilities:
            findings = "; ".join(
                f"{name_by_id.get(f['customerId'], f['customerId'])} has a delinquent facility "
                f"{f['facilityId']} ({f.get('daysPastDue')} days past due)"
                for f in delinquent_facilities
            )
            summary = f"Found {len(hierarchy_rows)} related companies in the corporate hierarchy. {findings}."
        elif hierarchy_rows:
            names = ", ".join(name_by_id.values())
            summary = f"Found {len(hierarchy_rows)} related companies: {names}. No delinquencies among them."
        else:
            summary = "No parent or affiliated companies found for this customer."

        return jsonify({
            "status": "ok",
            "summary": summary,
            "relatedCompanies": hierarchy_rows,
            "graph": delta,
        })
    except Exception:
        logger.exception("Failed to look up corporate hierarchy")
        return jsonify({"error": "Could not look up the corporate hierarchy."}), 500


if __name__ == "__main__":
    app.run(debug=True)
