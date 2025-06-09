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


def create_background_image(
        output_file,
        style,
        scene,
        model='gpt-image-1',
        #model='dall-e-3',
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

        # generate prompt
        prompt = f"""
Create a background image for animating a scene using cel animation.

Do not include any characters, or foreground objects that the characters might interact with (e.g. tables/chairs/boxes/bushes).
These will be added later, and having them in the background will disrupt the cel animation.
Each scene should be totally empty, but only have minimal decorations away from where the characters will interact.
There must be a clear, flat space 100px above the bottom of the picture for the characters and sprites to be placed on.
There should be no text.

Style: {style}

Scene: {scene}
"""

        # generate a new image
        result = client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            #quality=quality,
        )

        # save the image
        image_base64 = result.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)
        f.write(image_bytes)


if __name__ == '__main__':

    # parse command line options
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input_file', required=True)
    parser.add_argument('--style', default='cartoon, bright colors, bold outlines, fun for kids')
    args = parser.parse_args()

    # extract subscenes from input JSON
    with open(args.input_file, 'rt') as fin:
        data = json.load(fin)
        subscenes = data['subscenes']

    for i, subscene in enumerate(subscenes):
        image_path = os.path.dirname(args.input_file) + f'/../subscene/{subscene["name"]}.png'
        logging.info(f"i={i}, image_path={image_path}")
        create_background_image(image_path, args.style, subscene)
