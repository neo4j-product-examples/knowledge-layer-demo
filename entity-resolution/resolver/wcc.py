"""Weakly Connected Components over the shadowDb resolution graph.

Tries Neo4j GDS's native gds.wcc first (fast, works if the GDS plugin is
enabled on that Aura instance). Falls back to a pure-Python union-find
over the fetched node/edge list otherwise (requirements §6) — the
union-find itself is a pure function so it's fully unit-testable without a
database.
"""

from resolver.shadow_nodes import MATCH_REL_TYPE

_FETCH_GRAPH = f"""
USE meridianComposite.shadowDb
MATCH (n:Shadow)
OPTIONAL MATCH (n)-[r:{MATCH_REL_TYPE}]-(m:Shadow)
RETURN n.sourceGraph AS sourceGraph, n.sourceId AS sourceId,
       m.sourceGraph AS otherSourceGraph, m.sourceId AS otherSourceId
"""

_GDS_PROJECT_AND_WRITE = f"""
USE meridianComposite.shadowDb
CALL gds.graph.project('shadowGraph', 'Shadow', {[MATCH_REL_TYPE]!r})
YIELD graphName
CALL gds.wcc.write('shadowGraph', {{writeProperty: 'componentId'}})
YIELD componentCount
CALL gds.graph.drop('shadowGraph') YIELD graphName AS dropped
RETURN componentCount
"""

_WRITE_COMPONENT_ID = """
USE meridianComposite.shadowDb
MATCH (n:Shadow {sourceGraph: $sourceGraph, sourceId: $sourceId})
SET n.componentId = $componentId
"""


def node_key(source_graph, source_id):
    return f"{source_graph}:{source_id}"


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def compute_components(nodes, edges):
    """nodes: list of (sourceGraph, sourceId) tuples.
    edges: list of ((sourceGraph, sourceId), (sourceGraph, sourceId)) tuples.
    Returns dict: node_key -> componentId (int, stable ordering by first
    appearance)."""
    uf = UnionFind()
    for n in nodes:
        uf.find(node_key(*n))
    for a, b in edges:
        uf.union(node_key(*a), node_key(*b))

    roots = {}
    result = {}
    for n in nodes:
        key = node_key(*n)
        root = uf.find(key)
        if root not in roots:
            roots[root] = len(roots)
        result[key] = roots[root]
    return result


def try_gds_wcc(session):
    """Returns True if GDS ran successfully, False if GDS is unavailable.

    Must force the result to be consumed: Bolt defers actual query
    execution to the PULL step, so an unconsumed session.run() never raises
    even if the procedure doesn't exist on this instance."""
    try:
        list(session.run(_GDS_PROJECT_AND_WRITE))
        return True
    except Exception:
        return False


def run_wcc(session):
    if try_gds_wcc(session):
        return

    result = session.run(_FETCH_GRAPH)
    nodes = set()
    edges = []
    for record in result:
        n = (record["sourceGraph"], record["sourceId"])
        nodes.add(n)
        if record["otherSourceGraph"] is not None:
            m = (record["otherSourceGraph"], record["otherSourceId"])
            nodes.add(m)
            edges.append((n, m))

    components = compute_components(list(nodes), edges)

    for (source_graph, source_id) in nodes:
        key = node_key(source_graph, source_id)
        session.run(
            _WRITE_COMPONENT_ID,
            sourceGraph=source_graph,
            sourceId=source_id,
            componentId=components[key],
        )
