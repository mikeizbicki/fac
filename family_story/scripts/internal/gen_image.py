#!/usr/bin/env python3

# setup logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# imports
from PIL import Image, ImageDraw
import json
import os
import clize


def create_image(
        output_file,
        prompt,
        *reference_files,
        model='gpt-image-1',
        size='1536x1024',
        quality='low',
        ):
    # we try to open the output file first before accessing API;
    # this way, if there is a problem with the file, we won't waste API credits
    with open(output_file, "wb") as f:

        # init API
        from openai import OpenAI
        import base64
        client = OpenAI()

        # generate a new image
        if not reference_files:
            result = client.images.generate(
                model=model,
                prompt=prompt,
                size=size,
                quality=quality,
            )
        else:
            result = client.images.edit(
                model=model,
                image=[open(f, 'rb') for f in reference_files],
                prompt=prompt,
                size=size,
                quality=quality,
            )

        # save the image
        image_base64 = result.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)
        f.write(image_bytes)

        # output cost info 
        # FIXME:
        # these costs are hard-coded to gpt-image-1
        input_cost = result.usage.input_tokens * 10 / 1000000
        output_cost = result.usage.output_tokens * 40 / 1000000
        total_cost = input_cost + output_cost
        print(f'input cost:  {input_cost:0.3f}') 
        print(f'output cost: {output_cost:0.3f}') 
        print(f'total cost:  {total_cost:0.3f}') 


if __name__ == '__main__':
    clize.run(create_image)
