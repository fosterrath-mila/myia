"""Tools for aliasing detection and handling."""


from collections import defaultdict
from dataclasses import is_dataclass

import numpy as np

from ..prim import ops as P
from ..utils import ADT, MyiaInputTypeError, dataclass_fields, overload
from . import data as ab


@overload.wrapper(bootstrap=True, initial_state=set)
def _explore(__call__, self, v, vseq, path):
    yield v, vseq, path
    if id(v) in self.state:
        return
    self.state.add(id(v))
    yield from __call__(self, v, vseq, path)


@overload  # noqa: F811
def _explore(self, v: (list, tuple), vseq, path):
    vseq = (*vseq, v)
    for i, x in enumerate(v):
        yield from self(x, vseq, (*path, i))


@overload  # noqa: F811
def _explore(self, v: dict, vseq, path):
    vseq = (*vseq, v)
    for k, x in v.items():
        yield from self(x, vseq, (*path, k))


@overload  # noqa: F811
def _explore(self, v: object, vseq, path):
    if is_dataclass(v):
        vseq = (*vseq, v)
        for k, x in dataclass_fields(v).items():
            yield from self(x, vseq, (*path, k))

def ndarray_aliasable(v, vseq, path):
    """Aliasing policy whereas all numpy.ndarray are aliasable.

    Arrays inside a list or ADT are not aliasable.
    """
    if isinstance(v, np.ndarray):
        if any(isinstance(x, (list, ADT)) for x in vseq):
            return 'X'
        else:
            return True
    return False


def find_aliases(obj, aliasable=ndarray_aliasable):
    """
    Find aliased data in obj.

    :param ndarray_aliasable: A function with signature
       ((v, vseq, path) -> True/False/"X")

       where:

          v: The potentially aliasable value
          vseq: The sequence of objects containing v
          path: The sequence of indexes on the path to v

    :return: True: v is aliasable, False: v is not aliasable, "X": v is 
       aliasable, but it is located in a place where the aliasing data
       cannot be used.
    """
    if aliasable is None:
        return {}, {}

    bad = {}
    paths = defaultdict(list)
    for v, vseq, path in _explore(obj, (), ()):
        al = aliasable(v, vseq, path)
        if al:
            if al == 'X':
                bad[id(v)] = True
            paths[id(v)].append(path)

    i = 1
    id_to_aid = {}
    aid_to_paths = {}
    for idv, path in paths.items():
        if len(path) > 1:
            if bad.get(idv, False):
                raise MyiaInputTypeError(
                    'There is aliased data in non-aliasable data types'
                )
            id_to_aid[idv] = i
            aid_to_paths[i] = path
            i += 1

    return id_to_aid, aid_to_paths


@overload(bootstrap=True)
def generate_getters(self, tup: ab.AbstractTuple, get):
    """Recursively generate sexps for getting elements of a data structure."""
    yield tup, get
    for i, elem in enumerate(tup.elements):
        geti = (P.tuple_getitem, get, i)
        yield from self(elem, geti)


@overload  # noqa: F811
def generate_getters(self, dat: ab.AbstractClassBase, get):
    yield dat, get
    for k, elem in dat.attributes.items():
        getk = (P.record_getitem, get, k)
        yield from self(elem, getk)


@overload  # noqa: F811
def generate_getters(self, dat: ab.AbstractDict, get):
    yield dat, get
    for k, elem in dat.entries.items():
        getk = (P.dict_getitem, get, k)
        yield from self(elem, getk)


@overload  # noqa: F811
def generate_getters(self, obj: object, get):
    yield obj, get


def setter_from_getter(getter, value):
    """Generate an expression to set a value from the expression to get it."""
    setters = {
        P.tuple_getitem: P.tuple_setitem,
        P.dict_getitem: P.dict_setitem,
        P.record_getitem: P.record_setitem,
    }
    if isinstance(getter, tuple):
        oper, elem, i = getter
        return setter_from_getter(elem, (setters[oper], elem, i, value))
    else:
        return value
