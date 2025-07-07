import math
import random

import arcade
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
import textwrap

class KapowBubble(arcade.Sprite):
    def __init__(
            self,
            text,
            font_size=46,
            padding=40,
            bubble_color=(255, 255, 255),  # White default background
            text_color=(0, 0, 0),
            border_color=(0, 0, 0),
            spikes=12,          # Number of spikes
            spike_length=3,    # Base length of spikes
            border_width=3,
            ellipse_ratio=1.4,  # Width to height ratio for elliptical shape
            seed=42,            # Seed for deterministic randomness
            **kwargs
            ):
        super().__init__(**kwargs)
        self.config = {}

        # Set up deterministic randomness
        random.seed(seed)

        # Load font and determine text dimensions
        font = PIL.ImageFont.truetype("arial.ttf", font_size)

        # Calculate text dimensions
        text_bbox = font.getbbox(text)
        text_width = text_bbox[2]
        text_height = text_bbox[3]

        # Calculate bubble base dimensions for elliptical shape
        base_width = text_width + padding * 2
        base_height = text_height + padding * 2

        # Ensure minimum size
        base_width = max(base_width, 100)
        base_height = max(base_height, 100)

        # Apply ellipse ratio
        base_width *= ellipse_ratio

        # Calculate radii
        a = base_width / 2  # Semi-major axis (horizontal)
        b = base_height / 2  # Semi-minor axis (vertical)

        # Calculate max possible spike length
        max_spike_length = spike_length * 1.3  # Allow for variation

        # Total size including potential spikes
        total_width = base_width + max_spike_length * 2
        total_height = base_height + max_spike_length * 2
        center_x = total_width / 2
        center_y = total_height / 2

        # Create image
        img = PIL.Image.new("RGBA", (int(total_width), int(total_height)), (0, 0, 0, 0))
        draw = PIL.ImageDraw.Draw(img)

        # Prepare points for the polygon
        outer_points = []
        inner_points = []

        # Generate spike variations first
        spike_variations = []
        for i in range(spikes):
            # Vary spike length between 70-130% of base length
            variation = random.uniform(0.5, 3)
            spike_variations.append(variation)

        # Generate all points
        num_points = spikes * 2
        for i in range(num_points):
            angle = 2 * math.pi * i / num_points

            # Base elliptical point
            base_x = a * math.cos(angle)
            base_y = b * math.sin(angle)

            # Apply spike or valley modification
            if i % 2 == 0:  # Spike points
                spike_index = i // 2
                variation = spike_variations[spike_index]

                # Calculate length with directional adjustments
                length = spike_length * variation
                if abs(math.cos(angle)) > 0.7:  # Horizontal spikes
                    length *= 1.2

                # Calculate spike point - as spike_length approaches 0, this approaches the base point
                x = center_x + base_x + (length * math.cos(angle))
                y = center_y + base_y + (length * math.sin(angle))

                # For inner border points
                inner_x = x - (border_width * math.cos(angle))
                inner_y = y - (border_width * math.sin(angle))
            else:  # Valley points
                # Get adjacent spike variations
                prev_variation = spike_variations[(i-1)//2 % spikes]
                next_variation = spike_variations[i//2 % spikes]

                # Average the width factors of adjacent spikes
                prev_width = 1.0 / prev_variation
                next_width = 1.0 / next_variation
                avg_width = (prev_width + next_width) / 2

                # Valley depth factor - depends on spike_length
                # As spike_length approaches 0, valley_depth_factor approaches 1.0
                valley_depth_factor = 1.0 - 0.7 * min(1.0, spike_length / 10.0)

                # Apply valley depth
                x = center_x + base_x * valley_depth_factor
                y = center_y + base_y * valley_depth_factor

                # Inner border points - move inward perpendicular to ellipse
                normal_x = base_x / a  # Normalized x component of normal vector
                normal_y = base_y / b  # Normalized y component of normal vector
                norm = math.sqrt(normal_x**2 + normal_y**2)
                if norm > 0:
                    inner_x = x - (border_width * normal_x / norm)
                    inner_y = y - (border_width * normal_y / norm)
                else:
                    inner_x, inner_y = x, y

            outer_points.append((x, y))
            inner_points.append((inner_x, inner_y))

        # Draw outer shape (border)
        draw.polygon(outer_points, fill=border_color)

        # Draw inner shape (bubble fill)
        draw.polygon(inner_points, fill=bubble_color)

        # Draw text centered
        text_x = center_x - text_width / 2
        text_y = center_y - text_height / 2
        draw.text((text_x, text_y), text, font=font, fill=text_color)

        # Set up sprite
        self.texture = arcade.Texture(img)
        self.width = total_width
        self.height = total_height


class SpeechBubble(arcade.Sprite):
    def __init__(
            self,
            text,
            max_width=600,
            font_size=46,
            padding=40,
            bubble_color=(255, 255, 255),
            text_color=(0, 0, 0),
            border_color=(0, 0, 0),
            pointer_position="bottom_right",
            border_width=3,
            **kwargs
            ):
        super().__init__(**kwargs)
        self.config = {}

        # Load font and determine text dimensions
        font = PIL.ImageFont.truetype("arial.ttf", font_size)

        # Wrap text to fit max width
        wrapped_lines = textwrap.wrap(text, width=max(1, int(max_width/font_size*1.5)))
        line_heights = [font.getbbox(line)[3] for line in wrapped_lines]

        # Calculate dimensions based on text
        text_width = max([font.getbbox(line)[2] for line in wrapped_lines])
        text_height = sum(line_heights)

        # Size the bubble with padding
        width = text_width + padding * 2
        bubble_height = text_height + padding * 2
        pointer_size = 25
        height = bubble_height + pointer_size  # Extra space for pointer

        # Create image
        img = PIL.Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = PIL.ImageDraw.Draw(img)

        # Draw main bubble shape with thicker border
        draw.rounded_rectangle(
            [(padding/2 - border_width*2, padding/2 - border_width*2),
             (width-padding/2 + border_width*2, bubble_height-padding/2 + border_width*2)],
            radius=15, fill=bubble_color
        )

        # First draw a larger black rounded rectangle
        draw.rounded_rectangle(
            [(padding/2 - border_width, padding/2 - border_width),
             (width-padding/2 + border_width, bubble_height-padding/2 + border_width)],
            radius=15, fill=border_color
        )

        # Then draw the inner white rectangle on top
        draw.rounded_rectangle(
            [(padding/2, padding/2),
             (width-padding/2, bubble_height-padding/2)],
            radius=15-border_width, fill=bubble_color
        )

        # Parse position
        vertical, horizontal = pointer_position.split('_')

        # Set pointer base position
        if vertical == "bottom":
            base_y = bubble_height - padding/2
            tip_y = height - padding/2
        else:  # top
            base_y = padding/2
            tip_y = padding/2 - pointer_size

        if horizontal == "left":
            base_x = width * 0.25
        elif horizontal == "right":
            base_x = width * 0.75
        else:  # center
            base_x = width / 2

        # Create a wavy pointer with concave and convex sides
        pointer_width = 30
        curve_offset = 12  # How much the curve deviates from straight line

        # Base points of pointer
        left_base = (base_x - pointer_width/2, base_y)
        right_base = (base_x + pointer_width/2, base_y)
        tip = (base_x, tip_y)

        # Calculate control points for curved sides
        if vertical == "bottom":
            # Left side (concave)
            left_control = (base_x - pointer_width/2 + curve_offset, base_y + (tip_y - base_y) * 0.5)
            # Right side (convex)
            right_control = (base_x + pointer_width/2 + curve_offset, base_y + (tip_y - base_y) * 0.5)
        else:
            # For top pointer
            left_control = (base_x - pointer_width/2 + curve_offset, base_y + (tip_y - base_y) * 0.5)
            right_control = (base_x + pointer_width/2 + curve_offset, base_y + (tip_y - base_y) * 0.5)

        # Create a list of points for the bezier curves
        # Left side - concave curve
        left_curve = []
        for t in [i/10 for i in range(11)]:
            # Quadratic Bezier curve formula
            x = (1-t)**2 * left_base[0] + 2*(1-t)*t * left_control[0] + t**2 * tip[0]
            y = (1-t)**2 * left_base[1] + 2*(1-t)*t * left_control[1] + t**2 * tip[1]
            left_curve.append((x, y))

        # Right side - convex curve
        right_curve = []
        for t in [i/10 for i in range(11)]:
            x = (1-t)**2 * tip[0] + 2*(1-t)*t * right_control[0] + t**2 * right_base[0]
            y = (1-t)**2 * tip[1] + 2*(1-t)*t * right_control[1] + t**2 * right_base[1]
            right_curve.append((x, y))

        # Combine the curves and fill
        pointer_points = left_curve + right_curve
        draw.polygon(pointer_points, fill=border_color, outline=None)

        # Draw the inner pointer with slight inset to create border effect
        inset = border_width * 0.8
        left_inset_curve = []
        right_inset_curve = []

        for t in [i/10 for i in range(11)]:
            # Inset the tip and control points slightly
            inset_tip = (tip[0], tip[1] - inset if vertical == "bottom" else tip[1] + inset)

            # Left inset curve
            x = (1-t)**2 * (left_base[0] + inset) + 2*(1-t)*t * (left_control[0] + inset/2) + t**2 * inset_tip[0]
            y = (1-t)**2 * left_base[1] + 2*(1-t)*t * left_control[1] + t**2 * inset_tip[1]
            left_inset_curve.append((x, y))

            # Right inset curve
            x = (1-t)**2 * inset_tip[0] + 2*(1-t)*t * (right_control[0] - inset/2) + t**2 * (right_base[0] - inset)
            y = (1-t)**2 * inset_tip[1] + 2*(1-t)*t * right_control[1] + t**2 * right_base[1]
            right_inset_curve.append((x, y))

        inset_pointer_points = left_inset_curve + right_inset_curve
        draw.polygon(inset_pointer_points, fill=bubble_color, outline=None)

        # Draw text
        y_offset = padding
        for line in wrapped_lines:
            draw.text((padding, y_offset), line, font=font, fill=text_color)
            y_offset += font.getbbox(line)[3] + 2

        # Set up sprite
        self.texture = arcade.Texture(img)
        self.width = width
        self.height = height



