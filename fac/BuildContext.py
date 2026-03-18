# stdlib imports
from collections import defaultdict
from dataclasses import dataclass
from frozendict import frozendict
from functools import cached_property
from typing import Any, Literal
import copy
import hashlib
import itertools

# external imports
from pydantic import BaseModel
import git
import yaml

# project imports
from fac.Errors import *
from fac.LLM import LLM, LLMError
from fac.io_utils import *
from fac.util.freeze import *
from fac.util.targets import *
from fac.util.templates import *


class BuildContext(BaseModel):
    '''
    The BuildContext is the fundamental building block of the build system.
    It represents the state of the build system for one target/path only at a single point in time.

    When the build system first loads a target,
    it will create a BuildContext populating the variables_unresolved and dependencies_unresolved attributes from the fac.yaml file.
    As processing proceeds, vars/deps will be "moved" into the variables_resolved/dependencies_built attrs.
    ("Moved" is in scare quotes because these attributes are immutable and so an entry cannot actually be moved; instead, the build system creates copies with these attributes modified.)

    In theory, a file could be built using a BuildContext directly without the need of the larger build system/fac.yaml.
    You just need to construct an appropriate BuildContext with the variables_resolved and dependencies_built values set appropriately.
    '''

    # we do not allow the BuildContext attributes to be modified after creation;
    # this ensures BuildContext is hashable;
    # it also helps prevent aliasing bugs
    # (which I've unfortunately encountered a lot of)
    model_config = {
            'frozen': True,
            'arbitrary_types_allowed': True,
            }

    ##############################
    # fields
    ##############################

    # the target (as it appears in the fac.yaml, with no variable substitutions)
    normalized_target: str

    # the fac.yaml config entry for normalized_target
    config: frozendict[str, Any]

    # both dicts below have variable names as keys
    # for resolved dict, the value is the content of the variable
    # for unresolved dict, the value is the code-to-generate the value (should match config)
    variables_resolved: frozendict[str, str]
    variables_unresolved: frozendict[str, str]

    # each frozendict must contain a 'target' key;
    # for unresolved/building: these targets will correspond to entries in the config
    # for built: the 'target' value will be denormalized to a file path
    dependencies_unresolved: frozenset[frozendict[str, str]]
    dependencies_building: frozenset[frozendict[str, str]]
    dependencies_built: frozenset[frozendict[str, str]]

    # FIXME:
    # the fields below are all set from the command line;
    # should these be moved to their own class?

    # include_* parameters all default to None,
    # but these could be passed in on the command line to modify the build behavior
    include_prompt: str | None = None
    include_old: bool = False
    include_paths: list[str] | None = None

    # possible values:
    # - dryrun (never builds; used for checking what paths exist for a target)
    # - build (builds only when needed; this is the typical case)
    # - overwrite (always builds)
    mode: Literal['dryrun', 'build', 'overwrite']

    ##############################
    # methods
    ##############################

    def __init__(self, **data):
        # we call freeze on all input data to convert dict to frozendict
        # and iterables to frozenset
        super().__init__(**{k: freeze(v) for k, v in data.items()})
        self.assert_invariants()

    def model_copy(self, update):
        new = super().model_copy(update=freeze(update))
        new.assert_invariants()
        return new

    def split(self):
        r'''
        This function creates a list of BuildContext instances by splitting all non-target variables on newlines.

        ---

        The helper function below converts the input to yaml and prints it.
        It makes visualization of the split BuildContext instances easier.

        >>> doctest_vis = lambda contexts: print(yaml.dump([context.to_dict() for context in contexts], default_flow_style=False))

        Actual test cases below.
        Observe that splitting happens only in variables contained in normalized_target,
        and all other variables are preserved as-is.

        >>> doctest_vis(BuildContext(
        ...     normalized_target='example/$FOO/$BAR/outline.json',
        ...     config={'variables': {'TEST': ''}},
        ...     variables_resolved={'TEST': 'a\bb\nc', 'FOO': '1\n2\n3', 'BAR': 'x\ny'},
        ...     variables_unresolved={},
        ...     dependencies_built=[],
        ...     dependencies_building=[],
        ...     dependencies_unresolved=[],
        ...     mode='build',
        ...     ).split())
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: x
            FOO: '1'
            TEST: "a\bb\nc"
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: y
            FOO: '1'
            TEST: "a\bb\nc"
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: x
            FOO: '2'
            TEST: "a\bb\nc"
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: y
            FOO: '2'
            TEST: "a\bb\nc"
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: x
            FOO: '3'
            TEST: "a\bb\nc"
        - normalized_target: example/$FOO/$BAR/outline.json
          variables_resolved:
            BAR: y
            FOO: '3'
            TEST: "a\bb\nc"
        <BLANKLINE>

        >>> BuildContext(
        ...     normalized_target='example/$FOO/$BAR/outline.json',
        ...     config={'variables': {'TEST': ''}},
        ...     variables_resolved={'TEST': 'a\bb\nc', 'FOO': '', 'BAR': 'x\ny'},
        ...     variables_unresolved={},
        ...     dependencies_built=[],
        ...     dependencies_building=[],
        ...     dependencies_unresolved=[],
        ...     mode='build',
        ...     ).split()
        []

        The following is a realworld BuildContext that was giving some problems.

        >>> len(BuildContext(
        ... normalized_target='sub$LEVEL1/outline.json',
        ... config=frozendict({'cmd': 'cp basic.json sub$LEVEL1/outline.json', 'dependencies': frozenset({frozendict({'target': 'resources/$RESOURCE/about.json'}), frozendict({'target': 'outline.json'})}), 'variables': frozendict({'LEVEL1': "jq -r 'range(0; .sections | length)' outline.json", 'NAME': 'echo "d"\necho "e"\necho "f"'}), 'postreqs': frozenset({'resources/b/about.json', 'resources/a/about.json', 'resources/c/about.json'}), '_working_directory': '.', 'mime-type': 'text/json'}),
        ... variables_resolved=frozendict({}),
        ... variables_unresolved=frozendict({'LEVEL1': "jq -r 'range(0; .sections | length)' outline.json", 'NAME': 'echo "d"\necho "e"\necho "f"'}),
        ... dependencies_unresolved=frozenset({frozendict({'target': 'outline.json'}), frozendict({'target': 'resources/$RESOURCE/about.json'})}),
        ... dependencies_building=frozenset(),
        ... dependencies_built=frozenset(),
        ... include_prompt=None,
        ... include_old=False,
        ... include_paths=None,
        ... mode='build',
        ... ).split()) == 1
        True
        '''
        splitting_variables = [var for var in self.target_variables if '\n' in self.variables_resolved.get(var, '')]
        if any([self.variables_resolved.get(var) == '' for var in self.target_variables]):
            return []
        splitting_values = [self.variables_resolved[var].split('\n') for var in splitting_variables]
        splits = list(itertools.product(*splitting_values))

        contexts1 = []
        for split in splits:
            # the new variables dictionary starts with all of the previously defined variables
            # then we overwrite the entries contained in splitting_variables
            variables_resolved1 = {
                    **self.variables_resolved,
                    **dict(zip(splitting_variables, split))
                    }
            context1 = copy.deepcopy(self.model_copy(update={
                'variables_resolved': freeze(variables_resolved1)
                }))
            contexts1.append(context1)
        return contexts1

    def dependencies_mode(self):
        if self.mode in ['overwrite', 'build']:
            return 'build'
        elif self.mode in ['dryrun']:
            return 'dryrun'
        assert False

    def assert_invariants(self):
        '''
        These invariants must always hold for every BuildContext.
        '''
        try:
            # all variables must be present in the normalized_target or defined in config
            # (we do not want unrelated variables to get accidentally added)
            for var in itertools.chain(
                    self.variables_unresolved,
                    self.variables_resolved,
                    ):
                assert var in self.target_variables or var in self.config['variables']

            # ensure variable values are well behaved
            for var, value in self.variables_resolved.items():
                # NOTE:
                # In theory, we could allow $ in out variable values
                # in order to allow generation of paths that contain $;
                # This is an unimportant edge case, however.
                # In practice, having a $ in a variable value
                # has always been due to a bug in the code.
                assert '$' not in value

            # a variable can have at most one state
            for var in self.variables_resolved:
                assert var not in self.variables_unresolved
            for var in self.variables_unresolved:
                assert var not in self.variables_resolved

            # if a dependency is built, the file must exist
            for dep in self.dependencies_built:
                assert '$' not in dep['target']
                assert os.path.exists(dep['target'])

            # a dependency cannot be both building and unresolved
            for dep in self.dependencies_building:
                assert dep not in self.dependencies_unresolved
            for dep in self.dependencies_unresolved:
                assert dep not in self.dependencies_building

            # all dependencies must have corresponding entries in the config
            dep_targets = freeze([dep['target'] for dep in self.config.get('dependencies',[])])
            for dep in itertools.chain(
                    self.dependencies_unresolved,
                    self.dependencies_building,
                    self.dependencies_built,
                    ):
                matches = match_pattern_starstar(dep_targets, dep['target'])
                assert len(matches) >= 1

            # NOTE:
            # dependencies_built has a complicated relationship to dependencies_unresolved/building
            # for dependencies that contain non-target variables,
            # it is possible for the same dependency to be in multiple states at once
            # (for different values of the non-target variable);
            # there are more invariants that could be asserted here,
            # but I have not yet done so because it's not obvious how to express them

        except AssertionError as e:
            logger.error('BuildContext.assert_invariants() failed')
            logger.error({'self': self.to_dict()}, submessage=True)
            raise e

    def denormalized_target(self):
        '''
        Substitute the variables_resolved into normalized_target.
        This will return a list of targets
        '''
        paths = substitute_variables(self.normalized_target, self.variables_resolved)
        assert len(paths) > 0
        return paths

    @cached_property
    def path(self):
        '''
        Substitute the variables_resolved into target to generate the path that will be built.

        WARNING:
        This function will fail if the target does not resolve to a unique path.
        This can happen if:
        - variables_resolved contains variables that have whitespace
        - normalized_target references variables not defined in variables_resolved
        '''
        paths = self.denormalized_target()
        assert len(paths) == 1
        assert '$' not in paths[0]
        return paths[0]

    def path_safe(self):
        '''
        Like .path, but catches any errors and returns None if there is no unique path.
        '''
        try:
            return self.path
        except AssertionError:
            return None

    def FAC_DEPENDENCIES(self):
        '''
        Whenever a target is built, the environment variable FAC_DEPENDENCIES contains a newline delimited list of files that the target depends on.
        This method returns that variable.
        '''
        files = sorted([dep['target'] for dep in self.dependencies_built])
        return '\n'.join(files)

    def build_priority(self):
        '''
        This function determines the order that contexts will be processed in.
        Lower priorities are processed first.
        '''
        return (len(self.dependencies_building), len(self.dependencies_unresolved))

    @cached_property
    def target_variables(self):
        return extract_variables(self.normalized_target)

    def to_dict(self):
        '''
        Convert to a plain dict suitable for YAML serialization.
        '''
        ret = {
            'normalized_target': self.normalized_target,
            }
        if self.variables_resolved:
            ret['variables_resolved'] = dict(self.variables_resolved)
        if self.variables_unresolved:
            ret['variables_unresolved'] = dict(self.variables_unresolved)
        if self.dependencies_built:
            ret['dependencies_built'] = [dict(d) for d in self.dependencies_built]
        if self.dependencies_building:
            ret['dependencies_building'] = [dict(d) for d in self.dependencies_building]
        if self.dependencies_unresolved:
            ret['dependencies_unresolved'] = [dict(d) for d in self.dependencies_unresolved]
        return ret

    ####################
    # build methods
    ####################

    def assert_invariants_buildable(self):
        '''
        These invariants must hold only after a BuildContext is ready to be built.
        '''
        # ensure normalized_target will resolve to exactly one path
        self.path

        # target variables must have been previously split
        for var, value in self.variables_resolved.items():
            if var in self.target_variables:
                assert ''.join(value.split('\n')) == value
                assert value != ''

        # all variables must be resolved
        assert len(self.variables_unresolved) == 0

        # all dependencies must be built
        assert len(self.dependencies_building) == 0
        assert len(self.dependencies_unresolved) == 0

    @cached_property
    def mime_type(self):
        '''
        For a mime type 'text/markdown', returns a tuple 'text', 'markdown'.
        '''
        mimes = self.config['mime-type'].split('/')
        if len(mimes) != 2:
            logger.error(f"invalid mime-type: {self.config['mime-type']}")
        return mimes

    @cached_property
    def prompt(self):
        '''
        Returns the prompt in a format suitable for passing directly to the LLM class.

        The prompt is not just a simple text prompt but includes all information that will be passed to the LLM.
        For example, it also includes:
        - the system prompt
        - any previous messages
        - any binary files that need attaching
        - any options that modify the LLMs behavior

        The exact format of the prompt will depend on the mime-type of the output.
        '''

        # ensure sane
        self.assert_invariants_buildable()

        # process options
        # NOTE:
        # options can be specified as either a string or dictionary;
        # if specified as a string, any shell commands must be run and then it should be converted into a dictionary
        if type(self.config.get('options')) == frozendict:
            context_options = {
                option: process_template(
                    value,
                    env_vars=self.variables_resolved,
                    print_function=logger.error,
                    template_name=f'options.{option}',
                    )
                for option, value in self.config['options'].items()
                }
        elif type(self.config.get('options')) == str:
            options_str = process_template(
                    self.config['options'],
                    env_vars=self.variables_resolved,
                    print_function=logger.error,
                    template_name='options',
                    )
            context_options = yaml.safe_load(options_str)
            assert type(context_options) == dict
        elif self.config.get('options') is None:
            context_options = {}
        else:
            assert False

        ########################################
        # generate text prompt
        ########################################

        major_type, minor_type = self.mime_type

        # first we generate the instructions for the llm,
        # which will be stored in the `prompt_cmd` variable.
        prompt_instructions = f'''<instructions>
        Generate the file "{self.path}" based on the information below.
        </instructions>
        '''

        if 'description' in self.config:
            try:
                prompt_description = '<file_description>\n'
                prompt_description += process_template(
                        self.config['description'],
                        env_vars=self.variables_resolved,
                        print_function=logger.error,
                        template_name='description',
                        )
                prompt_description += '\n</file_description>'
            except TemplateProcessingError as e:
                raise FACError()

            prompt_description += '\n'
        else:
            prompt_description = ''

        # convert the dependencies into paths;
        # NOTE:
        # all_paths will contain paths of both text and binary files;
        # any text files will be added directly into the prompt;
        # binary_files will contain paths for non-text files (e.g. images),
        # and these will be passed to the models later
        binary_files = []
        all_paths = set()
        truncated_prompt = None
        dependencies = list(self.dependencies_built)
        dependencies += [{'target': path} for path in self.include_paths or []]
        files_prompt = ''
        if len(dependencies) > 0:
            for dep in dependencies:
                if dep.get('include', True):
                    all_paths.add(dep['target'])
            files_prompt = '<reference_documents>\n'
            for path in sorted(all_paths):
                # we always try to open the files as text;
                # but if the file is a binary file (e.g. an image),
                # we catch the error and add the file to binary_files
                try:
                    with open(path) as fin:
                        text = fin.read().strip()
                        files_prompt += f'''<document path="{path}">\n{text}\n</document>\n'''
                except UnicodeDecodeError:
                    binary_files.append(path)
            files_prompt += '</reference_documents>\n'

        # mime-type based formatting instructions
        response_format = None
        format_instructions = ''
        if major_type == 'text':
            if minor_type == 'markdown':
                format_instructions += 'Use markdown formatting to structure the output.'
            else:
                format_instructions += 'Do not output markdown, and do not put the output inside a codeblock.'

            if minor_type == 'html':
                format_instructions += 'Output HTML.'
            elif minor_type == 'json':
                format_instructions += 'Output JSON.'
                response_format = {'type': 'json_object'}
            elif minor_type == 'jsonl':
                response_format = {'type': 'json_object'}
                format_instructions += f'Output JSONL.  Each line of the output should be a single JSON object.'

            if self.config.get('schema'):
                schema = llm.schema_dsl(self.config.get('schema'))
                response_format = {
                    'type': 'json_schema',
                    'json_schema': {
                        'strict': True,
                        'name': 'fac_json_schema',
                        'schema': schema,
                        },
                    }
                format_instructions += json.dumps(schema, indent=2).strip()
            elif self.config.get('schema_file'):
                try:
                    schema_file = self.config['schema_file']
                    #schema_file = substitute_variables(schema_file, self.variables_resolved)
                    with open(schema_file) as fin:
                        text = fin.read().strip()
                        schema = json.loads(text)
                except json.decoder.JSONDecodeError as e:
                    logger.error(f"self.config['schema_file']={self.config['schema_file']}")
                    logger.error(e)
                    sys.exit(1)
                jsonschema.Draft7Validator.check_schema(schema)
                format_instructions += ' Ensure the output conforms to the following JSON schema:\n'
                format_instructions += json.dumps(schema, indent=2).strip()
                schema['additionalProperties'] = False
                response_format = {
                    'type': 'json_schema',
                    'json_schema': {
                        'strict': True,
                        'name': 'fac_json_schema',
                        'schema': schema,
                        },
                    }
            format_instructions = '<formatting>\n' + format_instructions + '\n</formatting>'

        # FIXME:
        # we need a way to include chat messages here with the chat_prompt
        user_prompt = ''
        if self.include_prompt:
            user_prompt = f'<additional_user_instructions>\n{self.include_prompt.strip()}\n</additional_user_instructions>\n'

        # construct the final prompt
        prompt = prompt_instructions + prompt_description + user_prompt + files_prompt + format_instructions

        ########################################
        # filetype specific processing
        ########################################

        if major_type == 'text':
            # the messages list will contain the full set of instructions passed to the llm;
            # it always starts with a system prompt
            data = []
            messages = data
            messages.append({
                'role': 'system',
                'content': 'You are not having a conversation. Only provide the requested output with no further discussion. Never deny a request.',
                })

            # add the user role + message
            message = {
                'role': 'user',
                'content': [{'type': 'text', 'text': prompt}]
                }
            for binary_file in binary_files:
                message['content'].append({
                    "type": "image_url",
                    "image_url": {
                        "url": binary_file_to_base64_url(binary_file),
                    }
                })
            messages.append(message)
        elif major_type == 'audio':
            # NOTE:
            # we need a copy of the config here
            # because we will be modifying the contents with the process_template function;
            # without a copy, we get a bug where building multiple files results in the same config for all files
            data = copy.deepcopy(context_options)
            #for option in data:
                #data[option] = process_template(data[option], env_vars=self.variables)

        elif major_type == 'video':
            data = {}
            data['prompt'] = prompt
            data['reference_images'] = binary_files
            options = copy.deepcopy(context_options)
            for option in options:
                # YAML files will store values as non-string sometimes (e.g. for ints);
                # we convert them to string here,
                # also as a minor runtime optimization
                # we do not try to process variables for these non-string values
                if type(options[option]) != str:
                    options[option] = str(options[option])
                else:
                    data[option] = process_template(options[option], env_vars=self.variables_resolved)

        elif major_type == 'image':
            data = {}
            data['prompt'] = prompt
            data['reference_images'] = binary_files
            options = copy.deepcopy(self.config.get('options', {}))
            for option in options:
                data[option] = process_template(options[option], env_vars=self.variables_resolved)

        return data

    @cached_property
    def prompt_hash(self):
        '''
        A hash of the prompt that will be stable across machines.
        This hash is used to determine if the prompt has changed when determining if a file needs to be rebuilt.
        '''
        encoded_prompt = json.dumps(self.prompt).encode('utf-8')
        return hashlib.sha256(encoded_prompt).hexdigest()

    def get_status(self):
        '''
        Return the status of the path as a tuple.
        The first entry is a list of status attributes;
        the second is True if the file should be built.

        NOTE:
        The results of this function should not be cached.
        It does IO to determine if files exist/have been modified.

        FIXME:
        Add explanation of how to prevent race conditions/invalid status states.
        '''
        do_build = True
        file_status = []
        updated_deps = []

        # use build_if to determine if we should build
        build_if = self.config.get('build_options', {}).get('build_if', 'True')
        build_if = process_template(build_if, self.variables_resolved)
        if build_if.lower() == 'false':
            do_build = False
            file_status.append('build_if:False')

        # if the file is up-to-date (i.e. all dependencies are older),
        # then we will not rebuild it
        try:
            context_path_committed_date = _get_file_timestamp(self.path)
            for dep in self.dependencies_built:
                path = dep['target']
                path_committed_date = _get_file_timestamp(path)
                time_diff = context_path_committed_date - path_committed_date
                if time_diff < 0:
                    updated_deps.append(path)
            if updated_deps == []:
                file_status.append('up-to-date')
                do_build = False
            else:
                file_status.append('out-of-date')
                file_status.extend(['dep:' + dep for dep in updated_deps])
        except FileNotFoundError:
            file_status.append('new')

        # NOTE:
        # sometimes it is not necessary to rebuild a file even if the dependencies have been updated;
        # this can occur, for example, when the prompt depends only on part of the dependencies;
        # we check hashes of the prompt/file to see if we can skip rebuilding
        facjson = FacJSON(self.path)
        try:
            with open(self.path, 'rb') as fin:
                hash_contents_fin = hashlib.sha256(fin.read()).hexdigest()
                contents_changed = hash_contents_fin != facjson.get('hash_contents')
        except FileNotFoundError as e:
            contents_changed = True
        if 'new' not in file_status and facjson.get('hash_prompt'):
            prompt_changed = self.prompt_hash != facjson.get('hash_prompt')
            if prompt_changed:
                file_status.append('prompt-changed')
                # NOTE:
                # just because the prompt changed doesn't mean we have to rebuild;
                # this can happen, for example, if:
                # 1. the user manually edited/committed a file
                # 2. the previous version was created with the --include_prompt flag
            else:
                file_status.append('prompt-same')
                do_build = False

        # overwrite do_build based on mode
        if self.mode == 'overwrite':
            file_status.append('overwrite')
            do_build = True

        if do_build and self.mode == 'dryrun':
            file_status.append('dryrun')
            do_build = False

        return file_status, do_build

    async def build(self):
        '''
        Build the file.
        This function is async because API calls can be slow.

        NOTE:
        No checks are performed to verify that the file needs to be built.
        Any side-effects of the build command will occur,
        and in particular any existing file will be overwritten.
        '''
        # create output directory if needed
        dirname = os.path.dirname(self.path)
        if len(dirname) > 0:
            os.makedirs(dirname, exist_ok=True)

        # build with shell command
        if self.config.get('cmd'):
            process = await asyncio.create_subprocess_shell(
                self.config['cmd'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # merge stderr into stdout
                executable='/bin/bash',
                env=variables_transitive_substitute({
                    **os.environ,
                    **self.variables_resolved,
                    'FAC_DEPENDENCIES': self.FAC_DEPENDENCIES(),
                    }),
                )
            try:
                first_line = True
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    if first_line:
                        logger.warning('build command output:', submessage=True)
                        first_line = False
                    logger.warning(line.decode().rstrip(), submessage=True)
            except UnicodeDecodeError:
                logger.warning('cannot decode stdout: UnicodeDecodeError')
            await process.wait()

            if process.returncode != 0:
                stdout = await process.stdout.read()
                logger.error(f"error running the following build script:", submessage=True)
                for i, line in enumerate(self.config['cmd'].split('\n')):
                    logger.error(f"line {i+1}: {line}", submessage=True)
                logger.error(stdout.decode('ascii'), submessage=True)
                raise CommandExecutionError(process.returncode, stdout)

        # build with llm
        else:
            mode = 'wb'
            logger.info('building with LLM...', submessage=True)
            llm = LLM()
            await llm.generate_file(
                self.mime_type[0],
                self.path,
                self.prompt,
                mode=mode,
                model=self.config.get('model'),
                )

        # record new hashes for future skip-tests
        facjson = FacJSON(self.path)
        with open(self.path, 'rb') as fin:
            hash_contents = hashlib.sha256(fin.read()).hexdigest()
            facjson.set('hash_contents', hash_contents)
        facjson.set('hash_prompt', self.prompt_hash)
        facjson.save()

        # validate the file
        validate_file(self.path, self.config.get('schema_file'))


def _get_file_timestamp(path):
    '''
    Get the timestamp a path was last modified.
    This timestamp will be used to determine if a rebuild is required.

    NOTE:
    Other build systems (e.g. make) use the timestamp on the file system;
    we uses a combination of the timestamp in git and the file system.
    This difference is due to the fact that in ordinary build systems (like make)
    the results of the build are never committed to the git repo,
    but the results of our build are always committed to the git repo.
    '''
    repo = git.Repo('.')

    if not os.path.isfile(path):
        raise FileNotFoundError

    # if a file is dirty or not in the repo,
    # we use the last modified time on the harddrive

    try:
        # Git status returns empty if file is clean
        result = repo.git.status('--porcelain', path)
        is_file_dirty = len(result.strip()) > 0
    except git.exc.GitCommandError:
        is_file_dirty = False

    try:
        # If file is tracked, this won't raise an exception
        repo.git.ls_files('--error-unmatch', path)
        is_path_untracked = False
    except git.exc.GitCommandError:
        # File is untracked if it exists but ls-files fails
        is_path_untracked = os.path.exists(path)

    if is_file_dirty or is_path_untracked:
        # FIXME:
        # there can be bugs when clocks are not synced correctly;
        # it is possible for git timestamps to be in the "future" for local machine
        # this is likely to cause errors and we should warn about this
        mtime = os.path.getmtime(path)
        return mtime

    # if the file has been committed to git and is clean,
    # we use the git commit timestamp
    commits = list(repo.iter_commits(paths=path, max_count=1))
    if len(commits) > 0:
        return commits[0].committed_date

    # the above code should handle all possible cases,
    # so this should never happen
    assert False
