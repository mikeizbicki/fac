'''
This file defines a generic interface for working with LLMs from any provider and any modality.
'''

# stdlib imports
from collections import defaultdict, Counter
from pathlib import Path
import asyncio
import base64
import datetime
import json
import os
import time
import uuid

# external imports
import fal_client
import ffmpeg
import httpx
import openai
import requests

# project imports
from fac.Errors import FACError
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
    'anthropic/claude-opus-4-8':            {'text/in': 5.00, 'text.out': 25.00},
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
    'openai/gpt-5.5':                       {'text/in': 2.50, 'text/out': 15.00},
    'openai/gpt-5.4':                       {'text/in': 2.50, 'text/out': 15.00},
    'openai/gpt-5':                         {'text/in': 1.25, 'text/out': 10.00},
    'openai/gpt-5-mini':                    {'text/in': 0.25, 'text/out':  2.00},
    'openai/gpt-5-nano':                    {'text/in': 0.05, 'text/out':  0.40},
    'openai/gpt-4.1':                       {'text/in': 2.00, 'text/out':  8.00},
    'openai/gpt-4.1-mini':                  {'text/in': 0.40, 'text/out':  1.60},
    'openai/gpt-4.1-nano':                  {'text/in': 0.10, 'text/out':  0.60},
    'openai/gpt-image-1':                   {'text/in': 5.00, 'image/in': 10.00, 'image/out': 40.00},
    'openai/gpt-4o-mini-tts':               {'text/in': 0.60, 'audio/out': 12.00},

    # fal-ai prices
    'fal-ai/nano-banana':                   {'image/out': 0.04},
    'fal-ai/nano-banana-pro':               {'image/out': 0.15},
    'fal-ai/nano-banana/edit':              {'image/out': 0.04},
    'fal-ai/nano-banana-pro/edit':          {'image/out': 0.15},
    'fal-ai/nano-banana-2':                 {'image/out': 0.08},
    'fal-ai/nano-banana-2/edit':            {'image/out': 0.08},

    # image -> video
    # video prices are measured in seconds, not tokens
    'fal-ai/bytedance/omnihuman/v1.5':      {'video/out': 0.16},
    'fal-ai/creatify/aurora':               {'video/out': 0.14},
    'fal-ai/kling-video/o1/image-to-video': {'video/out': 0.112},
    'fal-ai/kling-video/o3/pro/image-to-video': {'video/out': 0.112},
    'fal-ai/kling-video/o3/standard/image-to-video': {'video/out': 0.084},
    'fal-ai/kling-video/v3/pro/image-to-video': {'video/out': 0.112},
    'fal-ai/kling-video/v3/standard/image-to-video': {'video/out': 0.084},
    'fal-ai/kling-video/v2.6/pro/image-to-video': {'video/out': 0.07},
    'fal-ai/kling-video/v2.6/standard/image-to-video': {'video/out': 0.042},
    'fal-ai/kling-video/v2.5-turbo/pro/image-to-video': {'video/out': 0.07},
    'fal-ai/kling-video/v2.5-turbo/standard/image-to-video': {'video/out': 0.042},
    'fal-ai/veed/fabric-1.0':               {'video/out': 0.08},
    'fal-ai/veo3.1/fast/first-last-frame-to-video': {'video/out': 0.10},
    'fal-ai/veo3.1/first-last-frame-to-video': {'video/out': 0.20},
    'openai/sora-2':                        {'video/out': 0.10},
    'openai/sora-2-pro':                    {'video/out': 0.50},

    # avatar
    'fal-ai/kling-video/v1/pro/ai-avatar':  {'video/out': 0.115},
    'fal-ai/kling-video/v1/standard/ai-avatar': {'video/out': 0.0562},

    # video -> audio
    'fal-ai/mmaudio-v2':                                {'video/out': 0.001},
    'fal-ai/mirelo-ai/sfx-v1/video-to-video':           {'video/out': 0.007},
    'fal-ai/pixverse/sound-effects':                    {'video/out': 0.02},
    'fal-ai/cassetteai/video-sound-effects-generator':  {'video/out': 0.0034},

    }


