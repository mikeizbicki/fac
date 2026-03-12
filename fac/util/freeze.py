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
    if isinstance(obj, dict):
        return frozendict({k: freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, set, frozenset)):
        return frozenset(freeze(item) for item in obj)
    return obj



