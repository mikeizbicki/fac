'''
This file contains all code for managing git.
'''

import git
import os
import time

from fac.Logging import logger, with_subtree


def assert_git_sane(allow_dirty=False):
    '''
    Used on program startup.
    Ensures that all Job instances will correctly commit.
    '''
    repo = git.Repo('.')

    if repo.working_dir != os.getcwd():
        logger.error('must be in root of git repo')
        raise DirtyRepo()

    if repo.is_dirty(untracked_files=True):
        if allow_dirty:
            logger.warning('git repo is dirty but proceeding with --allow_dirty')
        else:
            logger.error('git repo is dirty')
            logger.error('you can clean the repo by committing all changes', submessage=True)
            logger.error('you can clean the repo by deleting all changes with `git checkout . && git clean -fd`', submessage=True)
            logger.error('you can allow running with a dirty repo using --allow_dirty or --auto_commit=False', submessage=True)
            raise DirtyRepo()


class Job:
    '''
    Multiple jobs can be run sequentially or concurrently in BuildState.
    This class tracks which paths/contexts correspond to which build jobs.
    The main purpose of tracking is so we can commit all modified files at once and with an appropriate commit message within the finalize() method.
    '''
    job_count = 0

    def __init__(self, build_cmd, auto_commit=True):
        self.build_cmd = build_cmd
        self.repo = git.Repo('.')
        self.auto_commit = auto_commit
        self.contexts = set()
        self.paths = set()
        self.start_time = time.time()
        self.end_time = None
        self.job_id = Job.job_count
        Job.job_count += 1

    def register_context(self, context):
        self.contexts.add(context)
        if context.path_safe():
            self.paths.add(context.path_safe())

    def assert_invariants_finalizable(self):
        # ensure finalize has not already been called
        assert self.end_time is None

        # ensure that all contexts have corresponding built paths
        for context in self.contexts:
            if context.path_safe() and context.mode != 'dryrun':
                assert context.path_safe() in self.paths

    def finalize(self):
        '''
        This method is called after all paths are finally built.
        The main purpose is to commit all built paths to git.
        '''
        self.assert_invariants_finalizable()
        self.end_time = time.time()

        # add/commit the built targets
        def try_add(path):
            try:
                self.repo.git.add(path)
            except git.exc.GitCommandError:
                pass
        if self.auto_commit:
            try_add('fac.yaml')
            try_add('.fac.jsonl')
            for context in self.contexts:
                if context.path_safe():
                    try_add(context.path)
                    if context.config.get('build_options', {}).get('update_meta'):
                        dirname = os.path.dirname(context.path)
                        filename = os.path.basename(context.path)
                        try_add(f'./{dirname}/.{filename}.facjson')
                        try_add(f'./{dirname}/.{filename}.fac.log')
            commit_message=f'[bot] {self.build_cmd}'

            # the if condition below checks if we actually added files;
            # we only commit if files were actually added;
            # otherwise a large ugly warning will appear
            if self.repo.index.diff('HEAD'):
                self.repo.git.commit('-m', commit_message)
