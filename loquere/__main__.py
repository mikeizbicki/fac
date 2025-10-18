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
import subprocess

from fac.Logging import logger
import fac.LLM


class Session:

    system_prompt = '''
You are a make-like build tool designed to help users create projects with LLMs.
Assume your users are highly technical and use professional, concise language.
All responses should be as short as possible and not include any chitchat.
Never suggest follow on tasks unless you are explicitly prompted to do so.
A typical response should be between 1-3 sentences, but a longer response up to 20 sentences may sometimes be appropriate if the user has asked for more detail.
Answers of a single word or phrase (even if not a complete sentence) are ideal.
You have a strong preference for using markdown formatting like lists and tables when appropriate.
If the user gives you a "command":
1. You should find the appropriate tool to use.
2. If no tool is appropriate then say you cannot complete the command and why.
3. If the tool you use errors then you may try again, but also state that:
    a. the original tool calls errored,
    b. why you think that was the case, and
    c. what you did to try to fix the problem.
4. If the tool call succeeded, then do not output a summary of what you have done.
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
        self.llm.default_text_model = 'openai/gpt-5' #-mini'

    def get_system_prompt(self):
        system_prompt = self.system_prompt
        try:
            with open('fac.yaml') as fin:
                yaml = fin.read()
            self.system_prompt = Session.system_prompt + f'''

The project config is specified in the following `fac.yaml` file:
{{yaml}}
'''
        except FileNotFoundError:
            pass

        system_prompt += f'''

In case it is helpful, here is the current output of `ls -R`
'''
        result = subprocess.run(['ls', '-R'], capture_output=True, text=True)
        system_prompt += result.stdout

        return system_prompt

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
            tools.append(module.data)
            if hasattr(module, 'tool'):
                callables[module.data['function']['name']] = module.tool
            else:
                tool = module.gen_tool(messages)
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

        # send the message to the LLM
        messages = [{'role': 'system', 'content': self.get_system_prompt()}]
        messages.extend(self.get_session_messages())
        messages.append({
                'role': 'user',
                'content': message
            })
        tools, callables = self.load_tools(messages)
        response, usage = self.llm.text(
            messages,
            tools=tools,
            callables=callables,
            )

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
    logger.setLevel('INFO')

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
