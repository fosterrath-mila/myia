"""Dead data elimination."""


from collections import defaultdict

from ..abstract import (
    DEAD,
    AbstractError,
    AbstractFunction,
    GraphFunction,
    PartialApplication,
    PrimitiveFunction,
    TypedPrimitive,
)
from ..graph_utils import dfs
from ..ir import Constant, Graph, succ_incoming
from ..prim import ops as P
from ..utils import Partializable


def _flatten_call(fn):

    if isinstance(fn, PartialApplication):
        return (*_flatten_call(fn.fn), *fn.args)

    elif isinstance(fn, GraphFunction):
        return (fn.graph,)

    elif isinstance(fn, (PrimitiveFunction, TypedPrimitive)):
        return (fn.prim,)

    else:
        raise AssertionError(f'Unsupported: {fn}')


def _graphs_from(calls):
    return [x[0] for x in calls]


def _subslices(seq):
    for i in range(len(seq)):
        yield seq[:-i] if i else seq


class DeadDataElimination(Partializable):
    """Eliminate expressions that compute unretrieved data."""

    def __init__(self, resources=None):
        """Initialize a DeadDataElimination."""
        self.resources = resources

    def output_structure(self, graph):
        """Yield the output structure for the graph.

        Generates entries with the form:
            path, (node, index)

        Where path is a tuple of int/SymbolicKey that can index
        the output of the graph. The empty path represents the
        return value itself.
        """
        def collect(node, path):
            if node.is_apply(P.make_tuple):
                for i, inp in enumerate(node.inputs[1:]):
                    p = (*path, i)
                    yield p, (node, i + 1)
                    yield from collect(inp, p)
            elif node.is_apply(P.env_setitem):
                _, env, key, value = node.inputs
                p = (*path, key.value)
                yield from collect(env, path)
                yield p, (node, 3)
                yield from collect(value, p)
            else:
                pass
        yield (), (graph.return_, 1)
        yield from collect(graph.output, ())

    def node_to_paths(self, root):
        """Maps each node to possible accesses.

        Returns {node: [(graph, *path), ...]}

        Meaning that node is computed as graph(...)[*path]. Note that the
        relation is not transitive here, the transitive relation is computed by
        self.dependencies.
        """
        mng = root.manager
        mng.keep_roots(root)

        finished = defaultdict(list)
        cache = {}

        def finish(node, deps):
            start, *path = deps
            finished[node] += [(fn, *path) for fn in start]

        def access_path(node):

            if node in cache:
                return cache[node]

            if node.is_apply(P.tuple_getitem):
                _, x, key = node.inputs
                rval = (*access_path(x), key.value)

            elif node.is_apply(P.env_getitem):
                _, x, key, _ = node.inputs
                rval = (*access_path(x), key.value)

            elif node.is_apply():
                for inp in node.inputs:
                    finish(inp, access_path(inp))

                fn, *args = node.inputs
                args = [a.abstract for a in args]
                fna = fn.abstract
                assert isinstance(fna, AbstractFunction)

                calls = [_flatten_call(f) for f in fna.get_sync()]

                rval = []

                for f, *args1 in calls:
                    if f is P.array_map:
                        f = (*args1, *args)[0]
                        calls = [_flatten_call(f2) for f2 in f.get_sync()]
                        finish(node, (_graphs_from(calls),))
                    elif isinstance(f, Graph):
                        rval.append(f)

                rval = (tuple(rval),)

            else:
                rval = ((),)

            cache[node] = rval
            return rval

        for node in mng.all_nodes:
            access_path(node)

        return finished

    def dependencies(self, root):
        """Return dependencies for each graph and output path.

        Returns {graph: {path: [(graph2, *path2), ...], ...}, ...}

        Meaning that computing graph(...)[*path] may require computing
        graph2(...)[*path2].
        """
        results = {}
        paths = self.node_to_paths(root)

        for g in root.manager.graphs:
            results[g] = {}
            for path, (parent, idx) in self.output_structure(g):
                node = parent.inputs[idx]
                all_paths = set()
                for node2 in dfs(node, succ_incoming):
                    all_paths.update(paths.get(node2, []))
                results[g][path] = (parent, idx), all_paths

        return results

    def find_dead_paths(self, root):
        """Returns a set of dead paths for each graph.

        Returns {graph: {(node, idx) ...}} where the edge represented
        by (node, idx) is dead.
        """
        deps = self.dependencies(root)

        seen = set()
        keep = set()

        def succ(path):
            if path in seen:
                return
            g, *path = path
            if g not in deps:
                return
            path = tuple(path)
            sg = deps[g]
            while path and path not in sg:
                path = path[:-1]
            seen.add((g, *path))
            keep.update(_subslices((g, *path)))
            node, paths = sg[path]
            for p in paths:
                yield p

        for path in deps.get(root, []):
            for _ in dfs((root, *path), succ):
                pass

        missing = {}
        for g, paths in deps.items():
            missing[g] = set(node for (p, (node, _)) in paths.items()
                             if (g, *p) not in keep
                             and all(subp not in seen
                                     for subp in _subslices((g, *p))))
        return missing

    def __call__(self, root):
        """Apply dead data elimination."""
        missing = self.find_dead_paths(root)
        mng = root.manager
        for g, dead in missing.items():
            if g not in mng.graphs:
                # This might happen if set_edge removes a graph.
                continue
            for node, idx in dead:
                repl = Constant(DEAD)
                repl.abstract = node.inputs[idx].abstract
                if isinstance(repl.abstract, AbstractFunction):
                    repl.abstract = AbstractError(DEAD)
                mng.set_edge(node, idx, repl)
        return False  # Pretend there are no changes, for now
