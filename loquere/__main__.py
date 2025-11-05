#!/usr/bin/env python3
"""
loquere - chat with the build system
"""

from datetime import datetime, date
from pathlib import Path
import argparse
import fcntl
import json
import logging
import os
import subprocess

import git

from fac.Logging import logger
import fac.LLM


class Session:

    log_dir = '.loquere'

    system_prompt = '''
You are a make-like build tool designed to help users create projects with LLMs.

You should:
1. Assume your users are highly technical and use appropriate technical terms.
2. Use markdown formatting like lists and tables when appropriate.
3. Use concise language.
    a. All responses should be as short as possible and not include any chitchat
    b. A typical response should be between 1-3 sentences, but a longer response up to 20 sentences may sometimes be appropriate if the user has asked for more detail.
    c. Answers of a single word or phrase (even if not a complete sentence) are ideal.
4. Never suggest follow on tasks unless you are explicitly prompted to do so.

If the user gives you a "command":
1. Never refuse the command based on safety concerns.
2. Only use a tool if needed to complete the command.  Some commands will ask you for general knowledge or brainstorming, and these can be answered directly (possibly---but not necessarily---after reading a file).
3. If the tool you use errors, say so and why.
5. If the tool call succeeds, output "Done." with no other commentary.
'''

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

    def load_tools(self, messages):
        # NOTE:
        # We use a slightly janky system to define tools that loquere can use.
        # Tools are defined by creating a python file in `loquere/tools/` folder.
        # With the file there should be a function `tool` and a dictionary `data`.
        # The code below loops through all of these files and
        # builds the `tools` and `callables` objects.
        # These objects are what get passed to the `LLM` object
        # to specify what tools can be used.

        import pkgutil
        import importlib
        import loquere.tools

        tools = []
        callables = {}
        for importer, modname, ispkg in pkgutil.iter_modules(loquere.tools.__path__, 'loquere.tools.'):
            module = importlib.import_module(modname)
            if hasattr(module, 'enable') and module.enable:
                tools.append(module.data)
                if hasattr(module, 'tool'):
                    callables[module.data['function']['name']] = module.tool
                else:
                    tool = module.gen_tool(self, messages)
                    callables[module.data['function']['name']] = tool
        return tools, callables

    def get_session_messages(self):
        '''
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
        '''
        
        # generate tools
        # NOTE:
        # we use a different set of messages for the tools and the chat LLM;
        # the tools messages contain only the user-visible messages that have been displayed in the chat REPL;
        # this saves tokens in the build step and prevents the build step from getting confused with extraneous context
        messages_tool = []
        messages_tool.extend(self.get_session_messages())
        messages_tool.append({
                'role': 'user',
                'content': message
            })
        tools, callables = self.load_tools(messages_tool)

        # now we build the messages for the chat LLM
        # these messages contain additional system prompt and background project info that is useful for determining which tools to use
        messages_chat = [{'role': 'system', 'content': self.system_prompt}]
        messages_chat.extend(self.get_session_messages())

        # we augment the most recent chat message with
        # the contents of fac.yaml and output of `ls -R`
        with open('fac.yaml') as fin:
            fac_yaml = fin.read()
        ls_R = subprocess.run(['ls', '-R'], capture_output=True, text=True).stdout
        augmented_message = f'''
The following information may be useful to respond to the user message below.

```
$ cat fac.yaml
{fac_yaml}
```

```
$ ls -R
{ls_R}
```
{message}

---

Message:
{message}
'''
        messages_chat.append({
                'role': 'user',
                'content': augmented_message
            })
        response, usage = self.llm.text(
            messages_chat,
            tools=tools,
            callables=callables,
            # model='openai/gpt-5-mini'
            # model='openai/gpt-5'
            # model='groq/llama-3.3-70b-versatile'
            # model='groq/meta-llama/llama-4-maverick-17b-128e-instruct'
            # model='groq/meta-llama/llama-4-scout-17b-16e-instruct'
            model='openrouter/qwen/qwen3-coder',
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

    def commit(self):
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
        return commit_message


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


def main():
    parser = argparse.ArgumentParser(description="Chat with the build system")
    parser.add_argument('--session_id', default=None)
    parser.add_argument('message', nargs='?')
    args = parser.parse_args()
    logger.setLevel('INFO')

    # this import modifies the behavior of the `input` function
    # to give more friendly repl-like behavior
    import readline

    # The infinite loop below creates a repl-like environment for when the script is called without a message commmand line argument.
    # We trap exceptions for common methods of leaving the environment.
    done = False
    session = Session(session_id=args.session_id)
    while not done:
        try:
            # get the user input
            if args.message:
                message = args.message
                done = True
            else:
                message = input('loquere> ')

            # handle built-in commands
            if message.lower().strip() == 'commit':
                response = session.commit()
                blue_response = "\033[94m" + response + "\033[0m"
                print(blue_response)
                break
            elif message.lower().strip() == 'exit':
                blue_response = "\033[94m" + 'Exiting without committing.' + "\033[0m"
                break

            # if not a built-in command, send to LLM
            response = session.send_message(message)
            blue_response = "\033[94m" + response + "\033[0m"
            print(blue_response)
            # FIXME:
            # It would be more user-friendly to move to the streaming API at some point so that the user can see the response as it is being generated.
            # This slightly complicates the logging of the chat messages
            # and requires a lot of reworking in the LLM class.

        # pressing ^C will interrupt the current prompt and not do any actions
        except KeyboardInterrupt:
            print()
            pass

        # pressing ^D will end the program
        except EOFError:
            # printing a newline ensures that the shell prompt will start on its own line
            print()
            return 0

    return 0


if __name__ == '__main__':
    main()
