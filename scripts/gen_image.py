from openai import OpenAI
import base64
client = OpenAI()

prompt = """
A young boy named Rider (about 8 years old) standing in front of a tall tower. The tower is colorful and has windows. The boy is smiling and pointing at the tower. The Hebrew words "נַעַר" (boy) and "מִגְדָּל" (tower) are visible in the scene.
"""

result = client.images.generate(
    #model="gpt-image-1",
    model="dall-e-2",
    prompt=prompt,
    #size="1536x1024",
    #quality="low",
)

image_base64 = result.data[0].b64_json

import code; code.interact(local=locals())
image_bytes = base64.b64decode(image_base64)

# Save the image to a file
with open("otter.png", "wb") as f:
    f.write(image_bytes)
