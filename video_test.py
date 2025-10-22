from openai import OpenAI
from pathlib import Path
import sys
import time

openai = OpenAI()

input_file = 'books/levelA/lost_toy/page_3/art_1280x720.png'
action = 'the dinosaur and panda greet each other and the dinosaur moves to sit with the panda'
model = 'sora-2-pro'
output_file = f'{input_file}__{model}.mp4'

video = openai.videos.create(
    model="sora-2",
    prompt=action,
    input_reference=Path(input_file),
    size="1280x720",
    seconds=4,
)

print("Video generation started:", video)

progress = getattr(video, "progress", 0)
bar_length = 30

while video.status in ("in_progress", "queued"):
    # Refresh status
    video = openai.videos.retrieve(video.id)
    progress = getattr(video, "progress", 0)

    filled_length = int((progress / 100) * bar_length)
    bar = "=" * filled_length + "-" * (bar_length - filled_length)
    status_text = "Queued" if video.status == "queued" else "Processing"

    sys.stdout.write(f"\n{status_text}: [{bar}] {progress:.1f}%")
    sys.stdout.flush()
    time.sleep(2)

# Move to next line after progress loop
sys.stdout.write("\n")

if video.status == "failed":
    message = getattr(
        getattr(video, "error", None), "message", "Video generation failed"
    )
    print(message)
    asd

print("Video generation completed:", video)
print("Downloading video content...")

content = openai.videos.download_content(video.id, variant="video")
content.write_to_file(output_file)

print("Wrote video.mp4")
