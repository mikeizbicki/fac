'''
This file handles loading and manipulating `fac.yaml` config files.
'''

# stdlib imports
from collections import defaultdict, deque
import copy
import os
import re

# external lib imports
import yaml


def load_config(path):
    '''
    Loads a fac.yaml file and generates a dictionary of targets.
    This is a simple wrapper around `rawyaml_to_targets`.
    '''
    with open(path) as fin:
        text = fin.read()
    return rawyaml_to_targets(text)


def pprint_targets(targets):
    '''
    A wrapper around `yaml.dump` for pretty printing a dictionary of targets.
    '''
    print(yaml.dump(targets, default_flow_style=False).strip())


def rawyaml_to_targets(rawyaml):
    r'''
    The following example shows a simple yaml target gets expanded with default values.

    >>> pprint_targets(rawyaml_to_targets("""
    ... example/target:
    ...   description: example target's description
    ...   dependencies:
    ...   - file1
    ...   - file2
    ... """))
    example/target:
      _working_directory: .
      dependencies:
      - target: file1
      - target: file2
      description: example target's description
      variables: {}

    We call a top-level entry in the yaml config a "scope" if it ends in a slash.

    >>> pprint_targets(rawyaml_to_targets("""
    ... example/scope/:
    ...   targets:
    ...     target1:
    ...       description: this is an example target within a scope
    ...     example/target2:
    ...       description: a different target
    ...       variables:
    ...         var1: echo "hello"
    ...         var2: echo "world"
    ...     scope1/:
    ...       targets:
    ...         target1:
    ...           description: this target has the same name as a different target in a different scope, and that's okay
    ...           options_text:
    ...             model: opus4.5
    ...   variables:
    ...     var1: echo "hola"
    ...     var3: echo "mundo"
    ...   options_text:
    ...     model: gpt5.2
    ... """))
    example/scope/example/target2:
      _working_directory: example/scope
      dependencies: []
      description: a different target
      options_text:
        model: gpt5.2
      variables:
        var1: echo "hello"
        var2: echo "world"
        var3: echo "mundo"
    example/scope/scope1/target1:
      _working_directory: example/scope/scope1
      dependencies: []
      description: this target has the same name as a different target in a different
        scope, and that's okay
      options_text:
        model: opus4.5
      variables:
        var1: echo "hola"
        var3: echo "mundo"
    example/scope/target1:
      _working_directory: example/scope
      dependencies: []
      description: this is an example target within a scope
      options_text:
        model: gpt5.2
      variables:
        var1: echo "hola"
        var3: echo "mundo"
    '''
    config = yaml.safe_load(rawyaml)
    return _configdict_to_targets(config)


def _configdict_to_targets(config):
    '''
    This is an internal helper for rawyaml_to_targets.
    It takes a dictionary as input, which is not particularly human-friendly.
    '''

    # generate an initial targets dictionary from config by processing scopes
    targets = {}
    for c_name, c_value in config.items():

        # if c_name is not a scope, add it to targets dictionary directly
        if c_name[-1] != '/':
            targets[c_name] = copy.deepcopy(c_value)
            targets[c_name]['_working_directory'] = '.'

        # if c_name is a scope, add all subtargets within scope
        else:
            subtargets = _configdict_to_targets(c_value.get('targets', {}))
            for st_name, st_value in subtargets.items():
                name = c_name + st_name
                targets[name] = copy.deepcopy(st_value)
                targets[name]['_working_directory'] = os.path.normpath(c_name + targets[name]['_working_directory'])

                # inherit the values of variables and options_* dictionaries that are specified for the scope,
                # but do not overwrite existing values within the subtargets;
                # equivalently, the values within the subtargets "overwrite" the default values specified in the scope
                fields_to_inherit = [
                    'variables',
                    'options_text',
                    'options_image',
                    'options_video',
                    'options_audio',
                    ]
                for field in fields_to_inherit:
                    c_value.setdefault(field, {})
                    for val in c_value[field]:
                        targets[name].setdefault(field, {})
                        if val not in targets[name][field]:
                            targets[name][field][val] = c_value[field][val]

    # clean the final output targets dict
    for target in targets:
        # set the mime-type
        if 'mime-type' not in targets[target]:
            filename = os.path.basename(target)
            _, extension = os.path.splitext(filename)

            if extension == '.md' or extension == '.markdown':
                targets[target]['mime-type'] = 'text/markdown'
            elif extension == '.html':
                targets[target]['mime-type'] = 'text/html'
            elif extension == '.json':
                targets[target]['mime-type'] = 'text/json'
            elif extension == '.jsonl':
                targets[target]['mime-type'] = 'text/jsonl'
            elif extension == '.png':
                targets[target]['mime-type'] = 'image/png'
            elif extension == '.wav':
                targets[target]['mime-type'] = 'audio/wav'
            elif extension == '.mp4':
                targets[target]['mime-type'] = 'video/mp4'
            else:
                targets[target]['mime-type'] = 'text/plain'


        # remove excess whitespace from fields;
        # this is mostly useful for debugging and getting nice looking configs
        for option in targets[target]:
            if type(targets[target][option]) == str:
                targets[target][option] = targets[target][option].strip()
            elif type(targets[target][option]) == dict:
                for suboption in targets[target][option]:
                    if type(targets[target][option][suboption]) == str:
                        targets[target][option][suboption] = targets[target][option][suboption].strip()

        # the dependencies field can be specified as a string, list of strings, or list of dictionaries;
        # we convert all forms into the list of dictionary form here
        dependencies1 = []
        dependencies = targets[target].get('dependencies', '')
        if type(dependencies) is str:
            dependencies = dependencies.split()
        elif dependencies is None:
            dependencies = []
        for dep in dependencies:
            if type(dep) == str:
                dep = {'target': dep}
            assert type(dep) == dict
            dependencies1.append(dep)
            for k in dep:
                if k not in ['target', 'include', 'allow_create', 'is_prompt']:
                    logger.warning(f'in target "{target}", in dependency "{dep["target"]}", unknown option "{k}"')
        targets[target]['dependencies'] = dependencies1

        # ensure that all fields have reasonable default values
        targets[target].setdefault('dependencies', {})
        targets[target].setdefault('variables', {})

    # reorder the variable definitions
    for target in targets:
        targets[target]['variables'] = reorder_variable_dictionary(targets[target]['variables'])

    return targets


