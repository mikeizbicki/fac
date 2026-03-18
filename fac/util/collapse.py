def collapse_redundant(node):
    """
    Collapse redundant structures in a nested dict tree.

    Redundant means: a key maps to a subtree that is structurally identical
    (same key pattern) and can be collapsed.

    >>> collapse_redundant({'a': {'a': {'b': {}}}})
    {'a': {'b': {}}}

    >>> collapse_redundant({'x': {'x': {'x': {'y': {}}}}})
    {'x': {'y': {}}}

    >>> collapse_redundant({'a': {'b': {}}})
    {'a': {'b': {}}}

    >>> collapse_redundant({'a': {'a': {}, 'b': {}}})
    {'a': {'a': {}, 'b': {}}}

    >>> collapse_redundant({'k': {'k': {'k': {'k': {'end': {}}}}}})
    {'k': {'end': {}}}
    """
    def trees_equal(a, b):
        """Check structural equality of two nodes."""
        if type(a) != type(b):
            return False
        if isinstance(a, dict):
            if a.keys() != b.keys():
                return False
            return all(trees_equal(a[k], b[k]) for k in a)
        return a == b

    def collapse(node):
        if isinstance(node, dict):
            if not node:
                return {}
            result = {}
            for k, v in node.items():
                collapsed_v = collapse(v)
                # Check if v is a single-key dict with the same key
                if (isinstance(collapsed_v, dict) and len(collapsed_v) == 1 and
                    k in collapsed_v):
                    # Potential redundancy: {k: {k: X}} -> {k: X}
                    inner = collapsed_v[k]
                    result[k] = inner
                else:
                    result[k] = collapsed_v
            return result
        else:
            return node

    # Iterate until no more changes
    prev = None
    current = node
    while not trees_equal(prev, current):
        prev = current
        current = collapse(current)
    return current


def flatten_singletons(data):
    """
    Converts nested singleton dicts into a list of their keys,
    preserving multi-key dicts as-is.

    >>> flatten_singletons({"a": {"b": {"c": True}}})
    ['a', 'b', 'c', True]

    >>> flatten_singletons({"a": {"b": {"x": 1, "y": 2}}})
    ['a', 'b', {'x': 1, 'y': 2}]

    >>> flatten_singletons({"only_key": 42})
    ['only_key', 42]

    >>> flatten_singletons({"x": 1, "y": 2})
    [{'x': 1, 'y': 2}]

    >>> flatten_singletons({})
    [{}]

    >>> flatten_singletons("not a dict")
    ['not a dict']

    >>> flatten_singletons({"a": {"b": None}})
    ['a', 'b', None]

    >>> flatten_singletons({"sub$LEVEL1/sub$LEVEL2/outline.json": {"final.txt": {"<user_action>": True}}})
    ['sub$LEVEL1/sub$LEVEL2/outline.json', 'final.txt', '<user_action>', True]
    """
    result = []

    while isinstance(data, dict) and len(data) == 1:
        key, value = next(iter(data.items()))
        result.append(key)
        data = value

    result.append(data)

    return result