class ModelUsageSummary():
    def __init__(self):
        self.model_details = defaultdict(lambda: Counter())
        self.tools_used = Counter()

    def register_result(self, model, result):
        tokens = Counter()

        # Video Generation calls
        if 'get' in dir(result) and result.get('seconds'):
            tokens['video/out'] = float(result['seconds']) * 1000000

        # FAL-AI API image calls
        elif model.startswith('fal-ai'):
            tokens['image/out'] = 1000000.0

        # TTS API calls
        elif 'StreamedBinaryAPIResponse' in str(result):
            pass
            #logger.warning('TTS API does not support usage information', submessage=True)

        # image API calls
        elif hasattr(result, 'usage') and hasattr(result.usage, 'input_tokens'):
            tokens['text/in'] = result.usage.input_tokens_details.text_tokens
            tokens['image/in'] = result.usage.input_tokens_details.image_tokens
            tokens['image/out'] = result.usage.output_tokens
            self.model_details[model] += tokens

        # text API calls
        elif hasattr(result, 'usage') and hasattr(result.usage, 'completion_tokens'):
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
            breakpoint()
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
        models = set(l.model_details.keys()) | set(r.model_details.keys)
        for model in models:
            new.model_details[model] = l.model_details[model] + r.model_details[model]
        new.tools_used = l.tools_used + r.tools_used
        return new


