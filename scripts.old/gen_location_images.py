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
        location,
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
Create a background image for animating a location using cel animation.

Do not include any characters, or foreground objects that the characters might interact with (e.g. tables/chairs/boxes/bushes).
These will be added later, and having them in the background will disrupt the cel animation.
Each location should be totally empty, but only have minimal decorations away from where the characters will interact.
There must be a clear, flat space 100px above the bottom of the picture for the characters and sprites to be placed on.
There should be no text.

Style: {style}

Draw the image described in the "sublocation" below.
This is one of several sublocations in the overall location below.
Use the "location" field for directional guidance,
but make sure to draw the "sublocation".

{location}
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
    parser.add_argument('story_dir')
    parser.add_argument('--style', default='cartoon, bright colors, bold outlines, fun for kids')
    args = parser.parse_args()

    # extract sublocations from input JSON
    locations_path = args.story_dir + '/locations.json'
    os.makedirs(args.story_dir + '/sublocations', exist_ok=True)
    with open(locations_path, 'rt') as fin:
        data = json.load(fin)

    for i, location in enumerate(data['locations']):
        for j, sublocation in enumerate(location['sublocations']):
            image_path = os.path.dirname(args.story_dir) + f'/sublocations/{sublocation["name"]}.png'
            logging.info(f"i={i}, image_path={image_path}")
            prompt = f'''sublocation: {sublocation["description"]}
location: {location["description"]}'''
            create_background_image(image_path, args.style, prompt)

