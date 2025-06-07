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


def create_image(
        output_file,
        style,
        reference_images,
        notes='',
        model='gpt-image-1',
        #size='1024x1024',
        size='1024x1536',
        quality='low',
        ):
    # we try to open the output file first before accessing API;
    # this way, if there is a problem with the file, we won't waste API credits
    with open(output_file, "wb") as f:

        # init API
        from openai import OpenAI
        import base64
        client = OpenAI()

        # init API
        from openai import OpenAI
        import base64
        client = OpenAI()

        # generate prompt
        prompt = f"""
Take the input images and generate an avatar of the represented person.
The avatar should have a transparent background and only show the person,
with no background or other objects.
Show the full person (not just head) in a natural standing pose.
There clothing should be a solid color and not have logos.
Style: {style}
Notes: {notes}
"""
        #print(f"prompt={prompt}")

        result = client.images.edit(
            model=model,
            image=[open(image, 'rb') for image in reference_images],
            prompt=prompt,
            size=size,
            quality=quality,
        )

        # save the image
        image_base64 = result.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)
        f.write(image_bytes)


if __name__ == '__main__':

    # parse command line options
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('character_folder')
    parser.add_argument('--style', default='cartoon, bright colors, bold outlines, fun for kids')
    args = parser.parse_args()

    # find reference_images
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
    raw_images_path = args.character_folder + '/raw_images'
    reference_images = [raw_images_path + '/' + f for f in os.listdir(raw_images_path) if os.path.isfile(os.path.join(raw_images_path, f)) and os.path.splitext(f)[1].lower() in image_extensions]

    # load text about info
    import json
    about_path = args.character_folder + '/about.json'
    with open(about_path, 'rt') as fin:
        about = json.load(fin)
        notes = about.get('Appearance')

    # create the image
    create_image(
            args.character_folder + '/avatar.png',
            args.style,
            reference_images,
            notes
            )
