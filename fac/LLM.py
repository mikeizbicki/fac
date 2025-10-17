
from collections import defaultdict, Counter
import json
import os
import time
import uuid

import openai

from .Logging import logger

def generate_uuid7():
    timestamp = int(time.time() * 1000)
    random_number = uuid.uuid4().int
    uuid7 = (timestamp << 64) | random_number
    return uuid7


class LLM():

    providers = {
        'anthropic': {
            'base_url': 'https://api.anthropic.com/v1/',
            'apikey': 'ANTHROPIC_API_KEY'
            },
        'groq': {
            'base_url': 'https://api.groq.com/openai/v1',
            'apikey': 'GROQ_API_KEY'
            },
        'openai': {
            'base_url': 'https://api.openai.com/v1',
            'apikey': 'OPENAI_API_KEY'
            },
        }

    models = {
        'anthropic/claude-3-haiku-20240307':    {'text/in': 0.25, 'text/out':  1.25},
        'anthropic/claude-opus-4-20250514':     {'text/in':15.00, 'text.out': 75.00},
        'anthropic/claude-sonnet-4-0':          {'text/in': 3.00, 'text/out': 15.00},
        'anthropic/claude-3-5-haiku-latest':    {'text/in': 0.80, 'text/out':  4.00},
        'groq/llama-3.3-70b-versatile':         {'text/in': 0.00, 'text/out':  0.00},
        'openai/gpt-5':                         {'text/in': 1.25, 'text/out': 10.00},
        'openai/gpt-5-mini':                    {'text/in': 0.25, 'text/out':  2.00},
        'openai/gpt-5-nano':                    {'text/in': 0.05, 'text/out':  0.40},
        'openai/gpt-4.1':                       {'text/in': 2.00, 'text/out':  8.00},
        'openai/gpt-4.1-mini':                  {'text/in': 0.40, 'text/out':  1.60},
        'openai/gpt-4.1-nano':                  {'text/in': 0.10, 'text/out':  0.60},
        'openai/gpt-image-1':                   {'text/in': 5.00, 'image/in': 10.00, 'image/out': 40.00},
        'openai/gpt-4o-mini-tts':               {'text/in': 0.60, 'audio/out': 12.00},
        }

    def __init__(self):
        #self.default_text_model = 'groq/llama-3.3-70b-versatile'
        #self.default_text_model = 'openai/gpt-4.1'
        self.default_text_model = 'openai/gpt-4.1-mini'
        #self.default_text_model = 'anthropic/claude-sonnet-4-0'
        #self.default_text_model = 'anthropic/claude-3-5-haiku-latest'
        #self.default_text_model = 'anthropic/claude-3-haiku-20240307'
        self.model_image = 'openai/gpt-image-1'
        self.default_audio_model = 'openai/gpt-4o-mini-tts'
        self.usage = defaultdict(lambda: Counter())
        self.build_id = generate_uuid7()

    def text(self, messages, *, tools=None, callables=None, response_format=None, model=None, seed=None, max_iter=10):

        assert (tools is None and callables is None) or (tools is not None and callables is not None)

        local_usage = defaultdict(lambda: Counter())

        # extract provider/model info from input model name
        if model is None:
            model = self.default_text_model
        provider, model_name = model.split('/')

        # we make a copy of the messages list;
        # this is necessary because we may be updating the list in the loop below,
        # and we do not want to update the list at the call site
        messages = list(messages)

        # call the API;
        # if the result asks for a tool use,
        # then use the tool and retry the API
        for i in range(max_iter):
            try:
                client = openai.Client(
                    api_key = os.environ.get(self.providers[provider]['apikey']),
                    base_url = self.providers[provider]['base_url'],
                )
                logger.trace('calling API: client.chat.completions.create()')
                result = client.chat.completions.create(
                    messages=messages,
                    model=model_name,
                    seed=seed,
                    tools=tools,
                )
            except openai.BadRequestError as e:
                print(f'response_format=\n{json.dumps(response_format, indent=2)}')
                raise e

            # update token usage
            usage = {
                'text/out': result.usage.completion_tokens,
                'text/in': result.usage.prompt_tokens,
                }
            local_usage[model] += usage
            self.usage[model] += usage

            # if there is no tool call, then we break from the loop
            if result.choices[0].message.content is not None:
                break

            # in order to append the results of tool calls to the messages list,
            # we need to have the output from the assistant appended
            messages.append(result.choices[0].message)

            # otherwise, we evaluate each tool call
            # and update messages list with their outputs;
            # the next iteration of the loop will call the API with the results
            for tool_call in result.choices[0].message.tool_calls:
                logger.trace(f'tool_call.function.name={tool_call.function.name}')
                f = callables[tool_call.function.name]
                try:
                    content = f(**json.loads(tool_call.function.arguments))
                    if content is None:
                        content = "Success."
                except Exception as e:
                    content = str(e)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": content,
                    })

        content = result.choices[0].message.content or ''

        logger.trace(f'self._tokens_to_prices()={self._tokens_to_prices(self.usage)}')
        logger.info(f'file_cost: ${self._total_price(local_usage):0.4f}  total_cost: ${self._total_price(self.usage):0.4f}', submessage=True)
        return  content, local_usage

    def image(self, fout, data, *, seed=None):
        logger.trace(f'llm.image; data.keys()={list(data.keys())}')
        client = openai.Client()
        model = self.model_image.split('/')[-1]
        quality = data.get('quality', 'low')

        size = '1536x1024'
        if data.get('orientation') == 'square':
            size = '1024x1024'
        if data.get('orientation') == 'portrait':
            size = '1024x1536'

        # generate a new image
        if not data.get('reference_images'):
            result = client.images.generate(
                model=model,
                prompt=data['prompt'],
                size=size,
                quality=quality,
            )
        else:
            result = client.images.edit(
                model=model,
                prompt=data['prompt'],
                size=size,
                quality=quality,
                image=data['reference_images'],
            )

        # save the image
        image_base64 = result.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)
        fout.write(image_bytes)

        # update usage info
        usage = {
            self.model_image: {
                'text/in': result.usage.input_tokens_details.text_tokens,
                'image/in': result.usage.input_tokens_details.image_tokens,
                'image/out': result.usage.output_tokens,
                }
            }
        self.usage[self.model_image] += usage[self.model_image]

        logger.info(f'self._tokens_to_prices()={self._tokens_to_prices(self.usage)}')
        logger.info(f'self._total_price()={self._total_price(self.usage)}')
        return usage

    def audio(self, path, data, *, model=None):

        # extract provider/model info from input model name
        if model is None:
            model = self.default_audio_model
        provider, model_name = model.split('/')

        # call API
        client = openai.Client()
        assert set(data.keys()) == set(['input', 'instructions', 'voice'])
        with client.audio.speech.with_streaming_response.create(
            model=model_name,
            response_format="wav",
            **data,
        ) as response:
            response.stream_to_file(path)

        # FIXME:
        # I don't know how to get usage info out of the TTS API :(
        logger.warning(f'unable to count token usage for model="{model}"')
        usage = {
            model: {
                'audio/out': 0,
                'text/in': 0,
                },
            }
        self.usage[model] += usage[model]

        logger.info(f'self._tokens_to_prices()={self._tokens_to_prices(self.usage)}')
        logger.info(f'self._total_price()={self._total_price(self.usage)}')
        return usage

    def generate_file(self, filetype, path, data, *, mode='xb', response_format, seed=None, model=None):
        try:
            # generate the file
            _, extension = os.path.splitext(path)
            if extension == '.png':
                with open(path, mode) as fout:
                    usage = self.image(fout, data)
            elif extension == '.wav':
                usage = self.audio(path, data)
            else:
                with open(path, mode) as fout:
                    text, usage = self.text(data, model=model, response_format=response_format)
                    blob = text.encode('utf-8')
                    fout.write(blob)

            # generate build info JSON
            buildinfo = {
                "__fac_version__": '0.0.0-dev',
                "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "path": path,
                "build_id": self.build_id,
                "cost": self._total_price(usage),
                "usage": usage,
                }
            buildinfo_str = json.dumps(buildinfo) + '\n'

            buildinfo_path = os.path.join(os.path.dirname(path), '.' + os.path.basename(path) + '.fac')
            with open(buildinfo_path, 'wt') as fout:
                fout.write(buildinfo_str)

            # register action globally
            with open('.fac.jsonl', 'ta') as fout:
                fout.write(buildinfo_str)

        except FileExistsError:
            logger.warning(f'file "{path}" exists; skipping')

    def _total_price(self, tokens):
        prices = self._tokens_to_prices(tokens)
        total = sum([sum(prices[model].values()) for model in prices])
        return total

    def _tokens_to_prices(self, tokens):
        prices = {}
        for model in tokens:
            prices[model] = {}
            for event in tokens[model]:
                num_tokens = tokens[model][event]
                token_price = self.models.get(model, {}).get(event, 0.0)
                if model not in self.models:
                    logger.warning(f'when calculating pricing, model="{model}" not found')
                if model in self.models and event not in self.models[model]:
                    logger.warning(f'when calculating pricing, event="{event}" not found for model="{model}"')
                prices[model][event] = token_price / 1000000.0 * num_tokens
        return prices



