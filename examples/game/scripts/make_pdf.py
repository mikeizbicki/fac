from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image
import os
import argparse

def crop_whitespace(img):
    """Crop whitespace from around the image"""
    # Convert to RGBA if not already
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    # Get image data
    data = img.getdata()

    # Find bounding box of non-transparent and non-white pixels
    width, height = img.size
    left, top, right, bottom = width, height, 0, 0

    for y in range(height):
        for x in range(width):
            pixel = data[y * width + x]
            # Check if pixel is not transparent and not white
            if len(pixel) == 4:  # RGBA
                if pixel[3] > 0 and not (pixel[0] > 240 and pixel[1] > 240 and pixel[2] > 240):
                    left = min(left, x)
                    top = min(top, y)
                    right = max(right, x)
                    bottom = max(bottom, y)

    # If we found content, crop to it
    if left < right and top < bottom:
        return img.crop((left, top, right + 1, bottom + 1))

    return img

def create_tiled_pdf(image_paths, output_pdf, tile_size_inches, num_pages):
    # Register Greek font
    pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))

    # PDF setup
    c = canvas.Canvas(output_pdf, pagesize=letter)
    page_width, page_height = letter
    margin = 0.25 * inch
    tile_size = tile_size_inches * inch

    # Calculate tiles per row/column per page
    tiles_per_row = int((page_width - 2 * margin) // tile_size)
    tiles_per_col = int((page_height - 2 * margin) // tile_size)
    tiles_per_page = tiles_per_row * tiles_per_col
    total_tiles = tiles_per_page * num_pages

    # Calculate tiles per image type
    tiles_per_image = total_tiles // len(image_paths)
    extra_tiles = total_tiles % len(image_paths)

    # Prepare images and names
    images_data = []
    for image_path in image_paths:
        filename = os.path.basename(image_path)
        greek_name = filename.replace('.png', '')

        # Load and crop image
        img = Image.open(image_path)
        img = crop_whitespace(img)

        # Convert PNG to remove transparency issues
        if img.mode in ('RGBA', 'LA'):
            # Create white background
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])  # Use alpha channel as mask
            img = background

        images_data.append((img, greek_name))

    # Create tile distribution
    tile_queue = []
    for i, (img, greek_name) in enumerate(images_data):
        count = tiles_per_image + (1 if i < extra_tiles else 0)
        tile_queue.extend([(img, greek_name)] * count)

    # Create tiles across multiple pages
    tile_index = 0
    for page in range(num_pages):
        if page > 0:
            c.showPage()  # Start new page

        for row in range(tiles_per_col):
            for col in range(tiles_per_row):
                if tile_index >= len(tile_queue):
                    break

                x = margin + col * tile_size
                y = page_height - margin - (row + 1) * tile_size

                img, greek_name = tile_queue[tile_index]

                # Draw image (centered, with horizontal margin, leave space for text at top)
                img_width = 0.99 * tile_size
                img_height = tile_size - 0.4 * inch  # More space for text with padding
                img_x = x + (tile_size - img_width) / 2
                c.drawImage(ImageReader(img), img_x, y, width=img_width, height=img_height, preserveAspectRatio=True)

                # Draw Greek text at top with padding
                c.setFont("DejaVuSans", 20)
                text_y = y + tile_size - 0.35 * inch  # Added padding from top edge
                c.drawCentredString(x + tile_size/2, text_y, greek_name)

                # Draw light gray outline
                c.setStrokeColor(colors.lightgrey)
                c.setLineWidth(0.5)
                c.rect(x, y, tile_size, tile_size)

                tile_index += 1

            if tile_index >= len(tile_queue):
                break

    c.save()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Create a tiled PDF from Greek tile images')
    parser.add_argument('image_paths', nargs='+', help='Path(s) to the input image file(s)')
    parser.add_argument('-o', '--output', default='tiles.pdf', help='Output PDF filename (default: tiles.pdf)')
    parser.add_argument('-s', '--tile_size', type=float, default=2.0, help='Size of tiles in inches (default: 2.0)')
    parser.add_argument('-p', '--pages', type=int, default=1, help='Number of pages to spread tiles across (default: 1)')

    args = parser.parse_args()

    create_tiled_pdf(args.image_paths, args.output, args.tile_size, args.pages)
    print(f"PDF created: {args.output}")
