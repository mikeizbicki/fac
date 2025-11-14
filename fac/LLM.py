
from collections import defaultdict, Counter
from pathlib import Path
import asyncio
import base64
import datetime
import json
import mimetypes
import os
import sys
import time
import uuid

import fal_client
import openai
import requests

from fac.Logging import logger

registered_providers = {
    'anthropic': {
        'base_url': 'https://api.anthropic.com/v1/',
        'apikey': 'ANTHROPIC_API_KEY'
        },
    'openrouter': {
        'base_url': 'https://openrouter.ai/api/v1',
        'apikey': 'OPENROUTER_API_KEY',
        },
    'cerebras': {
        'base_url': 'https://api.cerebras.ai/v1',
        'apikey': 'CEREBRAS_API_KEY'
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

registered_models = {
    'anthropic/claude-3-haiku-20240307':    {'text/in': 0.25, 'text/out':  1.25},
    'anthropic/claude-opus-4-20250514':     {'text/in':15.00, 'text.out': 75.00},
    'anthropic/claude-sonnet-4-0':          {'text/in': 3.00, 'text/out': 15.00},
    'anthropic/claude-3-5-haiku-latest':    {'text/in': 0.80, 'text/out':  4.00},
    'cerebras/qwen-3-235b-a22b-instruct-2507':
                                            {'text/in': 0.00, 'text/out':  0.00},
    'groq/llama-3.1-8b-instant':            {'text/in': 0.00, 'text/out':  0.00},
    'groq/llama-3.3-70b-versatile':         {'text/in': 0.00, 'text/out':  0.00},
    'groq/meta-llama/llama-4-maverick-17b-128e-instruct': 
                                            {'text/in': 0.00, 'text/out':  0.00},
    'groq/meta-llama/llama-4-scout-17b-16e-instruct':
                                            {'text/in': 0.00, 'text/out':  0.00},
    'openai/gpt-5':                         {'text/in': 1.25, 'text/out': 10.00},
    'openai/gpt-5-mini':                    {'text/in': 0.25, 'text/out':  2.00},
    'openai/gpt-5-nano':                    {'text/in': 0.05, 'text/out':  0.40},
    'openai/gpt-4.1':                       {'text/in': 2.00, 'text/out':  8.00},
    'openai/gpt-4.1-mini':                  {'text/in': 0.40, 'text/out':  1.60},
    'openai/gpt-4.1-nano':                  {'text/in': 0.10, 'text/out':  0.60},
    'openai/gpt-image-1':                   {'text/in': 5.00, 'image/in': 10.00, 'image/out': 40.00},
    'openai/gpt-4o-mini-tts':               {'text/in': 0.60, 'audio/out': 12.00},

    # video prices are measured in seconds, not tokens
    'openai/sora-2':                        {'video/out': 0.10},
    'openai/sora-2-pro':                    {'video/out': 0.50},

    # fal-ai prices are measured in seconds, not tokens
    'fal-ai/nano-banana':                   {'video/out': 0.04},
    }


class ModelUsageSummary():
    def __init__(self):
        self.model_details = defaultdict(lambda: Counter())
        self.tools_used = Counter()

    def register_result(self, model, result):
        tokens = Counter()

        # FAL-AI API calls
        if model.startswith('fal-ai'):
            tokens['video/out'] = 1000000.0

        # Video Generation calls
        elif str(result).startswith('Video'):
            tokens['video/out'] = float(result.seconds) * 1000000
            # we multiply by a million here because we divide by 1000000 later

        # TTS API calls
        elif 'StreamedBinaryAPIResponse' in str(result):
            pass
            #logger.warning('TTS API does not support usage information', submessage=True)

        # image API calls
        elif hasattr(result.usage, 'input_tokens'):
            tokens['text/in'] = result.usage.input_tokens_details.text_tokens
            tokens['image/in'] = result.usage.input_tokens_details.image_tokens
            tokens['image/out'] = result.usage.output_tokens
            self.model_details[model] += tokens

        # text API calls
        elif hasattr(result.usage, 'completion_tokens'):
            tokens['text/in'] = result.usage.completion_tokens
            tokens['text/out'] = result.usage.prompt_tokens
            self.model_details[model] += tokens

            # only text results use tool use
            tools = result.choices[0].message.tool_calls
            if tools:
                for tool in tools:
                    self.tools_used[str(tool)] += 1

        # other API calls
        else:
            raise ValueError('unsupported result type')

        # record cost
        if hasattr(result, 'usage') and hasattr(result.usage, 'cost'):
            self.model_details[model]['cost'] += result.usage.cost
        elif model not in registered_models:
            logger.warning(f'model="{model}" not in registered_models')
        else:
            prices = registered_models[model]
            for event in tokens:
                if event not in prices:
                    logger.warning(f'model="{model}" does not have event={event}; assuming 0 cost')
                else:
                    self.model_details[model]['cost'] += prices[event] / 1000000.0 * tokens[event]

    def total_cost(self):
        return sum([self.model_details[model]['cost'] for model in self.model_details])

    def __add__(l, r):
        new = ModelUsageSummary()
        models = set(self.model_details.keys()) | set(other.model_details.keys)
        for model in models:
            new.model_details[model] = l.model_details[model] + r.model_details[model]
        new.tools_used = l.tools_used + r.tools_used
        return new


class LLM():

    def __init__(self):
        #self.default_text_model = 'groq/llama-3.3-70b-versatile'
        #self.default_text_model = 'openai/gpt-4.1'
        #self.default_text_model = 'openai/gpt-4.1-mini'
        self.default_text_model = 'openai/gpt-5'
        #self.default_text_model = 'openai/gpt-5-nano'
        #self.default_text_model = 'groq/llama-3.3-70b-versatile'
        #self.default_text_model = 'anthropic/claude-sonnet-4-0'
        #self.default_text_model = 'anthropic/claude-3-5-haiku-latest'
        #self.default_text_model = 'anthropic/claude-3-haiku-20240307'
        #self.model_image = 'fal-ai/nano-banana/edit'
        self.model_image = 'openai/gpt-image-1'
        self.default_audio_model = 'openai/gpt-4o-mini-tts'
        self.usage_summary = ModelUsageSummary()
        self.build_id = generate_uuid7()

    def text(self, messages, *,
            tools=None,
            callables=None,
            response_format=None,
            model=None,
            seed=None,
            max_iter=10,
            ):
        #return asyncio.run(self.text_async(
            #messages,
            #tools=tools,
            #callables=callables,
            #response_format=response_format,
            #model=model,
            #seed=seed,
            #max_iter=max_iter
        #))
        try:
            # Check if we're already in a running event loop
            loop = asyncio.get_running_loop()
            # If we are, we need to run in a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, self.text_async(
                    messages,
                    tools=tools,
                    callables=callables,
                    response_format=response_format,
                    model=model,
                    seed=seed,
                    max_iter=max_iter
                ))
                return future.result()
        except RuntimeError:
            # No running event loop, use asyncio.run() normally
            return asyncio.run(self.text_async(
                messages,
                tools=tools,
                callables=callables,
                response_format=response_format,
                model=model,
                seed=seed,
                max_iter=max_iter
            ))


    async def text_async(self, messages, *,
            tools=None,
            callables=None,
            response_format=None,
            model=None,
            seed=None,
            max_iter=10,
            ):

        # if either tools/callables is provided, both must be
        assert ((tools is     None and callables is     None)
             or (tools is not None and callables is not None))

        local_usage = ModelUsageSummary()

        # extract provider/model info from input model name
        if model is None:
            model = self.default_text_model
        provider, model_name = model.split('/', 1)

        # any responses will be stored in new_messages;
        # without tool use, this will be only the response;
        # with tool use, this will contain all tool calls and all results of the calls
        new_messages = []

        # openrouter supports supplying additional parameters that other providers do not;
        # these parameters will ensure fast responses and provide actual costs in the usage field returned;
        # the cost field is important for openrouter because it can be different for different runs,
        # and so it cannot be hardcoded in the dictionaries above
        extra_body = None
        if provider == 'openrouter':
            extra_body={
                "provider": {"sort": "latency"},
                "usage": {"include": True},
                }

        # call the API;
        # if the result asks for a tool use,
        # then use the tool and retry the API
        client = openai.AsyncOpenAI(
            api_key = os.environ.get(registered_providers[provider]['apikey']),
            base_url = registered_providers[provider]['base_url'],
        )
        for i in range(max_iter):
            logger.trace('calling API: client.chat.completions.create()')
            result = await client.chat.completions.create(
                messages=list(messages) + new_messages,
                model=model_name,
                seed=seed,
                tools=tools,
                stream=False,
                extra_body=extra_body,
            )
            new_messages.append(result.choices[0].message)
            local_usage.register_result(model, result)
            self.usage_summary.register_result(model, result)

            # if there is no tool call, then we break from the loop
            if result.choices[0].message.tool_calls is None:
                break

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
                    logger.warning(f'exception in {tool_call.function.name}: {repr(e)}')
                    content = str(e)
                new_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": content,
                    })

        content = result.choices[0].message.content or ''

        logger.info(f'request_cost: ${local_usage.total_cost():0.4f}  total_cost: ${self.usage_summary.total_cost():0.4f}', submessage=True)
        return content, local_usage


    def image(self, path, mode, data, *, model=None, seed=None):
        return asyncio.run(self.image_async(path, mode, data, model=model, seed=seed))

    async def image_async(self, path, mode, data, *, model=None, seed=None):
        logger.trace(f'llm.image; data.keys()={list(data.keys())}')
        client = openai.AsyncOpenAI()
        
        if model is None:
            model = self.model_image
        provider, model_name = model.split('/', 1)

        # openAI models:
        if provider == 'openai':
            quality = data.get('quality', 'low')
            size = '1536x1024'
            if data.get('orientation') == 'square':
                size = '1024x1024'
            if data.get('orientation') == 'portrait':
                size = '1024x1536'

            # generate a new image
            if not data.get('reference_images'):
                result = await client.images.generate(
                    model=model_name,
                    prompt=data['prompt'],
                    size=size,
                    quality=quality,
                )
            else:
                result = await client.images.edit(
                    model=model_name,
                    prompt=data['prompt'],
                    size=size,
                    quality=quality,
                    image=[open(path, 'rb') for path in data['reference_images']]
                )
            local_usage = ModelUsageSummary()
            local_usage.register_result(model, result)
            self.usage_summary.register_result(model, result)

            # save the image
            image_base64 = result.data[0].b64_json
            image_bytes = base64.b64decode(image_base64)
            with open(path, mode) as fout:
                fout.write(image_bytes)

        elif provider == 'fal-ai':
            base64_urls = [encode_image_to_base64_url(path) for path in data['reference_images']]

            # call the api and await result
            handler = await fal_client.submit_async(
                model,
                arguments={
                    "prompt": data['prompt'],
                    "num_images": 1,
                    "aspect_ratio": "16:9",
                    "image_urls": base64_urls,
                },
            )
            async for event in handler.iter_events(with_logs=True):
                pass
            result = await handler.get()

            # download the image
            response = requests.get(result['images'][0]['url'])
            with open(path, 'wb') as fout:
                fout.write(response.content)

            # update usage info
            local_usage = ModelUsageSummary()
            local_usage.register_result(model, result)
            self.usage_summary.register_result(model, result)

        logger.info(f'request_cost: ${local_usage.total_cost():0.4f}  total_cost: ${self.usage_summary.total_cost():0.4f}', submessage=True)
        return local_usage

    def audio(self, path, data, *, model=None):
        return asyncio.run(self.audio_async(path, data, model=model))

    async def audio_async(self, path, data, *, model=None):

        # extract provider/model info from input model name
        if model is None:
            model = self.default_audio_model
        provider, model_name = model.split('/')

        # call API
        client = openai.AsyncOpenAI()
        assert set(data.keys()) == set(['input', 'instructions', 'voice'])
        async with client.audio.speech.with_streaming_response.create(
            model=model_name,
            response_format="wav",
            **data,
        ) as result:
            await result.stream_to_file(path)

        # log usage
        local_usage = ModelUsageSummary()
        local_usage.register_result(model, result)
        self.usage_summary.register_result(model, result)
        logger.info(f'request_cost: ${local_usage.total_cost():0.4f}  total_cost: ${self.usage_summary.total_cost():0.4f}', submessage=True)
        return local_usage

    async def video_async(self, path, data):
        client = openai.OpenAI()
        model = data.get('model', 'openai/sora-2')
        provider, model_name = model.split('/', 1)
        assert len(data['reference_images']) == 1
        input_reference = Path(data['reference_images'][0])
        video = openai.videos.create(
                model=model_name,
                prompt=data['prompt'],
                input_reference=input_reference,
                size=data.get('size', '1280x720'),
                seconds=data.get('seconds', 4),
                )

        # async sleep until video ready
        while video.status in ("in_progress", "queued"):
            await asyncio.sleep(2)
            video = openai.videos.retrieve(video.id)
        local_usage = ModelUsageSummary()

        # check for errors
        if video.status == "failed":
            message = getattr(
                getattr(video, "error", None), "message", "Video generation failed"
            )
            logger.error(message)
            return local_usage

        # write video to file
        content = openai.videos.download_content(video.id, variant="video")
        content.write_to_file(path)

        # calculate usage info
        local_usage.register_result(model, video)
        self.usage_summary.register_result(model, video)
        logger.info(f'request_cost: ${local_usage.total_cost():0.4f}  total_cost: ${self.usage_summary.total_cost():0.4f}', submessage=True)

        return local_usage


    async def generate_file(self, filetype, path, data, *, mode='xb', response_format, seed=None, model=None):
        try:
            # generate the file
            _, extension = os.path.splitext(path)
            if extension == '.png':
                usage = await self.image_async(path, mode, data)
            elif extension == '.wav':
                usage = await self.audio_async(path, data)
            elif extension == '.mp4':
                usage = await self.video_async(path, data)
            else:
                text, usage = await self.text_async(data, model=model, response_format=response_format)
                blob = text.encode('utf-8')
                with open(path, mode) as fout:
                    fout.write(blob)

            # generate build info JSON
            buildinfo = {
                "__fac_version__": '0.0.0-dev',
                "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "path": path,
                "build_id": self.build_id,
                "cost": usage.total_cost(),
                "usage": usage.__dict__,
                }
            buildinfo_str = json.dumps(buildinfo) + '\n'

            buildinfo_path = os.path.join(os.path.dirname(path), '.' + os.path.basename(path) + '.fac.log')
            with open(buildinfo_path, 'wt') as fout:
                fout.write(buildinfo_str)

            # register action globally
            with open('.fac.jsonl', 'ta') as fout:
                fout.write(buildinfo_str)

        except FileExistsError:
            logger.warning(f'file "{path}" exists; skipping')


################################################################################
# utils
################################################################################

def generate_uuid7():
    timestamp = int(time.time() * 1000)
    random_number = uuid.uuid4().int
    uuid7 = (timestamp << 64) | random_number
    return uuid7


def encode_image_to_base64_url(file_path):
    with open(file_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        mime_type = mimetypes.guess_type(file_path)[0] or 'image/png'
        return f"data:{mime_type};base64,{encoded_string}"

