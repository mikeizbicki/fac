#!/usr/bin/env python3

# setup logging
import logging
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s',
    '%Y-%m-%d %H:%M:%S'
))
logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.propagate = False
logger.setLevel(logging.DEBUG)

# import modules
from collections import defaultdict
import json
import math
import os
import random
import time

import arcade
import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
import textwrap



class SpriteManager():
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sprites = arcade.SpriteList()
        self._name_to_sprite = {}
        self._name_positions = {}
        self._movements = {}
        self._foreground_elements = set()

        self.screen_width = 1280
        self.screen_height = 720

        # setup the physics engine
        self.physics_engine = arcade.PymunkPhysicsEngine(damping=1.0, gravity=(0, -1500))

        # create a floor for the scene
        floor_path = 'stories/tmp/Ground&Stone/Ground/ground2.png'
        floor_img = arcade.load_image(floor_path)
        floor_height = 128
        floor_width = int(floor_img.width * (floor_height / floor_img.height))
        floor_img = floor_img.resize((floor_width, floor_height))
        floor_texture = arcade.Texture(floor_img, hit_box_algorithm=arcade.hitbox.BoundingHitBoxAlgorithm())
        for i in range(20):
            sprite = arcade.Sprite(floor_texture)
            sprite.center_x = floor_width * i
            sprite.center_y = floor_height / 2
            self.sprites.append(sprite)
        self.physics_engine.add_sprite_list(
            self.sprites,
            friction=0.7,
            collision_type="wall",
            body_type=arcade.PymunkPhysicsEngine.STATIC,
        )

        def begin_handler(sprite1, sprite2, arbiter, space, data):
            return not (sprite1 in self._foreground_elements or sprite2 in self._foreground_elements)

        self.physics_engine.add_collision_handler('element', 'element', begin_handler=begin_handler)

        # set the values for stage directions
        self.placements = {
            'stage-left': {'x': 100, 'y': floor_height},
            'stage-right': {'x': self.screen_width-100, 'y': floor_height},
            'stage-center': {'x': self.screen_width/2, 'y': floor_height},
            }

    def add(self, name, sprite=None, position=None, background=False):
        assert name not in self._name_to_sprite
        if sprite is None:
            sprite = Element(name)
        self.sprites.append(sprite)
        self._name_to_sprite[name] = sprite
        self._name_positions[name] = position

        if position:
            x, y = self.position_to_coordinates(sprite, position)
            sprite.center_x = x
            sprite.center_y = y
        if not background and isinstance(sprite, Element):
            self.physics_engine.add_sprite(
                sprite,
                friction=1.0,
                collision_type="element",
                moment_of_inertia=arcade.PymunkPhysicsEngine.MOMENT_INF,
                max_horizontal_velocity=200,
                max_vertical_velocity=1000,
            )

    def add_movement(self, name, position):
        self._movements[name] = position
        if name in self._name_positions:
            del self._name_positions[name]

    def remove(self, name):
        self.sprites.remove(self._name_to_sprite[name])
        del self._name_to_sprite[name]
        if name in self._name_positions:
            del self._name_positions[name]

    def set_position(self, name, pos):
        assert name in self._name_to_sprite
        self._name_positions[name] = pos

    def update_positions(self):
        # first handle static positions
        for name, pos in list(self._name_positions.items()):
            sprite = self._name_to_sprite[name]
            x, y = self.position_to_coordinates(sprite, pos)
            sprite.center_x = x
            sprite.center_y = y

        # next apply forces to handle movement
        for name, pos in list(self._movements.items()):
            sprite = self._name_to_sprite[name]
            x, y = self.position_to_coordinates(sprite, pos)
            if x < sprite.center_x:
                force = (-4000, 0)
            else:
                force = (4000, 0)
            self.physics_engine.apply_force(sprite, force)
            self.physics_engine.set_friction(sprite, 0)
            self._foreground_elements.add(sprite)

            if abs(x - sprite.center_x) < 32:
                self._foreground_elements.remove(sprite)
                self.physics_engine.set_friction(sprite, 1.0)
                del self._movements[name]
        
        # finally step the physics engine to trigger the movement
        self.physics_engine.step()

    def position_to_coordinates(self, sprite, position):
        if position in self.placements:
            x = self.placements[position]['x']
            y = sprite.height / 2 + self.placements[position]['y']

        elif ':' in position:
            loc, target_name = position.split(':')
            loc = loc.strip()
            target_name = target_name.strip()
            target = self._name_to_sprite[target_name]

            offset_x = 0
            offset_y = -target.center_y + 128 + sprite.center_y - sprite.bottom
            padding = 20
            if 'above' in loc:
                offset_y = target.height / 2 + sprite.height / 2 + padding
            if 'below' in loc:
                offset_y = target.height / 2 + sprite.height / 2 + padding
            if 'left' in loc:
                offset_x = (target.left - target.center_x) - (sprite.right - sprite.center_x) - padding
            if 'right' in loc:
                offset_x = (target.right - target.center_x) - (sprite.left - sprite.center_x) + padding
            x = target.center_x + offset_x
            y = target.center_y + offset_y

        else:
            raise ValueError(f'bad position="{position}"')

        return (x, y)

