import datetime
import json
import logging
import os

import anthropic
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from resolver import chat as chat_tools
from resolver import db, graph_data, matching, shadow_nodes

load_dotenv()

app = Flask(__name__)
logger = logging.getLogger(__name__)

BLOOM_URL = os.environ.get("BLOOM_URL", "")
CHAT_MODEL = os.environ.get("ANTHROPIC_CHAT_MODEL", "claude-sonnet-5")
MAX_TOOL_ITERATIONS = 6

_driver = None
_anthropic_client = None
_chat_history = []


def get_driver():
    global _driver
    if _driver is None:
        _driver = db.get_driver()
    return _driver


def get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


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
    _chat_history.clear()
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
    _chat_history.clear()
    try:
        with db.get_session(get_driver()) as session:
            document_persons = matching.fetch_document_persons(session)
            document_organizations = matching.fetch_document_organizations(session)
            document_accounts = matching.fetch_document_accounts(session)
            document_properties = matching.fetch_document_properties(session)
            document_loan_requests = matching.fetch_document_loan_requests(session)

            shadow_nodes.seed_document_shadow_nodes(
                session, document_persons, document_organizations, document_accounts, document_properties,
                document_loan_requests,
            )
            shadow_nodes.seed_document_relationships(
                session,
                matching.fetch_document_worked_at(session),
                matching.fetch_document_authorized_for(session),
                matching.fetch_document_co_owns(session),
                matching.fetch_document_ownership(session),
                document_loan_requests,
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
            result = chat_tools.run_find_customer(session)
        return jsonify({"status": "ok", "matches": result["matches"], "graph": result["graph"]})
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
            result = chat_tools.run_find_parent_companies(session, customer_id)

        related = result["relatedCompanies"]
        delinquent = result["delinquentFacilities"]
        if delinquent:
            findings = "; ".join(
                f"{d['customerName'] or d['customerId']} has a delinquent facility "
                f"{d['facilityId']} ({d['daysPastDue']} days past due)"
                for d in delinquent
            )
            summary = f"Found {len(related)} related companies in the corporate hierarchy. {findings}."
        elif related:
            names = ", ".join(r["customerName"] or r["customerId"] for r in related)
            summary = f"Found {len(related)} related companies: {names}. No delinquencies among them."
        else:
            summary = "No parent or affiliated companies found for this customer."

        return jsonify({
            "status": "ok",
            "summary": summary,
            "relatedCompanies": related,
            "graph": result["graph"],
        })
    except Exception:
        logger.exception("Failed to look up corporate hierarchy")
        return jsonify({"error": "Could not look up the corporate hierarchy."}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    """Real chat: a tool-use agent loop over the same actions the scripted
    UI used to call directly, so the model decides what to do instead of
    the UI hardcoding two fixed steps."""
    body = request.get_json(silent=True) or {}
    user_message = (body.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "message is required."}), 400
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "ANTHROPIC_API_KEY is not configured on the server."}), 500

    _chat_history.append({"role": "user", "content": user_message})
    client = get_anthropic_client()
    graph_deltas = []
    steps = []

    try:
        with db.get_session(get_driver()) as session:
            for _ in range(MAX_TOOL_ITERATIONS):
                response = client.messages.create(
                    model=CHAT_MODEL,
                    max_tokens=4096,
                    system=chat_tools.SYSTEM_PROMPT,
                    tools=chat_tools.TOOLS,
                    messages=_chat_history,
                )
                _chat_history.append({"role": "assistant", "content": response.content})

                if response.stop_reason != "tool_use":
                    final_text = "".join(
                        block.text for block in response.content if block.type == "text"
                    )
                    if not final_text.strip():
                        block_types = [block.type for block in response.content]
                        logger.warning(
                            "Model returned no text content (stop_reason=%s, block_types=%s, steps=%d)",
                            response.stop_reason, block_types, len(steps),
                        )
                        final_text = (
                            "The assistant finished its analysis but didn't return a written "
                            "summary this time -- the decision trace above shows every step it "
                            "completed. Try asking again."
                        )
                    return jsonify({
                        "status": "ok",
                        "reply": final_text,
                        "graph": chat_tools.merge_graph_deltas(graph_deltas),
                        "steps": steps,
                    })

                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    result = chat_tools.run_tool(block.name, block.input, session)
                    graph_delta = result.pop("graph", None)
                    if graph_delta:
                        graph_deltas.append(graph_delta)
                    steps.append({
                        "tool": block.name,
                        "label": chat_tools.describe_tool_call(block.name, block.input),
                        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                        # This step's own delta, so the client can reveal it on
                        # canvas in sync with narrating this step live, instead
                        # of the whole graph appearing at once at the end.
                        "graph": graph_delta or {"nodes": [], "edges": []},
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
                _chat_history.append({"role": "user", "content": tool_results})

        return jsonify({"error": "The assistant took too many steps to answer."}), 500
    except anthropic.APIError:
        logger.exception("Anthropic API error")
        return jsonify({"error": "The assistant is unavailable right now."}), 502
    except Exception:
        logger.exception("Chat request failed")
        return jsonify({"error": "Something went wrong talking to the assistant."}), 500


if __name__ == "__main__":
    app.run(debug=True)
