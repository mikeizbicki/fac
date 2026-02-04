'''
This file contains utility functions for working with templates.
A template is a string that may contain shell-like variables (e.g. $EXAMPLE).

IMPLEMENTATION NOTE:
Basically all of these functions were written by LLMs,
and I have not actually reviewed their implementation.
I have high confidence the work correctly because of the doctests.
But any edge cases not covered by doctests are likely broken.
'''


def substitute_variables(template: str, variables: dict[str, str]):
    r"""
    Substitute variables into the template.

    If a variable contains newlines, it's split and creates multiple output strings.
    If no variables contain newlines, returns a single-item list.
    If any variable is empty, returns an empty list.

    Basic examples:

    >>> substitute_variables('Hello $name', {'name': 'world'})
    ['Hello world']
    >>> substitute_variables('$greeting $name', {'greeting': 'Hi', 'name': 'Alice'})
    ['Hi Alice']
    >>> substitute_variables('${var1}_${var2}', {'var1': 'prefix', 'var2': 'suffix'})
    ['prefix_suffix']

    When variables contain a newline,
    we split the variable on the newline and the returned list has the substitution done for each entry.

    >>> substitute_variables('Name: $name', {'name': 'Alice\nBob'})
    ['Name: Alice', 'Name: Bob']
    >>> substitute_variables('$x-$y', {'x': 'a\nb', 'y': '1\n2'})
    ['a-1', 'a-2', 'b-1', 'b-2']

    After splitting on newlines, we remove extra whitespace.
    If any element in the newly created list is '',
    we remove that element.
    This can result in an empty list being returned if those variables are used in the template.

    >>> substitute_variables('Value: $var', {'var': ''})
    []
    >>> substitute_variables('$a and $b', {'a': 'hello', 'b': ''})
    []
    >>> substitute_variables('$a and $b', {'a': 'hello', 'b': 'world', 'c': ''})
    ['hello and world']
    >>> substitute_variables('$a and $b', {'a': 'hello', 'b': '   \n '})
    []
    >>> substitute_variables('$var', {'var': '  \n  \nvalid\n  '})
    ['valid']
    >>> substitute_variables('$var', {'var': '  \n  \n   valid  \n  '})
    ['valid']

    Example test cases without substitutions.

    >>> substitute_variables('No variables here', {})
    ['No variables here']
    >>> substitute_variables('$missing stays', {'other': 'value'})
    ['$missing stays']
    >>> substitute_variables('$found and $missing', {'found': 'exists'})
    ['exists and $missing']
    """
    if variables is None:
        variables = {}

    results = [template]

    for var, value in variables.items():
        new_results = []
        for result in results:
            if f'${var}' in result or f'${{{var}}}' in result:
                lines = str(value).split('\n')
                for line in lines:
                    line = line.strip()
                    if line:  # Only append if line is non-empty
                        new_str = result.replace(f'${var}', line).replace(f'${{{var}}}', line)
                        new_results.append(new_str)
            else:
                new_results.append(result)
        results = new_results


    return results



