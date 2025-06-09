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
        #model='gpt-image-1',
        model='dall-e-3',
        #size='1024x1024',
        #size='1024x1536',
        #size='1536x1024',
        size='1792x1024',
        quality='standard',
        #quality='high',
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
Create a detailed sprite sheet for a game.
The final image is divided into a 3 row x 6 column grid.
Each subimage serves as a continuous animation keyframe,
and there should be substantial differences between one frame and the subsequent frame in order to illustrate motion.
Ensure the images transition smoothly and continuously.

The animation should be: the character is walking from left to right; the legs and arms are in motion and never appear in the same place twice

Art style: {style}
Other character notes: {notes}
"""
        prompt = f'''
The first input image shows a spritesheet of a character walking,
and the second image shows a character.
Generate a spritesheet of the character in the second image walking like the character in the first image.
The final image should be divided into a 3 row x 6 column grid.
'''
        prompt = f'''
Create a detailed sprite sheet for a game.
The final image is divided into a 3 row x 6 column grid.
Each subimage serves as a continuous animation keyframe,
and there should be substantial differences between one frame and the subsequent frame in order to illustrate motion.
Ensure the images transition smoothly and continuously.

The animation should be: the character is walking from left to right; the legs and arms are in motion and never appear in the same place twice

Art style: {style}
Other character notes: {notes}
'''
        #print(f"prompt={prompt}")

        result = client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            quality=quality,
        )
        import code; code.interact(local=locals())

        if False:
            result = client.images.edit(
                model=model,
                image=[open(image, 'rb') for image in ['common/walking.png'] + reference_images],
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
    reference_images = [args.character_folder + '/avatar.png']
    print(f"reference_images={reference_images}")

    # load text about info
    import json
    about_path = args.character_folder + '/about.json'
    with open(about_path, 'rt') as fin:
        about = json.load(fin)
        notes = about.get('Appearance')

    # create the image
    create_image(
            args.character_folder + '/sprites.png',
            args.style,
            reference_images,
            notes
            )

