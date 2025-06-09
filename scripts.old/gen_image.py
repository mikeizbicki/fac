#!/usr/bin/env python3

# parse command line options
import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output_file')
parser.add_argument('--scene')
parser.add_argument('--style', default='cartoon, bright colors, bold outlines, fun for kids')
#parser.add_argument('--style', default='grimdark cartoon')
#parser.add_argument('--style', default='studio ghibli')
args = parser.parse_args()

# we try to open the output file first before accessing API;
# this way, if there is a problem with the file, we won't waste API credits
with open(args.output_file, "wb") as f:

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
The scene will be formatted as a JSON list of "subscenes"; all of the subscenes should be included in a single image.  (Do not split it up like a storyboard/comic.)
There should be no text.
Style: {args.style}
Scene: {args.scene}
"""

    # get image from API 
    result = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1536x1024",
        quality="low",
    )
    image_base64 = result.data[0].b64_json
    image_bytes = base64.b64decode(image_base64)
    f.write(image_bytes)
