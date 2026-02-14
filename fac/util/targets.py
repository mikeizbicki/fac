'''
This file contains utility functions for working with targets.
A target is a string that may contain shell-like variables (e.g. $EXAMPLE).
These shell-like variables will be substituted with their values to resolve to a path.

IMPLEMENTATION NOTE:
Basically all of these functions were written by LLMs,
and I have not actually reviewed their implementation.
I have high confidence the work correctly because of the doctests.
But any edge cases not covered by doctests are likely broken.
'''

import re


def extract_variables(target):
    """
    Extract variables from a single target string.

    Examples:
        >>> extract_variables("$SERIES/$STORY/outline.json")
        ['SERIES', 'STORY']

        >>> extract_variables("$SERIES/$STORY/chapter$CHAPTER/chapter.json")
        ['SERIES', 'STORY', 'CHAPTER']

        >>> extract_variables("$SERIES/characters/$CHARACTER/about.json")
        ['SERIES', 'CHARACTER']

        >>> extract_variables("test_project/outline.json")
        []
    """
    return re.findall(r'\$(\w+)', target)



def variables_transitive_substitute(variables):
    '''
    The input dictionary represents a set of variable assignments.
    Some variables may be assigned to other variables (using $VAR shell notation).
    This function returns a resolved dictionary where all of these substitutions have occurred.

    # Chain resolution
    >>> variables_transitive_substitute({'a': '1', 'b': '$a', 'c': '$b'})
    {'a': '1', 'b': '1', 'c': '1'}

    # Multiple variables in one value
    >>> variables_transitive_substitute({'a': '1', 'b': '2', 'c': '$a$b'})
    {'a': '1', 'b': '2', 'c': '12'}
    >>> variables_transitive_substitute({'a': 'hello', 'b': 'world', 'c': '$a $b'})
    {'a': 'hello', 'b': 'world', 'c': 'hello world'}

    # Partial matches
    >>> variables_transitive_substitute({'a': '1', 'ab': '$a2'})
    {'a': '1', 'ab': '$a2'}
    >>> variables_transitive_substitute({'a': '1', 'b': 'prefix$a'})
    {'a': '1', 'b': 'prefix1'}

    # Undefined variables (remain as-is)
    >>> variables_transitive_substitute({'a': '$undefined'})
    {'a': '$undefined'}

    # Empty dictionary
    >>> variables_transitive_substitute({})
    {}
    '''
    resolved = variables.copy()
    changed = True

    # Keep resolving until no more substitutions are made
    while changed:
        changed = False
        for key, value in resolved.items():
            # Find all $VAR patterns in the value
            matches = re.findall(r'\$([a-zA-Z_][a-zA-Z0-9_]*)', str(value))
            new_value = str(value)

            for var_name in matches:
                if var_name in resolved:
                    # Replace $var_name with its resolved value
                    new_value = new_value.replace(f'${var_name}', str(resolved[var_name]))
                    changed = True

            resolved[key] = new_value

    return resolved