LEFT_FACING = 1
RIGHT_FACING = 0
DISTANCE_TO_CHANGE_TEXTURE = 20
class Element(arcade.Sprite):

    def __init__(
            self,
            name
            ):
        super().__init__(name=name, scale=1)

        name = name.lower()
        self.name = name
        root_dir = f'stories/elements/{name}'

        # load JSON info
        json_path = os.path.join(root_dir, 'sprite.json')
        with open(json_path) as fin:
            element_data = json.load(fin)

        def load_texture(image_path):
            img = arcade.load_image(image_path)
            new_height = int(256 * element_data['height'])
            new_width = int(img.width * (new_height / img.height))
            img = img.resize((new_width, new_height))
            return arcade.Texture(img)

        # load images
        if False: #name == 'aurelia':
            main_path = ":resources:images/animated_characters/female_adventurer/femaleAdventurer"
            #main_path = ":resources:images/animated_characters/female_person/femalePerson"
            # main_path = ":resources:images/animated_characters/male_person/malePerson"
            # main_path = ":resources:images/animated_characters/male_adventurer/maleAdventurer"
            # main_path = ":resources:images/animated_characters/zombie/zombie"
            # main_path = ":resources:images/animated_characters/robot/robot"

            # Load textures for idle, jump, and fall states
            idle_texture = load_texture(f"{main_path}_idle.png")
            jump_texture = load_texture(f"{main_path}_jump.png")
            fall_texture = load_texture(f"{main_path}_fall.png")
            self.idle_texture_pair = idle_texture, idle_texture.flip_left_right()
            self.jump_texture_pair = jump_texture, jump_texture.flip_left_right()
            self.fall_texture_pair = fall_texture, fall_texture.flip_left_right()
            self.walk_textures = []
            for i in range(8):
                texture = load_texture(f"{main_path}_walk{i}.png")
                self.walk_textures.append((texture, texture.flip_left_right()))
            self.texture = self.idle_texture_pair[0]
            self.character_face_direction = RIGHT_FACING
            self.cur_texture = 0
            self.x_odometer = 0
        else:
            try:
                import glob
                import re
                self.textures = defaultdict(lambda: defaultdict(lambda: []))
                for image_path in sorted(glob.glob(root_dir + '/sprites/*.png')):
                    img = arcade.load_image(image_path)
                    new_height = int(256 * element_data['height'])
                    new_width = int(img.width * (new_height / img.height))
                    img = img.resize((new_width, new_height))
                    texture = arcade.Texture(img)
                    action = re.sub(r'\d*\.[^.]+$', '', os.path.basename(image_path))
                    self.textures[action][RIGHT_FACING].append(texture)
                    self.textures[action][LEFT_FACING].append(texture.flip_left_right())
                print(f"list(self.textures.keys())={list(self.textures.keys())}")
                #self.texture = self.textures['idle'][0]
                self.character_face_direction = RIGHT_FACING
                self.action = 'idle'
                self.action_seq_id = 0
                self.x_odometer = 0
                self.set_action('idle')
            except IndexError:
                self.texture = load_texture(root_dir + '/sprite.png')

            #self.texture = arcade.Texture(img, hit_box_algorithm=arcade.hitbox.BoundingHitBoxAlgorithm())

    def pymunk_moved(self, physics_engine, dx, dy, d_angle):
        DEAD_ZONE = 0.1
        # Figure out if we need to face left or right
        if dx < -DEAD_ZONE and self.character_face_direction == RIGHT_FACING:
            self.character_face_direction = LEFT_FACING
        elif dx > DEAD_ZONE and self.character_face_direction == LEFT_FACING:
            self.character_face_direction = RIGHT_FACING
        self.x_odometer += dx

        if abs(dx) >= DEAD_ZONE:
            self.set_action('walk')
        else:
            self.set_action('idle')

        is_on_ground = physics_engine.is_on_ground(self)
        if not is_on_ground:
            if dy > DEAD_ZONE:
                self.set_action('jump')
            elif dy < -DEAD_ZONE:
                self.set_action('fall')

        if abs(self.x_odometer) > DISTANCE_TO_CHANGE_TEXTURE:

            # Reset the odometer
            self.x_odometer = 0

            # Advance the walking animation
            self.action_seq_id += 1
            if self.action_seq_id >= len(self.textures[self.action]):
                self.action_seq_id = 0

    def set_action(self, action):
        if action != self.action:
            self.x_odometer = 0
            self.action_seq_id = 0
            self.action = action
        self.texture = self.textures[action][self.character_face_direction][self.action_seq_id]


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


