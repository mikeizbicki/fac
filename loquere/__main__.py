#!/usr/bin/env python3
"""
loquere - chat with the build system
"""

from datetime import datetime, date
import argparse
import fcntl
import json
import logging
import os

from fac.Logging import logger
import fac.LLM

################################################################################
# tools
################################################################################
tools = []
callables = {}

def create_file(path, content):
    '''
    >>> create_file('/test', 'test')
    Traceback (most recent call last):
    ...
    ValueError: Path is not relative to pwd
    '''

    print(f'create_file({path}, content=...)')

    import pathlib
    path = pathlib.Path(os.path.abspath(path))
    pwd = os.getcwd()
    if not path.is_relative_to(pwd):
        raise ValueError('Path is not relative to pwd')

    with open(path, 'x') as fout:
        fout.write(content)

tools.append({
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a file with the specified content",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "A filename or relative path for where the file will be created.  Absolute paths are not allowed, and the `..` parent special file is also not allowed.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content of the created file."
                    }
                },
                "required": ["path", "content"],
            },
        },
    })
callables['create_file'] = create_file

'''
    {
        "type": "function",
        "function": {
            "name": "build_target",
            "description": "Uses the `fac` command to build a target specified in the `fac.yaml` file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "A target to build from the `fac.yaml` file. The input may specify none, some, or all of the variables in the unqualified target name.",
                    },
                },
                "required": ["target"],
            },
        },
    }
'''


class Session:

    system_prompt = '''
You are a make-like build tool designed to help users create projects with LLMs.
Assume your users are highly technical and use professional, concise language.
All responses should be as short as possible and not include any chitchat.
Never suggest tasks for the user unless they explicitly ask for them.
A typical response should be between 1-3 sentences, but a longer response up to 20 sentences may sometimes be appropriate if the user has asked for more detail.
Answers of a single word or phrase (even if not a complete sentence) are ideal.
Use markdown lists whenever appropriate.
If the user gives you a "command", you should find the appropriate tool to use or tell them you don\'t know how to help them.
'''

    def __init__(self, session_id=None):

        if session_id is None:
            # The default session id is a combination of:
            # 1. the current date,
            # 2. the parent's pid,
            # 3. the current process's pid.
            # This ensures that related sessions can be identified.
            # It is theoretically possible for session id's to collide,
            # but this is extremely unlikely in practice.
            current_date = date.today()
            ppid = os.getppid()
            pid = os.getpid()
            self.session_id = f"{current_date}-{ppid}-{pid}"
        else:
            self.session_id = session_id

        self.log_dir = f'.loquere/{self.session_id}/'
        os.makedirs(self.log_dir, exist_ok=True)

        self.log_file = self.log_dir + 'log.jsonl'

        self.llm = fac.LLM.LLM()

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

        # send the message to the LLM
        messages = [{'role': 'system', 'content': self.system_prompt}]
        messages.extend(self.get_session_messages())
        messages.append({
                'role': 'user',
                'content': message
            })
        response, usage = self.llm.text(messages, tools=tools, callables=callables)

        # log the chat interaction
        with open(self.log_file, "a") as f:
            log_entry = {
                "time": datetime.now().isoformat(),
                "message": message,
                "response": response,
                "cost": self.llm._total_price(usage),
                "usage": usage
            }
            f.write(json.dumps(log_entry) + "\n")

        return response


def main():
    parser = argparse.ArgumentParser(description="Chat with the build system")
    parser.add_argument('--session_id', default=None)
    parser.add_argument('message', nargs='?')
    args = parser.parse_args()
    logger.setLevel('WARNING')

    # this import modifies the behavior of the `input` function
    # to give more friendly repl-like behavior
    import readline

    # The infinite loop below creates a repl-like environment for when the script is called without a message commmand line argument.
    # We trap exceptions for common methods of leaving the environment.
    done = False
    try:
        session = Session(session_id=args.session_id)
        while not done:
            if args.message:
                message = args.message
                done = True
            else:
                message = input('loquere> ')
            response = session.send_message(message)
            blue_response = "\033[94m" + response + "\033[0m"
            print(blue_response)
            # FIXME:
            # It would be more user-friendly to move to the streaming API at some point so that the user can see the response as it is being generated.
            # This slightly complicates the logging of the chat messages
            # and requires a lot of reworking in the LLM class.

    except (EOFError, KeyboardInterrupt):
        # printing a newline ensures that the shell prompt will start on its own line
        print()

    return 0


if __name__ == '__main__':
    main()
