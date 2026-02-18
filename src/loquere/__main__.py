#!/usr/bin/env python3
"""
loquere - chat with the build system
"""

from datetime import datetime, date
from pathlib import Path
import argparse
import fcntl
import glob
import json
import logging
import os
import subprocess

import git

from fac.__main__ import BuildSystem
from fac.Logging import logger
import fac.LLM


class Session:

    log_dir = '.loquere'
    system_prompt = 'Keep your response short, between 5-20 lines.'

    def __init__(self, session_id=None):

        self.repo = git.Repo('.')
        os.makedirs(self.log_dir, exist_ok=True)

        # create the session_id
        if session_id is None:
            self.session_id = self.get_default_session_id()
        else:
            self.session_id = session_id

        # create the log folders for the session
        self.session_dir = f'.loquere/{self.session_id}/'
        self.log_file = os.path.join(self.session_dir, 'log.jsonl')

        # log satus
        messages = self.get_session_messages()
        if len(messages) == 0:
            logger.info(f'Starting new session: "{self.session_id}".')
        else:
            logger.info(f'Continuing prev session: "{self.session_id}". There are {len(messages)} messages.')

        # initialize the LLM;
        self.llm = fac.LLM.LLM()

    ########################################
    # Util Methods
    ########################################

    def get_default_session_id(self):
        '''
        Every session has a unique session_id,
        and a session is "dirty" if its corresponding git folder has any dirty files.
        There should be at most one dirty session at any time.

        If there are no currently dirty sessions,
        then the default session_id is a combination of git branch and timestamp.
        (This information can be useful to help group related sessions together.)

        If there is a dirty session,
        then the default session_id is the session_id of that session.
        '''

        # find dirty files in self.log_dir
        all_dirty_files = (self.repo.untracked_files +
                          [item.a_path for item in self.repo.index.diff(None)] +
                          [item.a_path for item in self.repo.index.diff("HEAD")])
        dirty_sessions = []
        for item in os.listdir(self.log_dir):
            item_path = os.path.join(self.log_dir, item)
            if os.path.isdir(item_path):
                dirty_files = (f.startswith(item_path + os.sep) for f in all_dirty_files)
                if any(dirty_files):
                    dirty_sessions.append(item)

        # create new session_id
        if len(dirty_sessions) == 0:
            branch = self.repo.active_branch.name
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            session_id = f"{branch}__{timestamp}"
            return session_id

        # continue with prev session_id
        elif len(dirty_sessions) == 1:
            session_id = os.path.basename(dirty_sessions[0])
            return session_id

        # this should never happen
        else:
            raise ValueError('Multiple ongoing sessions')

    ########################################
    # Main Methods
    ########################################

    def get_session_messages(self):
        '''
        Construct the messages list that represents the ongoing chat.
        '''
        messages = []
        try:
            with open(self.log_file) as fin:
                for line in fin.readlines():
                    data = json.loads(line)
                    messages.append({
                        'role': 'user',
                        'content': data.get('message'),
                        })
                    messages.append({
                        'role': 'assistant',
                        'content': data.get('response'),
                        })
        except FileNotFoundError:
            pass
        return messages

    def send_message(self, message):
        '''
        Appends message to the ongoing chat and sends it to the LLM.
        '''

        # build the messages for the chat LLM
        # these messages contain additional system prompt and background project info that is useful for determining which tools to use
        messages_chat = [{'role': 'system', 'content': self.system_prompt}]
        messages_chat.extend(self.get_session_messages())
        messages_chat.append({
                'role': 'user',
                'content': message
            })
        response, usage = self.llm.text(
            messages_chat,
            # model='openai/gpt-5-mini'
            # model='openai/gpt-5'
            # model='groq/llama-3.3-70b-versatile'
            # model='groq/meta-llama/llama-4-maverick-17b-128e-instruct'
            # model='groq/meta-llama/llama-4-scout-17b-16e-instruct'
            #model='openrouter/qwen/qwen3-coder',
            #model='anthropic/claude-3-5-haiku-latest',
            model='anthropic/claude-sonnet-4-0',
            # model='cerebras/llama-3.3-70b'
            # model='cerebras/llama-4-scout-17b-16e-instruct'
            #model='cerebras/qwen-3-32b'
            )

        # ping the user if a tool was used
        if usage.tools_used:
            ping_user()

        # log the chat interaction
        os.makedirs(self.session_dir, exist_ok=True)
        with open(self.log_file, "a") as f:
            log_entry = {
                "time": datetime.now().isoformat(),
                "message": message,
                "response": response,
                "cost": usage.total_cost(),
            }
            f.write(json.dumps(log_entry) + "\n")

        return response

    ########################################
    # repl
    ########################################

    def repl(self):
        '''
        '''
        # this import modifies the behavior of the `input` function
        # to give more friendly repl-like behavior
        import readline

        # The infinite loop below creates a repl-like environment for when the script is called without a message commmand line argument.
        # We trap exceptions for common methods of leaving the environment.
        self.repl_done = False
        while not self.repl_done:
            try:
                message = input('loquere> ').strip()

                # handle built-in commands
                commands = self.get_commands()
                firstword = message.split()[0]
                if firstword in commands:
                    response = commands[firstword](message)
                else:
                    # if not a built-in command, send to LLM
                    response = self.send_message(message)
                    # FIXME:
                    # It would be more user-friendly to move to the streaming API at some point so that the user can see the response as it is being generated.
                    # This slightly complicates the logging of the chat messages
                    # and requires a lot of reworking in the LLM class.
                blue_response = "\033[94m" + response + "\033[0m"
                print(blue_response)

            # pressing ^C will interrupt the current prompt and not do any actions
            except KeyboardInterrupt:
                print()
                pass

            # pressing ^D will end the program
            except EOFError:
                # printing a newline ensures that the shell prompt will start on its own line
                print()
                return 0

    ########################################
    # commands
    ########################################

    def get_commands(self):
        '''
        Get all command methods from this class.
        Returns a dictionary with command names as keys and method references as values.
        '''
        commands = {}
        for attr_name in dir(self):
            if attr_name.startswith('cmd_'):
                method = getattr(self, attr_name)
                if callable(method):
                    command_name = attr_name[4:]  # Remove 'cmd_' prefix
                    commands[command_name] = method
        return commands

    def cmd_load(self, message):
        '''
        '''
        glob_pattern = ' '.join(message.split()[1:])

        # load the documents
        response = ''
        paths_loaded = []
        for path in sorted(glob.glob(glob_pattern)):
            with open(path) as fin:
                response += f'''<document path="{path}">\n{fin.read().strip()}\n</document>\n'''
                paths_loaded.append(path)

        # register the new info
        os.makedirs(self.session_dir, exist_ok=True)
        with open(self.log_file, "a") as f:
            log_entry = {
                "time": datetime.now().isoformat(),
                "message": message,
                "response": response,
                "cost": 0,
            }
            f.write(json.dumps(log_entry) + "\n")

        # generate output string
        if len(paths_loaded) == 0:
            return f'{glob_pattern} does not match any files.'
        elif len(paths_loaded) == 1:
            return f'Loaded: {path}'
        else:
            return f'Loaded:\n - ' + '\n - '.join(paths_loaded)

    def cmd_note(self, message):
        '''
        Register a note without having the llm respond directly.
        '''
        response = "Noted."
        # register the new info
        os.makedirs(self.session_dir, exist_ok=True)
        with open(self.log_file, "a") as f:
            log_entry = {
                "time": datetime.now().isoformat(),
                "message": message,
                "response": response,
                "cost": 0,
            }
            f.write(json.dumps(log_entry) + "\n")
        return response


    def cmd_fac(self, message):
        '''
        Run the fac command to build targets.
        '''
        target = ' '.join(message.split()[1:])
        messages = self.get_session_messages()
        build_system = BuildSystem(
            include_chat=json.dumps(messages, indent=4),
            overwrite=True,
            include_old=True,
            auto_commit=False,
            )
        build_system.llm = self.llm
        with build_system:
            build_system.build_targets([target])

        response = "Done."
        # register the new info
        os.makedirs(self.session_dir, exist_ok=True)
        with open(self.log_file, "a") as f:
            log_entry = {
                "time": datetime.now().isoformat(),
                "message": message,
                "response": response,
                "cost": 0,
            }
            f.write(json.dumps(log_entry) + "\n")
        return response

    def cmd_exit(self, line):
        '''
        Exit the loquere repl session.
        '''
        self.repl_done = True
        return 'Exiting without committing.'

    def cmd_commit(self, line):
        '''
        Commit all untracked files to the git repo.
        This method will at a minimum commit the session log and any files built by the session.

        WARNING:
        This method internally runs `git add .`.
        Therefore all files which have been created (and are not explicitly in .gitignore) will be added to the repo.
        This includes any sensitive files (e.g. with API keys) that you might have.
        '''

        commit_message = self.send_message('generate a commit message that summarizes our conversation')
        commit_message = f'[loquere] {commit_message}'
        self.repo.git.add('.')
        self.repo.git.commit('-m', commit_message)
        self.repl_done = True
        return commit_message


