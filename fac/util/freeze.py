from frozendict import frozendict


def freeze(obj):
    """Recursively convert dicts to frozendicts and iterables to frozensets.

    >>> freeze({'a': 1, 'b': 2})
    frozendict.frozendict({'a': 1, 'b': 2})

    >>> freeze({'nested': {'x': 1}})
    frozendict.frozendict({'nested': frozendict.frozendict({'x': 1})})

    >>> freeze([1, 2, 3])
    frozenset({1, 2, 3})

    >>> freeze({1, 2, 3})
    frozenset({1, 2, 3})

    >>> freeze([{'a': 1}, {'b': 2}]) == frozenset({frozendict({'a': 1}), frozendict({'b': 2})})
    True

    >>> freeze({'items': [{'x': 1}, {'y': 2}]}) == frozendict({'items': frozenset({frozendict({'x': 1}), frozendict({'y': 2})})})
    True

    >>> freeze('hello')
    'hello'

    >>> freeze(42)
    42

    >>> freeze(None)

    >>> freeze([])
    frozenset()

    >>> freeze({})
    frozendict.frozendict({})
    """
    obj_type = type(obj)
    if obj_type is dict:
        return frozendict({k: freeze(v) for k, v in obj.items()})
    if obj_type is list or obj_type is set or obj_type is frozenset:
        return frozenset(freeze(item) for item in obj)
    return obj


def thaw(obj):
    """Recursively convert frozendicts to dicts and frozensets to lists.

    >>> thaw(frozendict({'a': 1, 'b': 2}))
    {'a': 1, 'b': 2}

    >>> thaw(frozendict({'nested': frozendict({'x': 1})}))
    {'nested': {'x': 1}}

    >>> sorted(thaw(frozenset({1, 2, 3})))
    [1, 2, 3]

    >>> thaw('hello')
    'hello'

    >>> thaw(42)
    42

    >>> thaw(None)

    >>> thaw(frozenset())
    []

    >>> thaw(frozendict({}))
    {}

    >>> thaw(freeze({'a': 1, 'b': 2})) == {'a': 1, 'b': 2}
    True

    >>> thaw(freeze({'nested': {'x': 1}})) == {'nested': {'x': 1}}
    True

    >>> sorted(thaw(freeze([1, 2, 3]))) == sorted([1, 2, 3])
    True

    >>> thaw(freeze('hello')) == 'hello'
    True

    >>> thaw(freeze(42)) == 42
    True

    >>> thaw(freeze(None)) is None
    True

    >>> thaw(freeze([])) == []
    True

    >>> thaw(freeze({})) == {}
    True
    """
    if isinstance(obj, (dict, frozendict)):
        return {k: thaw(v) for k, v in obj.items()}
    if isinstance(obj, (list, set, frozenset)):
        return [thaw(item) for item in obj]
    return obj
