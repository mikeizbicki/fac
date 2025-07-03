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
import glob
import json
import os
import re
import sys
import time

import arcade
import numpy as np
import pyglet
from .Bubbles import *
from .Media import *


class CameraManager():
    def __init__(self, scene_manager):
        self.camera = arcade.Camera2D()
        self.scene_manager = scene_manager
        self._camera_must_draw_sprites = set(['AARON', 'PANDA'])
        pass

    def update(self):
        self.camera.use()

        lrbt = None
        for sprite in self.scene_manager.sprites:
            if isinstance(sprite, Element) and sprite.name in self._camera_must_draw_sprites:
                if not lrbt:
                    lrbt = arcade.LRBT(sprite.left, sprite.right, sprite.bottom, sprite.top)
                else:
                    lrbt = arcade.LRBT(
                        min(lrbt.left, sprite.left),
                        max(lrbt.right, sprite.right),
                        min(lrbt.bottom, sprite.bottom),
                        max(lrbt.top, sprite.top),
                        )
        padding = 64
        lrbt = arcade.LRBT(
            lrbt.left - padding,
            lrbt.right + padding,
            lrbt.bottom - padding,
            lrbt.top + padding,
            )

        max_camera_velocity = 12
        self.camera_move_clamp = 'l1'
        if hasattr(self, 'prev_camera_lrbt'):
            if self.camera_move_clamp == 'l0':
                def clamp(a, b):
                    if a > b:
                        return b
                    elif a < -b:
                        return -b
                    else:
                        return a
                lrbt = arcade.LRBT(
                        self.prev_camera_lrbt.left + clamp(lrbt.left - self.prev_camera_lrbt.left, max_camera_velocity),
                        self.prev_camera_lrbt.right + clamp(lrbt.right - self.prev_camera_lrbt.right, max_camera_velocity),
                        self.prev_camera_lrbt.bottom + clamp(lrbt.bottom - self.prev_camera_lrbt.bottom, max_camera_velocity),
                        self.prev_camera_lrbt.top + clamp(lrbt.top - self.prev_camera_lrbt.top, max_camera_velocity),
                        )

            elif self.camera_move_clamp == 'l1':
                total_diff = (
                        abs(self.prev_camera_lrbt.left - lrbt.left) +
                        abs(self.prev_camera_lrbt.right - lrbt.right) +
                        abs(self.prev_camera_lrbt.bottom - lrbt.bottom) +
                        abs(self.prev_camera_lrbt.top - lrbt.top)
                        )
                if total_diff >= max_camera_velocity:
                    move_ratio = max_camera_velocity / total_diff
                else:
                    move_ratio = 1
                lrbt = arcade.LRBT(
                        self.prev_camera_lrbt.left + move_ratio * (lrbt.left - self.prev_camera_lrbt.left),
                        self.prev_camera_lrbt.right + move_ratio * (lrbt.right - self.prev_camera_lrbt.right),
                        self.prev_camera_lrbt.bottom + move_ratio * (lrbt.bottom - self.prev_camera_lrbt.bottom),
                        self.prev_camera_lrbt.top + move_ratio * (lrbt.top - self.prev_camera_lrbt.top),
                        )
        self.prev_camera_lrbt = lrbt
        width = lrbt.right - lrbt.left
        height = lrbt.top - lrbt.bottom
        aspect = width / height
        target_aspect = 16/9
        if aspect > target_aspect:
            ydiff = (width / target_aspect - height) / 2
            lrbt = arcade.LRBT(lrbt.left, lrbt.right, lrbt.bottom-ydiff, lrbt.top+ydiff)
        if aspect < target_aspect:
            xdiff = (height * target_aspect - width) / 2
            lrbt = arcade.LRBT(lrbt.left-xdiff, lrbt.right+xdiff, lrbt.bottom, lrbt.top)
        #self.prev_camera_lrbt = lrbt
        if lrbt.bottom < 0:
            lrbt = arcade.LRBT(
                    lrbt.left,
                    lrbt.right,
                    0,
                    lrbt.top - lrbt.bottom,
                    )
        self.camera.update_values(lrbt, viewport=False, position=True)
        #self.camera.position = (self.screen_width / 2 - 100, self.screen_height / 2)