class GameWindow(arcade.Window):

    def __init__(self):

        # init arcade Window
        width = 1536
        height = 1024

        self.screen_width = 1280
        self.screen_height = 720

        super().__init__(self.screen_width, self.screen_height, 'test')

        script_path = 'stories/vignettes/doors/script.json'
        self.load_script(script_path)

    def load_script(self, script_path):

        # load the JSON file
        with open(script_path) as fin:
            script = json.load(fin)

        # prepare the scene
        if script['scene']['type'] == 'plain-background':

            # load the background image
            path_background = f'family_story/story2_moses/sublocations/Cave Hideout.png'
            self.background = arcade.load_texture(path_background)
            self.background_color = arcade.color.AMAZON

        else:
            assert False

        # create the initial elements
        self.sprites = SpriteManager()
        for i, element in enumerate(script.get('elements', [])):
            self.sprites.add(element['name'], position=element['position'], background=element.get('background', False))

        # load events
        self.events = script['events']
        self.events_config = {
            'autostep': True,
            'min_time': 0.5,
            }
        self.event_index = 0
        self.set_event(self.events[self.event_index])

    def set_event(self, event):
        logger.debug(f'event={event}')

        # remove old event sprites if applicable
        try:
            for event_sprite_name in self.event_info['event_sprite_names']:
                self.sprites.remove(event_sprite_name)
        except AttributeError:
            pass

        # create new event
        self.event_info = {
            'start_time': time.time(),
            'num_frames': 0,
            'event_sprite_names': [],
            'event': event,
            }

        if event['type'] == 'dialogue':
            bubble = SpeechBubble(event['text'])
            bubble_name = '__EVENT_BUBBLE__'
            self.sprites.add(bubble_name, bubble, 'above: ' + event['element'])
            self.event_info['event_sprite_names'].append(bubble_name)
        elif event['type'] == 'sound_effect':
            bubble = KapowBubble(event['text'])
            bubble_name = '__EVENT_BUBBLE__'
            self.sprites.add(bubble_name, bubble, event['position'])
            self.event_info['event_sprite_names'].append(bubble_name)
        elif event['type'] == 'add_element':
            self.sprites.add(event['element'], position=event['position'])
        elif event['type'] == 'movement':
            self.sprites.add_movement(event['element'], event['position'])
        else:
            logger.warning(f'event type "{event["type"]}" not supported')

    def on_update(self, delta_time):

        # update events
        event_runtime = time.time() - self.event_info['start_time']

        if len(self.sprites._movements) == 0 and event_runtime >= self.events_config['min_time']:
            self.event_index += 1
            if self.event_index < len(self.events):
                event = self.events[self.event_index]
                self.set_event(event)

        # update scene
        self.sprites.update_positions()

        # update event_info
        self.event_info['num_frames'] += 1

    def on_draw(self):
        self.clear()

        # draw the background texture
        arcade.draw_texture_rect(
            self.background,
            arcade.LBWH(0, 0, self.screen_width, self.screen_height),
        )

        # draw the sprites
        self.sprites.sprites.draw()
        for sprite in self.sprites.sprites:
            sprite.draw_hit_box()


if __name__ == "__main__":
    window = GameWindow()
    arcade.run()
