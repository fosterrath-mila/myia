"""Common subexpression elimination."""


from collections import defaultdict

from ..abstract import AbstractFunction, TypedPrimitive
from ..graph_utils import toposort
from ..ir import succ_incoming
from ..utils import Partializable


def _absof(node):
    # We use .abstract to differentiate identical values with different
    # types, e.g. 1.0::f32 and 1.0::f64.
    if isinstance(node.abstract, AbstractFunction):
        fn = node.abstract.get_unique()
        if isinstance(fn, TypedPrimitive):
            return fn
        else:
            # test_model::test_backward_specialize behaves differently if we
            # do not return fn here (it keeps an extra tuple_setitem operation
            # through the optimization)
            # TODO: Figure out why.
            return None
    else:
        return node.abstract


def group_nodes(root, manager):
    """Group together all nodes that could be merged.

    Some nodes in some groups may end up being unmergeable.
    """
    hashes = {}
    groups = defaultdict(list)
    manager.add_graph(root)

    for g in manager.graphs:
        for node in toposort(g.return_, succ_incoming):
            if node in hashes:
                continue

            if node.is_constant():
                h = hash((node.value, _absof(node)))
            elif node.is_apply():
                h = hash(tuple(hashes[inp] for inp in node.inputs))
            elif node.is_parameter():
                h = hash(node)
            else:
                raise TypeError(f'Unknown node type: {node}') \
                    # pragma: no cover

            hashes[node] = h
            groups[h, node.graph].append(node)
    return groups


def cse(root, manager):
    """Apply CSE on root."""
    groups = group_nodes(root, manager)
    changes = False

    # Note: this relies on dict keeping insertion order, so that the groups
    # dict is basically topologically ordered.

    for _, group in groups.items():
        main, *others = group
        for other in others:
            assert main.graph is other.graph

            if main.is_constant() and other.is_constant():
                repl = _absof(main) == _absof(other) \
                    and main.value == other.value

            elif main.is_apply() and other.is_apply():
                # The inputs to both should have been merged beforehand
                # because groups is topologically sorted
                in1 = main.inputs
                in2 = other.inputs
                repl = len(in1) == len(in2) \
                    and all(i1 is i2 for i1, i2 in zip(in1, in2))

            if repl:
                changes = True
                manager.replace(other, main)

    return changes


class CSE(Partializable):
    """Common subexpression elimination."""

    def __init__(self, resources, report_changes=True):
        """Initialize CSE."""
        self.resources = resources
        self.report_changes = report_changes

    def __call__(self, root):
        """Apply CSE on root."""
        chg = cse(root, self.resources.manager)
        return chg and self.report_changes