class SceneManager():

    def __init__(self, scene, screen_width, screen_height, output_file, **kwargs):
        super().__init__(**kwargs)
        self.camera_manager = CameraManager(self)

        self.sprites = arcade.SpriteList()
        self._name_to_sprite = {}
        self._name_positions = {}
        self._movements = {}
        self._foreground_elements = set()

        self.pyglet_sound_player = None

        # setup video recorder
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.video_recorder = VideoRecorder(
                self.screen_width,
                self.screen_height,
                fps=30,
                output_file=output_file,
                )
        self.video_recorder.__enter__()

        # load scene config
        assert scene['type'] == 'plain-background'
        scene.setdefault('walls', False)
        scene.setdefault('background_image_path', f'backgrounds/wall-interior.png')
        scene.setdefault('floor_image_path', f'scene/floor/carpet.png')
        floor_height = 128

        # load the background image
        self.background = arcade.load_texture(scene['background_image_path'])
        lr_padding = 0.2 * self.screen_width
        background_newheight = self.screen_width / (self.background.width / self.background.height) + 2 * lr_padding * self.screen_height / self.screen_width
        self.background_LBWH = arcade.LBWH(
                -lr_padding,
                floor_height,
                floor_height + self.screen_width + lr_padding * 2,
                background_newheight,
                )

        self.img_floor = arcade.load_texture(scene['floor_image_path'])
        self.img_floor_LBWH = arcade.LBWH(
                self.background_LBWH.left,
                self.background_LBWH.bottom - self.background_LBWH.height//2,
                self.background_LBWH.width,
                self.background_LBWH.height,
                )

        # load voices
        self.voices = {}
        voices_path = 'vignettes/animals/voices/'
        for element in os.listdir(voices_path):
            self.voices[element] = {}
            element_path = os.path.join(voices_path, element)
            for text in os.listdir(element_path):
                if text.endswith('.wav'):
                    text_path = os.path.join(element_path, text)
                    text = text[:-4]
                    self.voices[element][text] = arcade.load_sound(text_path)
                    self.voices[element][text].path = text_path

        # setup the physics engine
        self.physics_engine = arcade.PymunkPhysicsEngine(damping=1.0, gravity=(0, -1500))

        # create a floor for the scene
        self.floor = arcade.SpriteList()
        floor_path = 'tmp/Ground&Stone/Ground/ground2.png'
        floor_img = arcade.load_image(floor_path)
        floor_width = int(floor_img.width * (floor_height / floor_img.height))
        floor_img = floor_img.resize((floor_width, floor_height))
        floor_texture = arcade.Texture(floor_img, hit_box_algorithm=arcade.hitbox.BoundingHitBoxAlgorithm())
        for i in range(-20, 30):
            #for depth in range(2, -3, -1):
            for depth in range(-2, 3):
                sprite = arcade.Sprite(floor_texture)
                sprite.center_x = floor_width * i
                sprite.center_y = floor_height / 2 - 32 - depth * 32
                sprite.depth = depth
                self.floor.append(sprite)
        self.physics_engine.add_sprite_list(
            self.floor,
            friction=0.7,
            collision_type="floor",
            body_type=arcade.PymunkPhysicsEngine.STATIC,
        )

        # elements should only collide with floors of the same depth
        def floor_handler(element, floor, arbiter, space, data):
            collide = floor.depth >= element.depth
            logger.warning(f'element.name={element.name}, element.depth={element.depth}, floor.depth={floor.depth}, collide={collide}')
            return collide
        self.physics_engine.add_collision_handler(
                'element',
                'floor',
                begin_handler=floor_handler,
                )

        # add walls on either side of the scene
        self.wall = arcade.SpriteList()
        if scene['walls']:
            for i in range(20):
                sprite = arcade.Sprite(floor_texture)
                sprite.center_x = 0 #-floor_width / 2
                sprite.center_y = floor_height * (i + 1) + floor_height / 2
                self.wall.append(sprite)
                sprite = arcade.Sprite(floor_texture)
                sprite.center_x = self.screen_width #- floor_width / 2
                sprite.center_y = floor_height * (i + 1) + floor_height / 2
                self.wall.append(sprite)
        self.physics_engine.add_sprite_list(
            self.wall,
            friction=0.7,
            collision_type="wall",
            body_type=arcade.PymunkPhysicsEngine.STATIC,
        )

        # if an element collides with the wall, emit a warning
        def wall_handler(sprite1, sprite2, arbiter, space, data):
            name = getattr(sprite1, 'name', None) or getattr(sprite2, 'name')
            logger.warning(f'element {name} collided with wall; this may disrupt movement of other sprites')
            return True
        self.physics_engine.add_collision_handler(
                'wall',
                'element',
                begin_handler=wall_handler,
                )

        # setup the collision handler
        # NOTE:
        # by default, all sprites that have been added to the physics engine will collide;
        # if a begin_handler function returns False,
        # then the physics engine will not process a collision between the two sprites;
        def begin_handler(sprite1, sprite2, arbiter, space, data):
            collide = abs(sprite1.depth - sprite2.depth) <= 0.5
            logger.debug(f'element overlap: {sprite1.name} {sprite1.depth} {sprite2.name} {sprite2.depth}; collide={collide}')
            return collide
        self.physics_engine.add_collision_handler(
                'element',
                'element',
                begin_handler=begin_handler,
                )
        # set the values for stage directions
        xy_offset = 50
        self.placements = {
            'stage-left': {'x': xy_offset, 'y': floor_height},
            'stage-right': {'x': self.screen_width - xy_offset, 'y': floor_height},
            'stage-center': {'x': self.screen_width / 2, 'y': floor_height},
            }

    def draw(self):
        self.camera_manager.update()

        # draw the background texture
        arcade.draw_texture_rect(
            self.img_floor,
            self.img_floor_LBWH,
        )
        arcade.draw_texture_rect(
            self.background,
            self.background_LBWH,
        )

        # NOTE:
        # sprites will be drawn in the order they are in the sprite list;
        # sorting based on depth ensures that items will be drawn in the correct order;
        # sorting can be slow if there's a very large number of sprites;
        # so this could could be made more efficient to only sort when needed
        self.sprites.sort(key=lambda sprite: sprite.depth)

        # draw the sprites
        #self.floor.draw()
        #self.wall.draw()
        self.sprites.draw()
        #for sprite in self.sprites:
            #sprite.draw_hit_box()

        self._save_video_frame()

    def _save_video_frame(self):
        '''
        This is AI-generated code that extracts the video frame
        and registers it with the video_recorder.
        It could be simplified considerably,
        but there is some possible future debugging needed to certain handle edge cases
        and so I am leaving it unmodified.
        '''
        buffer = pyglet.image.get_buffer_manager().get_color_buffer()
        image_data = buffer.get_image_data()
        width = image_data.width
        height = image_data.height
        pitch = image_data.pitch  # Bytes per row
        format_str = image_data.format
        #print(f"Image dimensions: {width}x{height}, pitch: {pitch}, format: {format_str}")

        # Get raw data
        raw_data = image_data.get_data()
        arr = np.frombuffer(raw_data, dtype=np.uint8)

        # Determine bytes per pixel
        if 'RGBA' in format_str:
            bytes_per_pixel = 4
        elif 'RGB' in format_str:
            bytes_per_pixel = 3
        else:
            bytes_per_pixel = len(format_str)  # Fallback

        # Reshape with proper stride handling
        arr = arr.reshape(height, pitch // bytes_per_pixel, bytes_per_pixel)

        # Ensure proper orientation
        arr = arr[::-1]  # Flip vertically (OpenGL often has inverted Y)

        # If we need just RGB (for video), take only the first 3 channels
        # and only the actual width (not the padded width)
        if bytes_per_pixel >= 3:
            arr = np.ascontiguousarray(arr[:, :width, :3])

        # Now arr should be correctly shaped as (height, width, 3) for RGB data
        self.video_recorder.add_frame(arr)

    def add_voice(self, name, text):
        self.pyglet_sound_player = arcade.play_sound(self.voices[name][text])
        self.video_recorder.add_audio(self.voices[name][text].path)

    def has_audio(self):
        # NOTE:
        # for some reason, the pyarcade code for detecting if audio is playing
        # doesn't work when the program is run in headless mode;
        # internally, pyarcade uses pyglet for generating the audio;
        # the code below directly uses the pyglet api to determine if audio is playing
        if self.pyglet_sound_player is None:
            return False
        if self.pyglet_sound_player.source is None:
            return False
        return not self.pyglet_sound_player.time > self.pyglet_sound_player.source.duration

    def add(self, name, sprite=None, position=None, background=False, depth=0.0):
        assert name not in self._name_to_sprite
        if sprite is None:
            sprite = Element(name)
        sprite.depth = depth
        self.sprites.append(sprite)
        self._name_to_sprite[name] = sprite
        self._name_positions[name] = position

        if position:
            x, y = self.position_to_coordinates(sprite, position)
            sprite.center_x = x
            sprite.center_y = y
        if not background and isinstance(sprite, Element):
            self._reset_element_physics(sprite)

    def _reset_element_physics(self, sprite):
        try:
            self.physics_engine.remove_sprite(sprite)
        except KeyError:
            pass
        self.physics_engine.add_sprite(
            sprite,
            friction=1.0,
            collision_type="element",
            moment_of_inertia=arcade.PymunkPhysicsEngine.MOMENT_INF,
            max_horizontal_velocity=200,
            max_vertical_velocity=1000,
        )

    def add_movement(self, name, position):
        sprite = self._name_to_sprite[name]
        sprite.depth = 1.0
        self._reset_element_physics(sprite)
        self._movements[name] = position
        if name in self._name_positions:
            del self._name_positions[name]
        self.camera_manager._camera_must_draw_sprites.add(name)

    def interact(self, sub_name, obj_name):
        sub = self._name_to_sprite[sub_name]
        sub.set_state('interact')
        obj = self._name_to_sprite[obj_name]
        if obj.state == 'closed':
            obj.set_state('open')
        else:
            obj.set_state('closed')
        self.camera_manager._camera_must_draw_sprites.add(sub_name)
        self.camera_manager._camera_must_draw_sprites.add(obj_name)

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

            if abs(x - sprite.center_x) < 16:
                sprite.depth = 0
                self._reset_element_physics(sprite)
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
            if 'inside' in loc:
                padding = -10
            else:
                padding = 40

            if 'above' in loc:
                offset_y = (target.top - target.center_y) - (sprite.bottom - sprite.center_y) + padding
            if 'below' in loc:
                offset_y = (target.bottom - target.center_y) - (sprite.top - sprite.center_y) + padding
            if 'on' in loc:
                offset_y = padding

            if 'front' in loc:
                if target.right < sprite.left:
                    loc = 'right'
                elif target.left > sprite.right:
                    loc = 'left'
                #else:
                    #offset_x = sprite.center_x - target.center_x

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
        self.__old_center_x = self.center_x

        name = name
        self.name = name
        root_dir = f'elements/{name}'

        # load JSON info
        json_path = os.path.join(root_dir, 'sprite.json')
        with open(json_path) as fin:
            self.config = json.load(fin)
            self.config.setdefault('default_state', 'idle')
            self.config.setdefault('min_state_time', 1.5)

        # load state textures
        self.textures = {}
        for image_path in sorted(glob.glob(root_dir + '/sprites/*.png')):
            img = arcade.load_image(image_path)
            new_height = int(256 * self.config['height'])
            new_width = int(img.width * (new_height / img.height))
            img = img.resize((new_width, new_height))
            texture = arcade.Texture(img)
            state = re.sub(r'\d*\.[^.]+$', '', os.path.basename(image_path))
            if state not in self.textures:
                self.textures[state] = {
                    RIGHT_FACING: [],
                    LEFT_FACING: [],
                }
            self.textures[state][RIGHT_FACING].append(texture)
            self.textures[state][LEFT_FACING].append(texture.flip_left_right())

        # set initial state
        self.character_face_direction = RIGHT_FACING
        self.set_state(self.config['default_state'])

        logger.debug(f'spawned element; name="{name}"; valid_states={list(self.textures.keys())}')

    def set_state(self, state):
        if not hasattr(self, 'state') or state != self.state:
            self.x_odometer = 0
            self.state_seq_id = 0
            self.state = state
            self.state_start_time = time.time()
        self.texture = self.textures[state][self.character_face_direction][self.state_seq_id]

    def pymunk_moved(self, physics_engine, dx, dy, d_angle):

        # FIXME:
        # something is borked with dx/dy;
        # this is a super-hackish fix for regenerating dx/dy
        if abs(self.center_x - self.__old_center_x) < abs(dx)-5:
            dx = self.center_x - self.__old_center_x 
        self.__old_center_x = self.center_x

        if self.config['default_state'] == 'idle':
            # Figure out if we need to face left or right
            DEAD_ZONE = 1
            if dx < -DEAD_ZONE and self.character_face_direction == RIGHT_FACING:
                self.character_face_direction = LEFT_FACING
            elif dx > DEAD_ZONE and self.character_face_direction == LEFT_FACING:
                self.character_face_direction = RIGHT_FACING
            self.x_odometer += dx

            if abs(dx) >= DEAD_ZONE and self.state != 'interact':
                self.set_state('walk')
            else:
                if time.time() - self.state_start_time >= self.config['min_state_time']:
                    self.set_state('idle')

            # FIXME
            #is_on_ground = physics_engine.is_on_ground(self)
            #if not is_on_ground:
                #if dy > DEAD_ZONE:
                    #self.set_state('jump')
                #elif dy < -DEAD_ZONE:
                    #self.set_state('fall')

            if abs(self.x_odometer) > DISTANCE_TO_CHANGE_TEXTURE:

                # Reset the odometer
                self.x_odometer = 0

                # Advance the walking animation
                #logger.debug(f'pymunk_moved name={self.name} dx={dx} state={self.state}')
                self.state_seq_id += 1
                if self.state_seq_id >= len(self.textures[self.state][self.character_face_direction]):
                    self.state_seq_id = 0


class GameWindow(arcade.Window):

    def __init__(self, output_file):

        self.output_file = output_file

        # the default width/height of the scene is HD video
        self.screen_width = 1280
        self.screen_height = 720

        # FIXME:
        # we add +2 to the target width/height here for non-headless mode because
        # my window manager adds +1 pixel of padding around each window;
        # this ensures that the target width/height is achieved for the opengl buffer;
        # this should be made more generic to work with any window manager setting
        window_width = self.screen_width
        window_height = self.screen_height
        if not os.environ.get("ARCADE_HEADLESS"):
            window_width += 2
            window_height += 2
        super().__init__(window_width, window_height, 'test')

        story_path = 'vignettes/animals'

        self.storyboard_dir = os.path.join(story_path, 'storyboard')
        os.makedirs(self.storyboard_dir, exist_ok=True)

        script_path = os.path.join(story_path, 'script.json')
        self.load_script(script_path)

    def load_script(self, script_path):

        # load the JSON file
        with open(script_path) as fin:
            script = json.load(fin)
        self.scene = SceneManager(
                script['scene'],
                screen_width = self.screen_width,
                screen_height = self.screen_height,
                output_file = self.output_file,
                )

        # create the initial elements
        for i, element in enumerate(script.get('elements', [])):
            self.scene.add(
                element['name'],
                position=element['position'],
                background=element.get('background', False),
                )

        # load events
        self.events = script['events']
        self.events_config = {
            'autostep': True,
            'min_time': 0.5,
            }
        self.event_index = 0
        self.subevents = []
        self.set_event(self.events[self.event_index])

    def record_frame(self):
        image_path = os.path.join(self.storyboard_dir, f'event{self.event_index:04}.png')
        logger.debug(f'saving frame {image_path}')
        image = arcade.get_image(0, 0, *self.get_size())
        image.save(image_path)

    def set_event(self, event):
        logger.info(f'event={event}')
        assert self.subevents == []
        self.record_frame()

        # remove old event sprites if applicable
        try:
            for event_sprite_name in self.event_info['event_sprite_names']:
                self.scene.remove(event_sprite_name)
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
            self.scene.add(bubble_name, bubble, 'above: ' + event['element'])
            self.event_info['event_sprite_names'].append(bubble_name)
            self.scene.add_voice(event['element'], event['text'])

        elif event['type'] == 'sound_effect':
            bubble = KapowBubble(event['text'])
            bubble_name = '__EVENT_BUBBLE__'
            self.scene.add(bubble_name, bubble, event['position'])
            self.event_info['event_sprite_names'].append(bubble_name)

        elif event['type'] == 'spawn_element':
            self.scene.add(event['element'], position=event['position'], depth=-1.0)

        elif event['type'] == 'movement':
            self.subevents.append(event)
            #self.scene.add_movement(event['element'], event['position'])

        elif event['type'] == 'interact':
            self.subevents.append({
                'type': 'movement',
                'element': event['subject'],
                'position': 'inside-front: '+event['object'],
                })
            self.subevents.append(event)
            #self.scene.interact(event['subject'], event['object'])

        else:
            logger.error(f'event type "{event["type"]}" not supported')

    def do_subevent(self, subevent):
        logger.debug(f'subevent={subevent}')
        if subevent['type'] == 'movement':
            self.scene.add_movement(subevent['element'], subevent['position'])
        elif subevent['type'] == 'interact':
            self.scene.interact(subevent['subject'], subevent['object'])
        else:
            logger.error(f'subevent type "{subevent["type"]}" not supported')

    def on_update(self, delta_time):

        # update subevents
        subevent_done = len(self.scene._movements) == 0
        if subevent_done:
            if len(self.subevents) > 0:
                self.do_subevent(self.subevents[0])
                self.subevents.pop(0)
                self.event_info['start_time'] = time.time()

        # update events
        event_runtime = time.time() - self.event_info['start_time']

        if subevent_done and len(self.subevents) == 0 and event_runtime >= self.events_config['min_time'] and not self.scene.has_audio():
            self.event_index += 1
            if self.event_index < len(self.events):
                event = self.events[self.event_index]
                self.set_event(event)
            else:
                logger.debug('done!')
                self.scene.video_recorder.__exit__(None, None, None)
                sys.exit(0)

        # update scene
        self.scene.update_positions()

        # update event_info
        self.event_info['num_frames'] += 1

    def on_draw(self):
        self.clear()
        self.scene.draw()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output_file')
    args = parser.parse_args()

    window = GameWindow(output_file=args.output_file)
    arcade.run()
