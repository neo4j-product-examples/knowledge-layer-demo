import datetime
import json
import logging
import os
import time

import anthropic
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from resolver import chat as chat_tools
from resolver import db, graph_data, matching, ontology, shadow_nodes

load_dotenv()

app = Flask(__name__)
logger = logging.getLogger(__name__)

BLOOM_URL = os.environ.get("BLOOM_URL", "")
CHAT_MODEL = os.environ.get("ANTHROPIC_CHAT_MODEL", "claude-sonnet-5")
MAX_TOOL_ITERATIONS = 9
# get_decision_history now depends on get_lending_policy's result (it needs
# to know which rules failed), so it can no longer batch into an earlier,
# independent round -- that's one more required round-trip than before,
# and the risk/credit bundle sometimes doesn't fully batch either.
# The whole demo is built around this one applicant -- reset her own
# recorded decision on every page load so one run's recommendation never
# carries over into the next (see index()). Seeded historical decisions for
# other customers are permanent precedent and are left alone.
ROSA_CUSTOMER_ID = "C001"

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
        # Default timeout is 10 minutes -- a stalled streaming connection
        # would otherwise hang the whole (single-threaded dev server)
        # request silently for that long before the SDK gives up and lets
        # our except block turn it into a normal "error" SSE event.
        _anthropic_client = anthropic.Anthropic(timeout=60.0)
    return _anthropic_client


def ensure_meridian_seeded():
    """Idempotent: seeds shadowDb with Nordtell shadow nodes if missing
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
            matching.clear_customer_decisions(session, ROSA_CUSTOMER_ID)
    except Exception:
        logger.exception("Failed to seed Nordtell shadow nodes")
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


@app.route("/api/ontology")
def api_ontology():
    """Static architecture reveal for the "View Ontology" panel: how the
    composite database's real constituents fit together. Separate from
    api_graph -- this doesn't change during a session, so the frontend
    fetches it once and caches it."""
    try:
        with db.get_session(get_driver()) as session:
            graph = ontology.fetch_ontology_graph(session)
        return jsonify(graph)
    except Exception:
        logger.exception("Failed to fetch ontology graph")
        return jsonify({"error": "Could not fetch the ontology graph."}), 500


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


def _sse_event(payload):
    return f"data: {json.dumps(payload)}\n\n"


@app.route("/api/chat", methods=["POST"])
def chat():
    """Real chat: a tool-use agent loop over the same actions the scripted
    UI used to call directly, so the model decides what to do instead of
    the UI hardcoding two fixed steps.

    Streams as Server-Sent Events so each tool result reaches the client
    the instant it actually completes -- the graph/tool-call-trace update in
    real time during the ~10-15s of tool calls. The model's own text is
    also streamed token-by-token as it's generated (via client.messages.
    stream()/text_stream), not sent as one blob at the end -- a
    thinking-heavy final round can take 10-20s+ on its own, and that's
    dead air unless the answer is visibly typing out during it."""
    body = request.get_json(silent=True) or {}
    user_message = (body.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "message is required."}), 400
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "ANTHROPIC_API_KEY is not configured on the server."}), 500

    _chat_history.append({"role": "user", "content": user_message})
    client = get_anthropic_client()

    def generate():
        graph_deltas = []
        step_count = 0
        try:
            with db.get_session(get_driver()) as session:
                for _ in range(MAX_TOOL_ITERATIONS):
                    with client.messages.stream(
                        model=CHAT_MODEL,
                        # A round's adaptive-thinking tokens count against
                        # this budget too -- a heavy-thinking round
                        # drafting a full record_decision reasoning string
                        # can blow past 4096 combined and get cut off
                        # mid-tool-call (stop_reason="max_tokens" with no
                        # completed text or tool_use block to act on).
                        max_tokens=8192,
                        system=chat_tools.SYSTEM_PROMPT,
                        tools=chat_tools.TOOLS,
                        messages=_chat_history,
                    ) as stream:
                        for text in stream.text_stream:
                            yield _sse_event({"type": "text_delta", "text": text})
                        response = stream.get_final_message()
                    _chat_history.append({"role": "assistant", "content": response.content})

                    if response.stop_reason != "tool_use":
                        final_text = "".join(
                            block.text for block in response.content if block.type == "text"
                        )
                        if not final_text.strip():
                            block_types = [block.type for block in response.content]
                            logger.warning(
                                "Model returned no text content (stop_reason=%s, block_types=%s, steps=%d)",
                                response.stop_reason, block_types, step_count,
                            )
                            final_text = (
                                "The assistant finished its analysis but didn't return a written "
                                "summary this time -- the tool call trace above shows every step it "
                                "completed. Try asking again."
                            )
                        yield _sse_event({
                            "type": "done",
                            "reply": final_text,
                            "graph": chat_tools.merge_graph_deltas(graph_deltas),
                        })
                        return

                    tool_results = []
                    for block in response.content:
                        if block.type != "tool_use":
                            continue
                        result = chat_tools.run_tool(block.name, block.input, session)
                        # graphSteps (currently only record_decision) is an
                        # ordered list of small deltas meant to be revealed
                        # one at a time -- e.g. the real precedent chain,
                        # hop by hop -- instead of landing in one frame.
                        # Neither field goes to Claude: pop both before the
                        # result is JSON-encoded into the tool_result below.
                        graph_steps = result.pop("graphSteps", None) or []
                        graph_delta = result.pop("graph", None)
                        all_deltas = ([graph_delta] if graph_delta else []) + [s["graph"] for s in graph_steps]
                        if all_deltas:
                            graph_deltas.append(chat_tools.merge_graph_deltas(all_deltas))
                        step_count += 1
                        # Sent the instant this tool call actually finishes,
                        # not batched up for later -- this is the real-time
                        # progress the client renders live.
                        if graph_steps:
                            if graph_delta and (graph_delta.get("nodes") or graph_delta.get("edges")):
                                yield _sse_event({
                                    "type": "step",
                                    "tool": block.name,
                                    "label": chat_tools.describe_tool_call(block.name, block.input),
                                    "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                                    "graph": graph_delta,
                                })
                            for i, step in enumerate(graph_steps):
                                yield _sse_event({
                                    "type": "step",
                                    "tool": block.name,
                                    "label": step["label"],
                                    "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                                    "graph": step["graph"],
                                })
                                if i < len(graph_steps) - 1:
                                    time.sleep(0.4)
                        else:
                            yield _sse_event({
                                "type": "step",
                                "tool": block.name,
                                "label": chat_tools.describe_tool_call(block.name, block.input),
                                "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                                "graph": graph_delta or {"nodes": [], "edges": []},
                            })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })
                    _chat_history.append({"role": "user", "content": tool_results})

            yield _sse_event({"type": "error", "error": "The assistant took too many steps to answer."})
        except anthropic.APIError:
            logger.exception("Anthropic API error")
            yield _sse_event({"type": "error", "error": "The assistant is unavailable right now."})
        except Exception:
            logger.exception("Chat request failed")
            yield _sse_event({"type": "error", "error": "Something went wrong talking to the assistant."})

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=True)