################################################################################
# utils
################################################################################

def is_direct_child(filepath, folder):
    '''
    Check if file is directly in the folder (not in subdirectories)

    >>> is_direct_child('/home/user/file.txt', '/home/user')
    True
    >>> is_direct_child('/home/user/subdir/file.txt', '/home/user')
    False
    >>> is_direct_child('/home/other/file.txt', '/home/user')
    False
    >>> is_direct_child('/home/user', '/home/user')
    False
    >>> is_direct_child('C:\\Users\\file.txt', 'C:\\Users')
    True
    >>> is_direct_child('C:\\Users\\subfolder\\file.txt', 'C:\\Users')
    False
    '''
    if not filepath.startswith(folder + os.sep):
        return False
    relative_path = filepath[len(folder + os.sep):]
    return os.sep not in relative_path


def ping_user():
    '''
    This function plays a ping sound which can be used to let the user know that a long running chat command has finished.
    '''

    module_dir = Path(__file__).parent
    wav_path = module_dir / 'data' / 'ping.wav'

    try:
        subprocess.Popen(["paplay", wav_path])
                         #stdout=subprocess.DEVNULL,
                         #stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise ValueError("paplay not found")


################################################################################
# main script
################################################################################


def main():
    parser = argparse.ArgumentParser(description="Chat with the build system")
    parser.add_argument('--session_id', default=None)
    args = parser.parse_args()
    logger.setLevel('INFO')
    session = Session(session_id=args.session_id)
    session.repl()


if __name__ == '__main__':
    main()
