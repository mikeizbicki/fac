import heapq

class PrioritySet:
    """A set-like container with priority queue extraction.
    
    Combines set semantics (no duplicates) with heap-based priority extraction.
    Items are extracted in order determined by priority_func (lowest first).
    
    >>> ps = PrioritySet(priority_func=lambda x: x)
    >>> ps.add(3)
    >>> ps.add(1)
    >>> ps.add(2)
    >>> ps.add(1)  # duplicate, ignored
    >>> len(ps)
    3
    >>> ps.pop()
    1
    >>> ps.pop()
    2
    >>> ps.pop()
    3
    >>> len(ps)
    0
    
    Works with complex objects:
    >>> from collections import namedtuple
    >>> Task = namedtuple('Task', ['name', 'priority'])
    >>> ps = PrioritySet(priority_func=lambda t: t.priority)
    >>> ps.add(Task('low', 10))
    >>> ps.add(Task('high', 1))
    >>> ps.add(Task('mid', 5))
    >>> ps.pop().name
    'high'
    >>> ps.pop().name
    'mid'
    >>> ps.pop().name
    'low'
    
    Membership testing:
    >>> ps = PrioritySet()
    >>> ps.add('a')
    >>> 'a' in ps
    True
    >>> 'b' in ps
    False
    >>> ps.pop()
    'a'
    >>> 'a' in ps
    False
    
    Boolean evaluation:
    >>> ps = PrioritySet()
    >>> bool(ps)
    False
    >>> ps.add(1)
    >>> bool(ps)
    True
    
    Empty pop raises KeyError:
    >>> ps = PrioritySet()
    >>> ps.pop()
    Traceback (most recent call last):
        ...
    KeyError: 'pop from empty PrioritySet'
    
    Stable ordering (FIFO) for equal priorities:
    >>> ps = PrioritySet(priority_func=lambda x: 0)  # all same priority
    >>> ps.add('first')
    >>> ps.add('second')
    >>> ps.add('third')
    >>> [ps.pop() for _ in range(3)]
    ['first', 'second', 'third']
    """
    
    def __init__(self, priority_func=lambda x: 0):
        self._heap = []
        self._set = set()
        self._priority_func = priority_func
        self._counter = 0
    
    def add(self, item):
        """Add item to set. No-op if already present."""
        if item not in self._set:
            self._set.add(item)
            priority = self._priority_func(item)
            heapq.heappush(self._heap, (priority, self._counter, item))
            self._counter += 1
    
    def pop(self):
        """Remove and return lowest-priority item. Raises KeyError if empty."""
        while self._heap:
            _, _, item = heapq.heappop(self._heap)
            if item in self._set:
                self._set.discard(item)
                return item
        raise KeyError('pop from empty PrioritySet')
    
    def __contains__(self, item):
        return item in self._set
    
    def __len__(self):
        return len(self._set)
    
    def __bool__(self):
        return bool(self._set)

    def to_list(self):
        """Return list of (priority, item) tuples in priority order (lowest first).

        >>> ps = PrioritySet(priority_func=lambda x: x * 2)
        >>> ps.add(3)
        >>> ps.add(1)
        >>> ps.add(2)
        >>> ps.to_list()
        [(2, 1), (4, 2), (6, 3)]
        """
        items = [(self._priority_func(item), item) for item in self._set]
        items.sort(key=lambda x: x[0])
        return items

    def to_list_nopriority(self):
        """Return list of (priority, item) tuples in priority order (lowest first).

        >>> ps = PrioritySet(priority_func=lambda x: x * 2)
        >>> ps.add(3)
        >>> ps.add(1)
        >>> ps.add(2)
        >>> ps.to_list_nopriority()
        [1, 2, 3]
        """
        return [item for priority, item in self.to_list()]
