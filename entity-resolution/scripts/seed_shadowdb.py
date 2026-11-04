"""One-time seed script for `meridianComposite.shadowDb`'s meridian-side
identity nodes (a standalone AuraDB, aliased into the composite database --
see HANDOFF.md for how that alias was created).

Writes a lightweight `:Shadow:Customer` copy of every `meridian.Customer`
-- just sourceGraph/sourceId/name, enough to identify the real node and
hang a SIMILAR_TO match off of. The full record (accounts owned, corporate
hierarchy, etc.) stays in meridian itself and is read live by
resolver.graph_data when the canvas needs it; nothing structural is
copied in here.

`meridian.Account` was shadowed here too at one point, but documents never
actually has Account nodes in this demo's data, so account matching never
produced anything -- it only ever added orphaned nodes to shadowDb. See
the shadowdb-simplification commits.

Deliberately NOT run from the Flask app on every page load -- that's what
used to cause stale data to keep reappearing in shadowDb: any old copy of
the app pointed at this same shared database would silently re-derive and
re-write it on every request. Run this script by hand instead, once, or
whenever meridian's customer/account list actually changes.

All writes are MERGE-based on (sourceGraph, sourceId), so this is safe to
re-run.

Run from the entity-resolution/ directory:
    ./venv/bin/python scripts/seed_shadowdb.py
"""
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from resolver import db, matching, shadow_nodes

driver = db.get_driver()
with db.get_session(driver) as session:
    customers = matching.fetch_meridian_customers(session)
    shadow_nodes.seed_meridian_shadow_nodes(session, customers)
    print(f"Seeded {len(customers)} Customer shadow nodes.")
driver.close()