def reorder_variable_dictionary(var_dict):
    """
    Reorders a dictionary of shell variables to respect dependencies.
    We expect that var_dict has keys that represent shell variable names,
    and the values are commands that are run to set the value of those variables.
    Some of the commands may reference other variables in the dictionary,
    and we reorder the dictionary so that if the commands are run (in the order of the dictionary) there will be no error.
    That is, if VAR2 depends on VAR1, then VAR2 will appear after VAR1 in the dictionary.

    Raises:
        ValueError: If circular dependencies are detected

    >>> # Simple dependency chain
    >>> d1 = {'C': 'echo $B', 'B': 'echo $A', 'A': 'echo hello'}
    >>> result1 = reorder_variable_dictionary(d1)
    >>> list(result1.keys())
    ['A', 'B', 'C']

    >>> # No dependencies
    >>> d2 = {'X': 'echo x', 'Y': 'echo y', 'Z': 'echo z'}
    >>> result2 = reorder_variable_dictionary(d2)
    >>> set(result2.keys()) == {'X', 'Y', 'Z'}
    True

    >>> # Complex dependencies with ${} syntax
    >>> d3 = {'PATH': 'echo ${HOME}/bin:$OLDPATH', 'HOME': 'echo /home/user', 'OLDPATH': 'echo $PATH_BACKUP', 'PATH_BACKUP': 'echo /usr/bin'}
    >>> result3 = reorder_variable_dictionary(d3)
    >>> keys = list(result3.keys())
    >>> keys.index('PATH_BACKUP') < keys.index('OLDPATH')
    True
    >>> keys.index('HOME') < keys.index('PATH')
    True

    >>> # Direct circular dependency
    >>> d4 = {'VAR1': 'echo $VAR1'}
    >>> reorder_variable_dictionary(d4)
    Traceback (most recent call last):
    ...
    ValueError: Circular dependencies detected: VAR1

    >>> # Indirect circular dependency
    >>> d5 = {'VAR1': 'echo $VAR2', 'VAR2': 'echo $VAR1'}
    >>> reorder_variable_dictionary(d5)
    Traceback (most recent call last):
    ...
    ValueError: Circular dependencies detected: VAR1, VAR2

    >>> # 4-variable circular dependency: A->B->C->D->A
    >>> d6 = {'A': 'echo $D', 'B': 'echo $A', 'C': 'echo $B', 'D': 'echo $C'}
    >>> reorder_variable_dictionary(d6)
    Traceback (most recent call last):
    ...
    ValueError: Circular dependencies detected: A, B, C, D
    """
    # Build dependency graph
    dependencies = defaultdict(set)

    for var, command in var_dict.items():
        # Find variable references like $VAR or ${VAR}
        refs = re.findall(r'\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?', command)
        for ref in refs:
            if ref in var_dict:
                if ref == var:
                    raise ValueError(f"Circular dependencies detected: {var}")
                dependencies[var].add(ref)

    # Topological sort using Kahn's algorithm
    in_degree = {var: 0 for var in var_dict}
    for var in dependencies:
        for dep in dependencies[var]:
            in_degree[var] += 1

    queue = deque([var for var in in_degree if in_degree[var] == 0])
    result = []

    while queue:
        var = queue.popleft()
        result.append(var)
        for dependent in var_dict:
            if var in dependencies[dependent]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

    # Check for circular dependencies
    if len(result) != len(var_dict):
        remaining = sorted(set(var_dict.keys()) - set(result))
        raise ValueError(f"Circular dependencies detected: {', '.join(remaining)}")

    return {var: var_dict[var] for var in result}