class LLM():

    def __init__(self):
        #self.default_text_model = 'groq/llama-3.3-70b-versatile'
        #self.default_text_model = 'openai/gpt-4.1'
        #self.default_text_model = 'openai/gpt-4.1-mini'
        self.default_text_model = 'openai/gpt-5.5'
        #self.default_text_model = 'openai/gpt-5'
        #self.default_text_model = 'openai/gpt-5.4'
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

    def log_usage(self):
        logger.info(f'total_cost: ${self.usage_summary.total_cost():0.4f}')

    async def text_async(self, messages, *,
            tools=None,
            callables=None,
            model=None,
            seed=None,
            max_iter=10,
            ):
        # FIXME:
        # There is not currently a way to enforce that output must have a particular format (e.g. JSON schema).

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
            try:
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
            except openai.OpenAIError as e:
                logger.error(f'OpenAIError: {e}')
                raise LLMError

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

    async def image_async(self, path, data, *, seed=None):
        logger.trace(f'llm.image; data.keys()={list(data.keys())}')
        client = openai.AsyncOpenAI()
        
        model = data.get('model')
        if model is None:
            model = self.model_image
        provider, model_name = model.split('/', 1)

        # openAI models:
        if provider == 'openai':
            quality = data.get('quality', 'high')
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
            with open(path, 'wb') as fout:
                fout.write(image_bytes)

        elif provider == 'fal-ai':
            elements = [path for path in data.get('reference_images', [])]
            elements_urls = [self.fal_upload_file(element) for element in elements]

            if model_name.startswith('openai'):
                model = model_name

            # call the api and await result
            arguments={
                "prompt": data['prompt'],
                "num_images": 1,
                "aspect_ratio": "16:9",
                "image_urls": elements_urls,
            }
            try:
                handler = await fal_client.submit_async(model, arguments)
                async for event in handler.iter_events(with_logs=True):
                    pass
                result = await handler.get()
            except fal_client.client.FalClientHTTPError as e:
                # in the documentation, e.message is always a dict;
                # but sometimes it seems to be a str as well
                # (I believe this is undocumented behavior);
                # we have the if/else here to ensure good logs in either event
                if isinstance(e.message, dict):
                    logger.error(f"FalClientHTTPError: {e.message[0]['type']}: {e.message[0]['loc']}", submessage=True)
                    logger.error(e.message[0]['msg'], submessage=True)
                else:
                    logger.error(f"FalClientHTTPError: {e.message}", submessage=True)
                logger.error({
                    'fal_client.submit_async() parameters': {
                        'model': model,
                        'arguments': arguments,
                        }
                    },
                    submessage=True,
                    max_line_length=300,
                    )
                raise LLMError

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
        try:
            async with client.audio.speech.with_streaming_response.create(
                model=model_name,
                response_format="wav",
                **data,
            ) as result:
                await result.stream_to_file(path)
        except Exception as e:
            logger.error(str(e))
            raise LLMError

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

        if provider == 'openai':
            assert len(data['reference_images']) == 1
            input_reference = Path(data['reference_images'][0])
            response = openai.videos.create(
                    model=model_name,
                    prompt=data['prompt'],
                    input_reference=input_reference,
                    size=data.get('size', '1280x720'),
                    seconds=data.get('seconds', 4),
                    )

            # async sleep until video ready
            while response.status in ("in_progress", "queued"):
                await asyncio.sleep(2)
                video = openai.videos.retrieve(video.id)

            # check for errors
            if video.status == "failed":
                message = getattr(
                    getattr(video, "error", None), "message", "Video generation failed"
                )
                logger.error(message)
                return ModelUsageSummary()

            # write video to file
            content = openai.videos.download_content(video.id, variant="video")
            content.write_to_file(path)

        elif provider == 'fal-ai':

            # fal-ai models have many different argument configurations
            # and they must all be implemented separately here
            if model in [
                    'fal-ai/veo3.1/fast/first-last-frame-to-video',
                    'fal-ai/veo3.1/first-last-frame-to-video',
                    ]:
                seconds = int(data.get('duration', 8))
                arguments = {
                    "prompt": data['prompt'],
                    "first_frame_url": self.fal_upload_file(data['first_frame']),
                    "last_frame_url": self.fal_upload_file(data['last_frame']),
                    "duration": str(seconds) + 's',
                    "aspect_ratio": data.get('aspect_ratio', '16:9'),
                    'resolution': data.get('resolution', '720p'),
                    'generate_audio': data.get('generate_audio', False),
                }
            elif model in [
                    'fal-ai/kling-video/v2.5-turbo/pro/image-to-video',
                    'fal-ai/kling-video/v2.5-turbo/standard/image-to-video',
                    ]:
                seconds = int(data.get('duration', 5))
                arguments = {
                    "prompt": data['prompt'],
                    "image_url": self.fal_upload_file(data['first_frame']),
                    "duration": str(seconds),
                }
            elif model in [
                    'fal-ai/kling-video/o1/image-to-video',
                    ]:
                seconds = int(data.get('seconds', 5))
                arguments = {
                    "prompt": data['prompt'],
                    "start_image_url": self.fal_upload_file(data['first_frame']),
                    "end_image_url": self.fal_upload_file(data['last_frame']),
                    "duration": str(seconds),
                }
            elif model in [
                    'fal-ai/kling-video/o1/image-to-video',
                    'fal-ai/kling-video/o3/standard/image-to-video',
                    'fal-ai/kling-video/o3/pro/image-to-video',
                    ]:
                seconds = int(data.get('seconds', 5))
                arguments = {
                    "prompt": data['prompt'],
                    "image_url": self.fal_upload_file(data['first_frame']),
                    "end_image_url": self.fal_upload_file(data['last_frame']),
                    "duration": str(seconds),
                }
            elif model == 'fal-ai/kling-video/o1/reference-to-video':
                elements = [path for path in data['reference_images'] if path != data['start_frame']]
                elements_urls = [self.fal_upload_file(element) for element in elements]
                start_frame_url = self.fal_upload_file(data['start_frame'])
                seconds = int(data.get('seconds', 5))
                arguments = {
                    "prompt": "The start frame must match @Image1 exactly. " + data['prompt'],
                    "duration": str(seconds),
                    "aspect_ratio": data.get('aspect_ratio', '16:9'),
                    "image_urls": [start_frame_url],
                    "elements": [{"frontal_image_url": url, "reference_image_urls": [url]} for url in elements_urls],
                }
            elif model in [
                    'fal-ai/veed/fabric-1.0',
                    'fal-ai/creatify/aurora',
                    ]:
                if model == 'fal-ai/veed/fabric-1.0':
                    model = 'veed/fabric-1.0'
                start_frame_url = self.fal_upload_file(data['first_frame'])
                audio_url = self.fal_upload_file(data['audio'])
                arguments = {
                    'image_url': start_frame_url,
                    'audio_url': audio_url,
                    'resolution': data.get('resolution', '480p'),
                    'prompt': data.get('prompt', ''),
                }
            elif model == 'fal-ai/bytedance/omnihuman/v1.5':
                start_frame_url = self.fal_upload_file(data['first_frame'])
                audio_url = self.fal_upload_file(data['audio'])
                arguments = {
                    'image_url': start_frame_url,
                    'audio_url': audio_url,
                    'resolution': data.get('resolution', '1080p'),
                    'prompt': data.get('prompt', ''),
                }
            elif model in [
                    'fal-ai/kling-video/v1/standard/ai-avatar',
                    'fal-ai/kling-video/v1/pro/ai-avatar',
                    ]:
                start_frame_url = self.fal_upload_file(data['first_frame'])
                audio_url = self.fal_upload_file(data['audio'])
                arguments = {
                    'image_url': start_frame_url,
                    'audio_url': audio_url,
                    'prompt': data.get('prompt', ''),
                }
            elif model in [
                    'fal-ai/pixverse/sound-effects',
                    'fal-ai/mmaudio-v2',
                    ]:
                arguments = {
                    'video_url': self.fal_upload_file(data['video']),
                    'prompt': data.get('prompt', ''),
                }
            elif model in [
                    'fal-ai/cassetteai/video-sound-effects-generator',
                    'fal-ai/mirelo-ai/sfx-v1/video-to-video'
                    ]:
                arguments = {
                    'video_url': self.fal_upload_file(data['video']),
                }
                model = '/'.join(model.split('/')[1:])
            else:
                raise ValueError(f'model="{model}" not supported')

            # call the api and await result
            try:
                logger.debug({
                    'fal_client.submit_async() parameters': {
                        'model': model,
                        'arguments': arguments,
                        }
                    },
                    submessage=True,
                    max_line_length=70,
                    )
                handler = await fal_client.submit_async(model, arguments)
                async for event in handler.iter_events(with_logs=True):
                    if isinstance(event, fal_client.InProgress):
                        for log in event.logs:
                            logger.debug(f'status "{path}": {log["message"]}')
                result = await handler.get()
            except fal_client.client.FalClientHTTPError as e:
                logger.error({'FalClientHTTPError': e.message})
                logger.error({
                    'fal_client.submit_async() parameters': {
                        'model': model,
                        'arguments': arguments,
                        }
                    },
                    submessage=True,
                    max_line_length=300,
                    )
                raise LLMError

            # download the video
            video = requests.get(result['video']['url'])
            with open(path, 'wb') as fout:
                fout.write(video.content)

            # get video length for recording costs
            probe = ffmpeg.probe(path)
            result['seconds'] = float(probe['streams'][0]['duration'])

        # calculate usage info
        local_usage = ModelUsageSummary()
        local_usage.register_result(model, result)
        self.usage_summary.register_result(model, result)
        logger.info(f'request_cost: ${local_usage.total_cost():0.4f}  total_cost: ${self.usage_summary.total_cost():0.4f}', submessage=True)

        return local_usage

    def fal_upload_file(self, path):
        try:
            return fal_client.upload_file(path)
        except httpx.HTTPStatusError as e:
            logger.error(f'fal_upload_file: {e}')
            logger.error('HINT: most API errors are caused by either a lack of credits or the remote service being down', submessage=True)
            raise LLMError


################################################################################
# utils
################################################################################

def generate_uuid7():
    timestamp = int(time.time() * 1000)
    random_number = uuid.uuid4().int
    uuid7 = (timestamp << 64) | random_number
    return uuid7

class LLMError(FACError):
    pass
