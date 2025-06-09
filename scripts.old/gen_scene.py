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


def shift_image(image_path, shift_fraction):
    """
    Shifts an image to the left by a specified fraction,
    filling the remainder with transparency.
    Does not modify the original image,
    and returns the path to the new image.

    Here is an example of what happens when shifting an image with a width of 10:

    Original Image:
    ##########
    ##########
    ##########
    ##########

    Shifted Image (80%):
    ##........
    ##........
    ##........
    ##........

    """
    # load the image
    img = Image.open(image_path)
    img_format = img.format
    img = img.convert('RGBA')

    # create a new transparent image
    new_img = Image.new('RGBA', img.size, (0, 0, 0, 0))

    # paste the original image onto the new image
    keep_width = int(img.size[0] * (1 - shift_fraction))
    new_img.paste(img.crop((img.size[0] - keep_width, 0, img.size[0], img.size[1])), (0, 0))

    # save the new image
    output_path = image_path + '.shifted.png'
    new_img.save(output_path, img_format)

    # create a mask
    mask = Image.new('L', img.size, 0)
    ImageDraw.Draw(mask).rectangle((0, 0, keep_width, img.size[1]), fill=0)
    ImageDraw.Draw(mask).rectangle((keep_width, 0, img.size[0], img.size[1]), fill=255)
    mask_path = image_path + '.mask.png'
    mask.save(mask_path)

    return (output_path, mask_path)


def create_background_image(
        output_file,
        style,
        scene,
        file_to_modify=None,
        mask=None,
        #model='gpt-image-1',
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
        print(f"prompt={prompt}")
        #return

        # generate a new image from scratch
        if not file_to_modify:
            result = client.images.generate(
                model=model,
                prompt=prompt,
                size=size,
                quality=quality,
            )

        # edit file_to_modify
        else:
            print(f"file_to_modify={file_to_modify}")
            result = client.images.edit(
                model=model,
                image=open(file_to_modify, "rb"),
                mask=open(file_to_modify, "rb"),
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
    parser.add_argument('--output_file', required=True)
    parser.add_argument('--input_file', required=True)
    parser.add_argument('--style', default='cartoon, bright colors, bold outlines, fun for kids')
    args = parser.parse_args()

    # extract subscenes from input JSON
    with open(args.input_file, 'rt') as fin:
        data = json.load(fin)
        subscenes = data['subscenes']

    # generate an image of each subscene
    last_subscene_file = None
    mask_file = None
    for i, subscene in enumerate(subscenes):
        subscene_file = args.output_file + f".{i:04}.png"
        logging.info(f"subscene_file={subscene_file}")
        if i==0:
            create_background_image(
                    subscene_file,
                    args.style,
                    subscene,
                    file_to_modify=last_subscene_file,
                    mask=mask_file,
                    )
        else:
            subscene = f"We are transitioning between two related scenes (left) and (right).  The portion on the left is already given, and you should only add in the portion on the right.  Ensure that the left and right smoothly blend together with the same colorschemes and styles. The scenes are <left>{subscenes[i-1]}</left> <right>{subscenes[i]}</right>"
            create_background_image(
                    subscene_file,
                    args.style,
                    subscene,
                    file_to_modify=last_subscene_file,
                    mask=mask_file,
                    )
            asd
        last_subscene_file, mask_file = shift_image(subscene_file, 0.5)
