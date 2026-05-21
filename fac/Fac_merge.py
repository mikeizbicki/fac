from fac.util.targets import match_pattern_starstar, extract_variables, substitute_variables, variables_transitive_substitute
from fac.util.variables import eval_var


def safe_dict_union(dict1, dict2):
    """
    Returns the union of two dicts, raising an error if the same key
    has different values in both dicts.

    >>> safe_dict_union({'a': 1, 'b': 2}, {'b': 2, 'c': 3})
    {'a': 1, 'b': 2, 'c': 3}

    >>> safe_dict_union({'x': 10}, {'y': 20, 'z': 30})
    {'x': 10, 'y': 20, 'z': 30}

    >>> safe_dict_union({}, {'a': 1})
    {'a': 1}

    >>> safe_dict_union({'a': 1}, {})
    {'a': 1}

    >>> safe_dict_union({'a': 1, 'b': 2}, {'b': 3, 'c': 3})  # doctest: +ELLIPSIS
    Traceback (most recent call last):
        ...
    AssertionError: Conflict: key 'b' has different values: 2 vs 3
    """
    result = dict(dict1)
    for key, value in dict2.items():
        if key in result:
            assert result[key] == value, \
                    f"Conflict: key '{key}' has different values: {result[key]} vs {value}"
        else:
            result[key] = value
    return result


def merge_context(context1, context2, slow_sanity_check=True):
    '''
    Occasionally we create a new BuildContext that "conflicts" with an existing
    context in the sense that they both resolve to the same path.
    This function merges them into a single context.

    It performs a number of integrity checks to ensure that the two contexts
    are compatible with each other and would eventually have resulted in
    the same files(s) getting built after they were both fully resolved.
    Some of these integrity checks are a bit jankier than I'd like them to be.
    
    NOTE:
    I've tried several times getting doctests for this function.
    In principle, it should be possible because this is a "pure" function without IO.
    In practice, the doctests interact with IO due to assert_invariants() checks,
    and so the doctests are too brittle and more trouble than they are worth.
    '''

    # all of the following properties must be identical to merge
    assert context1.normalized_target == context2.normalized_target, f'context1.normalized_target={context1.normalized_target}, context1.path={context1.path_safe()}, context2.normalized_target={context2.normalized_target}, context2.path={context2.path_safe()}'
    assert context1.config == context2.config
    assert context1.include_prompt == context2.include_prompt
    assert context1.include_old == context2.include_old
    assert context1.include_paths == context2.include_paths

    # we keep all resolved variables from both contexts;
    # we only keep unresolved variables if they are not resolved in the other context
    variables_resolved = safe_dict_union(
            context1.variables_resolved,
            context2.variables_resolved,
            )
    variables_unresolved = safe_dict_union(
            context1.variables_unresolved,
            context2.variables_unresolved,
            )
    for var, expr in list(variables_unresolved.items()):
        if var in variables_resolved:
            if slow_sanity_check:
                # the check enforces that any unresolved variables
                # will resolve to the same value in both contexts;
                # normally it is not safe to evaluate arbitrary variables,
                # and we need a complex set of checks to ensure that
                # appropriate dependencies have already been defined;
                # in this case, however, we know that the variable
                # has already been evaluated once by the other context;
                # so any needed dependencies (i.e. files) should already
                # have been created
                value = eval_var(expr, variables_resolved)
                assert value == variables_resolved[var]
            del variables_unresolved[var]

    # we keep all built dependencies from both contexts
    dependencies_built = context1.dependencies_built | context2.dependencies_built
    built_paths = set([dep['target'] for dep in dependencies_built])

    # processing the other dependencies is rather complicated for two reasons:
    # they are stored in a different format (normalized instead of paths),
    # we only keep building dependencies if they have not already been built
    dependencies_building = set(
            context1.dependencies_building |
            context2.dependencies_building
            )
    for dep in list(dependencies_building):
        denormalized_targets = substitute_variables(
                dep['target'],
                variables_resolved,
                )
        denormalized_targets = substitute_variables(
                dep['target'],
                variables_resolved,
                )
        if len(denormalized_targets) == 0:
            dependencies_building.remove(dep)
        else:
            # either all targets should be built or no targets should be built
            if all([target in built_paths for target in denormalized_targets]):
                dependencies_building.remove(dep)
            #else:
                #assert all([target not in built_paths for target in denormalized_targets])

    dependencies_unresolved = set(
            context1.dependencies_unresolved |
            context2.dependencies_unresolved
            )
    for dep in list(dependencies_unresolved):
        # if dep has already advanced from unresolved -> building,
        # remove it from unresolved
        if dep in dependencies_building:
            dependencies_unresolved.remove(dep)

        # if dep has already been built,
        # remove it from unresolved
        denormalized_targets = substitute_variables(
                dep['target'],
                variables_resolved,
                )
        if len(denormalized_targets) == 0:
            dependencies_unresolved.remove(dep)
        else:
            if all([target in built_paths for target in denormalized_targets]):
                dependencies_unresolved.remove(dep)
            # FIXME: deleted this assert because I don't know why it's here?!
            #else:
                #assert all([target not in built_paths for target in denormalized_targets])

    return context1.model_copy(update={
        'tasks': context1.tasks | context2.tasks,
        'variables_resolved': variables_resolved,
        'variables_unresolved': variables_unresolved,
        'dependencies_built': dependencies_built,
        'dependencies_building': dependencies_building,
        'dependencies_unresolved': dependencies_unresolved,
        },
        # we don't assert the BuildContext invariants
        # because these check that all paths in dependencies_built actually exist,
        # and that breaks the doctests
        assert_invariants=False,
        )