def substitute_variables(target: str, variables: dict[str, str]):
    r"""
    Substitute variables into the target.

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
    This can result in an empty list being returned if those variables are used in the target.

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

    results = [target]

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


def match_pattern_starstar(patterns, input_string):
    """
    Match an input string (containing **) against patterns and extract variables.

    ** in input_string can match any number of path segments in patterns.
    Variables matched by ** are not extracted (similar to how $VAR in input_string are not extracted).

    Args:
        patterns: List of pattern strings with variables like "$SERIES/$STORY/outline.json"
        input_string: String that may contain ** wildcards, e.g. "a/**/outline.json"

    Returns:
        List of tuples: [(matched_pattern, extracted_variables), ...]
        Empty list if no matches. Variables consumed by ** are not included in extracted_variables.

    Examples:

        >>> match_pattern_starstar(["$SERIES/$STORY/outline.json"], "mystory/**/outline.json")
        [('$SERIES/$STORY/outline.json', {'SERIES': 'mystory'})]
        >>> match_pattern_starstar(["$SERIES/$PART/$CHAPTER/outline.json"], "mystory/**/outline.json")
        [('$SERIES/$PART/$CHAPTER/outline.json', {'SERIES': 'mystory'})]
        >>> match_pattern_starstar(["$SERIES/$STORY/outline.json"], "**/outline.json")
        [('$SERIES/$STORY/outline.json', {})]
        >>> match_pattern_starstar(["$SERIES/$STORY/outline.json"], "mystory/**")
        [('$SERIES/$STORY/outline.json', {'SERIES': 'mystory'})]
        >>> match_pattern_starstar(["$A/$B/$C/file.json"], "start/**/file.json")
        [('$A/$B/$C/file.json', {'A': 'start'})]

    Multiple patterns:

        >>> match_pattern_starstar(["$A/$B/file.json", "$X/$Y/$Z/file.json"], "test/**/file.json")
        [('$A/$B/file.json', {'A': 'test'}), ('$X/$Y/$Z/file.json', {'X': 'test'})]
        >>> match_pattern_starstar(["$A/$B/file.json", "$X/$Y/file.json"], "test/**/file.json")
        [('$A/$B/file.json', {'A': 'test'}), ('$X/$Y/file.json', {'X': 'test'})]
        >>> match_pattern_starstar(["$A/specific/file.json", "$X/$Y/$Z/file.json"], "test/**/file.json")
        [('$A/specific/file.json', {'A': 'test'}), ('$X/$Y/$Z/file.json', {'X': 'test'})]
        >>> match_pattern_starstar(["$A/$B/config.json", "$X/$Y/$Z/config.json", "$P/$Q/$R/$S/config.json"], "proj/**/config.json")
        [('$A/$B/config.json', {'A': 'proj'}), ('$X/$Y/$Z/config.json', {'X': 'proj'}), ('$P/$Q/$R/$S/config.json', {'P': 'proj'})]
        >>> match_pattern_starstar(["$A/$B/outline.json", "$X/$Y/summary.json"], "proj/**/outline.json")
        [('$A/$B/outline.json', {'A': 'proj'})]
        >>> match_pattern_starstar(["$A/chapter/$B/file.json", "$X/$Y/$Z/file.json"], "book/**/file.json")
        [('$A/chapter/$B/file.json', {'A': 'book'}), ('$X/$Y/$Z/file.json', {'X': 'book'})]
        >>> match_pattern_starstar(["$A/$B/file.json", "$X/exact/file.json"], "test/exact/file.json")
        [('$A/$B/file.json', {'A': 'test', 'B': 'exact'}), ('$X/exact/file.json', {'X': 'test'})]

    If a variable matches with another variable with the "incorrect name", we include it in the output:

        >>> match_pattern_starstar(["$A/$B/file.json", "$X/$Y/$Z/file.json"], "test/$VAR/file.json")
        [('$A/$B/file.json', {'A': 'test', 'B': '$VAR'})]

    No match cases:

        >>> match_pattern_starstar(["$SERIES/$STORY/outline.json"], "mystory/**/summary.json")
        []
        >>> match_pattern_starstar(["$A/$B/file.json"], "first/file.json")
        []
        >>> match_pattern_starstar([], "test/**/file.json")
        []
        >>> match_pattern_starstar(['about.md', 'art.md', 'writing.md', 'characters/$CHARACTER/about.json', 'characters/$CHARACTER/artist_instructions.md', 'characters/$CHARACTER/character_sheet.png', 'locations/$LOCATION/about.json', 'locations/$LOCATION/reference.png', 'books/$LEVEL/themes.md', 'books/$LEVEL/$BOOK/content.jsonl', 'books/$LEVEL/$BOOK/frames/$FRAME_ID/art.json', 'books/$LEVEL/$BOOK/frames/$FRAME_ID/art.png', 'books/$LEVEL/$BOOK/frames/$FRAME_ID/page.pdf', 'books/$LEVEL/$BOOK/pages.pdf', 'books/$LEVEL/$BOOK/description.json'], 'locations/familyhouse_interior_diningroom/reference.json')
        []

    Real world examples:

        >>> match_pattern_starstar(["$PROJ/$MOD/src/$FILE.py", "$PROJ/tests/$TEST.py", "$PROJ/$DIR/$SUBDIR/config.json"], "myproj/**/config.json")
        [('$PROJ/$DIR/$SUBDIR/config.json', {'PROJ': 'myproj'})]
        >>> match_pattern_starstar(["$ORG/$REPO/src/main/$MODULE.rs", "$ORG/$REPO/target/debug/$BINARY", "$ORG/$REPO/docs/$SECTION/$PAGE.md", "$PROJECT/build/$ARTIFACT.jar"], "acme/widget/**/UserGuide.md")
        [('$ORG/$REPO/target/debug/$BINARY', {'ORG': 'acme', 'REPO': 'widget', 'BINARY': 'UserGuide.md'}), ('$ORG/$REPO/docs/$SECTION/$PAGE.md', {'ORG': 'acme', 'REPO': 'widget', 'PAGE': 'UserGuide'})]
        >>> match_pattern_starstar(["$APP/static/css/$THEME/$STYLE.css", "$APP/targets/$SECTION/$TEMPLATE.html", "$APP/api/v$VERSION/$ENDPOINT.py", "$APP/$MODULE/$COMPONENT/views.py"], "webapp/**/main.css")
        [('$APP/static/css/$THEME/$STYLE.css', {'APP': 'webapp', 'STYLE': 'main'})]
        >>> match_pattern_starstar(["services/$SERVICE/src/$MODULE.go", "services/$SERVICE/config/$ENV.yaml", "libs/$LIBRARY/$VERSION/src/$FILE.ts", "$ROOT/tools/$TOOL/bin/$EXECUTABLE"], "services/**/production.yaml")
        [('services/$SERVICE/config/$ENV.yaml', {'ENV': 'production'}), ('$ROOT/tools/$TOOL/bin/$EXECUTABLE', {'ROOT': 'services', 'EXECUTABLE': 'production.yaml'})]
        >>> match_pattern_starstar(["docs/$LANG/api/$MODULE/$CLASS.md", "docs/$LANG/guides/$CATEGORY/$GUIDE.md", "docs/assets/images/$SECTION/$IMAGE.png", "$PROJECT/wiki/$TOPIC.md"], "docs/**/Authentication.md")
        [('docs/$LANG/api/$MODULE/$CLASS.md', {'CLASS': 'Authentication'}), ('docs/$LANG/guides/$CATEGORY/$GUIDE.md', {'GUIDE': 'Authentication'}), ('$PROJECT/wiki/$TOPIC.md', {'PROJECT': 'docs', 'TOPIC': 'Authentication'})]
        >>> match_pattern_starstar(["build/$TARGET/$ARCH/lib$LIB.so", "build/$TARGET/bin/$BINARY", "dist/$PLATFORM/$VERSION/$PACKAGE.tar.gz", "cache/$HASH/$TEMP.tmp"], "build/**/myapp")
        [('build/$TARGET/bin/$BINARY', {'BINARY': 'myapp'})]
        >>> match_pattern_starstar(["$ENV/config/$SERVICE.conf", "global/config/$SETTING.ini", "$PROJECT/$MODULE/config/local.json", "deploy/$STAGE/$REGION/settings.yaml"], "prod/**/local.json")
        [('$PROJECT/$MODULE/config/local.json', {'PROJECT': 'prod'})]
        >>> match_pattern_starstar(["media/$TYPE/$YEAR/$MONTH/$FILE.$EXT", "assets/images/$CATEGORY/$SIZE/$IMAGE.jpg", "content/$SECTION/gallery/$ALBUM/$PHOTO.png"], "media/**/vacation.jpg")
        [('media/$TYPE/$YEAR/$MONTH/$FILE.$EXT', {'FILE': 'vacation', 'EXT': 'jpg'})]

    If a different variable name has been used in the pattern/input_string, we should still match:

        >>> match_pattern_starstar(['recursive/$TEST/$NAME', 'simple/$TEST/$NAME', 'nonrecursive/$TEST/$NAME'], 'recursive/$TEST/$DEP')
        [('recursive/$TEST/$NAME', {'NAME': '$DEP'})]

    Realworls examples:

        >>> match_pattern_starstar([
        ...         'outline.json',
        ...         'sub$LEVEL1/outline.json',
        ...         'sub$LEVEL1/sub$LEVEL2/outline.json',
        ...         'final.txt',
        ...         'sub$LEVEL1/summary_NOVAR.md',
        ...         'sub$LEVEL1/summary_SAMEVAR.md',
        ...         'sub$LEVEL1/summary_VARSUBSET.md',
        ...         'sub$LEVEL1/summary_FOO.md',
        ...         'sub$LEVEL1/summary_DEP.md',
        ...         'deps/$DEP',
        ...         'sub$LEVEL1/summary_EMPTY.md'
        ...     ],
        ...     'sub/summary_SAMEVAR.md')
        [('sub$LEVEL1/summary_SAMEVAR.md', {'LEVEL1': ''})]
    """
    # Check for multiple ** in input_string
    if input_string.count('**') > 1:
        raise ValueError("Multiple ** wildcards are not supported in input_string")

    # Normalize input
    norm_input = re.sub(r'(\.\/)+', '', input_string)
    
    input_segments = norm_input.split('/')
    matches = []
    
    for pattern in patterns:
        # Normalize pattern
        norm_pattern = re.sub(r'(\.\/)+', '', pattern)
        pattern_segments = norm_pattern.split('/')
        
        # Try to match this pattern
        result = _match_pattern_with_starstar(pattern_segments, input_segments)
        if result is not None:
            matches.append((norm_pattern, result))
    
    return matches


def _match_pattern_with_starstar(pattern_segments, input_segments):
    """Helper to match pattern against input containing **."""
    
    # ** must match at least one segment, so input can't be longer than pattern
    num_stars = input_segments.count('**')
    non_star_segments = len(input_segments) - num_stars
    
    if len(pattern_segments) < non_star_segments + num_stars:
        return None
    
    variables = {}
    p_idx = 0  # pattern index  
    i_idx = 0  # input index
    
    while i_idx < len(input_segments):
        input_seg = input_segments[i_idx]
        
        if input_seg == '**':
            # ** consumes pattern segments until we find the next matching input segment
            if i_idx == len(input_segments) - 1:
                # ** at end, consume all remaining pattern segments
                p_idx = len(pattern_segments)
                i_idx += 1
            else:
                # Find next non-** input segment
                next_i_idx = i_idx + 1
                while next_i_idx < len(input_segments) and input_segments[next_i_idx] == '**':
                    next_i_idx += 1
                
                if next_i_idx >= len(input_segments):
                    # Rest of input is **, consume all remaining pattern segments
                    p_idx = len(pattern_segments)
                    i_idx = len(input_segments)
                else:
                    next_input_seg = input_segments[next_i_idx]
                    
                    # Calculate how many pattern segments we need to leave for remaining input
                    remaining_input_segments = len(input_segments) - next_i_idx
                    remaining_stars = sum(1 for seg in input_segments[next_i_idx:] if seg == '**')
                    min_pattern_segments_needed = remaining_input_segments - remaining_stars + remaining_stars
                    
                    # Find the rightmost pattern segment that could match next_input_seg
                    # while leaving enough segments for the rest of the input
                    found_match = False
                    max_p_idx = len(pattern_segments) - min_pattern_segments_needed
                    
                    for try_p_idx in range(p_idx, max_p_idx + 1):
                        if try_p_idx < len(pattern_segments):
                            try_pattern_seg = pattern_segments[try_p_idx]
                            if _segment_can_match(try_pattern_seg, next_input_seg):
                                # Check if we can match the rest of the input from this position
                                temp_vars = _try_match_from_position(
                                    pattern_segments[try_p_idx:], 
                                    input_segments[next_i_idx:]
                                )
                                if temp_vars is not None:
                                    # ** consumes segments from p_idx to try_p_idx (exclusive)
                                    p_idx = try_p_idx
                                    i_idx = next_i_idx
                                    found_match = True
                                    break
                    
                    if not found_match:
                        return None
        else:
            # Regular segment matching
            if p_idx >= len(pattern_segments):
                return None
                
            pattern_seg = pattern_segments[p_idx]
            match_result = _match_single_segment(pattern_seg, input_seg)
            if match_result is None:
                return None
            variables.update(match_result)
            p_idx += 1
            i_idx += 1
    
    # Check if we consumed all pattern segments
    if p_idx != len(pattern_segments):
        return None
        
    return variables

def _try_match_from_position(pattern_segments, input_segments):
    """Try to match remaining pattern and input segments."""
    temp_vars = {}
    p_idx = 0
    i_idx = 0
    
    while i_idx < len(input_segments) and p_idx < len(pattern_segments):
        input_seg = input_segments[i_idx]
        
        if input_seg == '**':
            # Skip ahead in pattern - simplified logic for validation
            segments_to_skip = 1
            if i_idx == len(input_segments) - 1:
                segments_to_skip = len(pattern_segments) - p_idx
            p_idx += segments_to_skip
            i_idx += 1
        else:
            pattern_seg = pattern_segments[p_idx]
            match_result = _match_single_segment(pattern_seg, input_seg)
            if match_result is None:
                return None
            temp_vars.update(match_result)
            p_idx += 1
            i_idx += 1
    
    if p_idx == len(pattern_segments) and i_idx == len(input_segments):
        return temp_vars
    return None

def _segment_can_match(pattern_seg, input_seg):
    """Check if a pattern segment could match an input segment."""
    return _match_single_segment(pattern_seg, input_seg) is not None

def _match_single_segment(pattern_seg, input_seg):
    """Match a single pattern segment against input segment."""
    import re
    
    # Handle variables in input segment (reverse matching)
    if '$' in input_seg and '$' not in pattern_seg:
        # Build regex from input_seg to match against pattern_seg
        regex = '^'
        pos = 0
        var_names = []
        
        while pos < len(input_seg):
            if input_seg[pos] == '$':
                var_start = pos + 1
                var_end = var_start
                while var_end < len(input_seg) and (input_seg[var_end].isalnum() or input_seg[var_end] == '_'):
                    var_end += 1
                var_name = input_seg[var_start:var_end]
                var_names.append(var_name)
                regex += '(.+)'
                pos = var_end
            else:
                if input_seg[pos] in '.^$*+?{}[]\\|()':
                    regex += '\\'
                regex += input_seg[pos]
                pos += 1
        regex += '$'
        
        match = re.match(regex, pattern_seg)
        if not match:
            return None
        
        variables = {}
        for j, var_name in enumerate(var_names):
            variables[var_name] = match.group(j + 1)
        return variables
    
    if '$' not in pattern_seg:
        return {} if pattern_seg == input_seg else None
    
    # Handle variables in pattern segment
    regex = '^'
    pos = 0
    var_names = []
    
    while pos < len(pattern_seg):
        if pattern_seg[pos] == '$':
            var_start = pos + 1
            var_end = var_start
            while var_end < len(pattern_seg) and (pattern_seg[var_end].isalnum() or pattern_seg[var_end] == '_'):
                var_end += 1
            
            var_name = pattern_seg[var_start:var_end]
            var_placeholder = f"${var_name}"
            
            if var_placeholder in input_seg:
                regex += re.escape(var_placeholder)
            else:
                var_names.append(var_name)
                regex += '(.*?)'
            
            pos = var_end
        else:
            if pattern_seg[pos] in '.^$*+?{}[]\\|()':
                regex += '\\'
            regex += pattern_seg[pos]
            pos += 1
    
    regex += '$'
    match = re.match(regex, input_seg)
    
    if not match:
        return None
    
    variables = {}
    for j, var_name in enumerate(var_names):
        variables[var_name] = match.group(j + 1)
    
    return variables

