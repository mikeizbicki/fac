from Typeable import Any

def cartesian_product(input_dict: dict[Any, list[Any]]):
    '''
    >>> cartesian_product({'a': [1], 'b': [2, 4]})
    [{'a': 1, 'b': 2}, {'a': 1, 'b': 4}] 

    >>> cartesian_product({'a': [1, 2, 3], 'b': [2, 4]})
    [{'a': 1, 'b': 2}, {'a': 1, 'b': 4}, {'a': 2, 'b': 2}, {'a': 2, 'b': 4}, {'a': 3, 'b': 2}, {'a': 3, 'b': 4}] 
    '''
