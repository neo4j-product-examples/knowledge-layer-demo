import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

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


@app.route("/process", methods=["POST"])
def process():
    """Runs the document-side matching + shadow-node + WCC pipeline
    (requirements §5.2, §6, §7.2-7.4)."""
    try:
        with db.get_session(get_driver()) as session:
            meridian_customers = matching.fetch_meridian_customers(session)
            document_persons = matching.fetch_document_persons(session)
            document_organizations = matching.fetch_document_organizations(session)
            meridian_accounts = matching.fetch_meridian_accounts(session)
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

            wcc.run_wcc(session)

        return jsonify({
            "status": "ok",
            "customerMatches": len(customer_matches),
            "accountMatches": len(account_matches),
        })
    except Exception:
        logger.exception("Failed to run entity resolution pipeline")
        return jsonify({"error": "Entity resolution pipeline failed. See server logs."}), 500


if __name__ == "__main__":
    app.run(debug=True)
