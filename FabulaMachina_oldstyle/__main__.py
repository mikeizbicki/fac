#!/usr/bin/env python3

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
from .Camera import *
from .Element import *
from .Media import *
from .utils import *


BACKGROUND_DEPTH = -50

class SceneManager():

    def __init__(self, working_folder, screen_width, screen_height, debug=False, **kwargs):
        super().__init__(**kwargs)
        self.pyglet_sound_player = None
        self.working_folder = working_folder
        self.debug = debug

        # setup camera
        if debug:
            self.camera = StaticCamera(self)
        else:
            self.camera = DynamicCamera(self)

        # setup storyboard recorder
        self.storyboard_dir = os.path.join(working_folder, 'storyboard')
        os.makedirs(self.storyboard_dir, exist_ok=True)

        # setup video recorder
        self.screen_width = screen_width
        self.screen_height = screen_height
        output_file = os.path.join(working_folder, 'movie.mp4')
        self.video_recorder = VideoRecorder(
                self.screen_width,
                self.screen_height,
                fps=30,
                output_file=output_file,
                )
        self.video_recorder.__enter__()

        # load voices
        self.voices = {}
        voices_path = f'{working_folder}/voices/'
        for element in os.listdir(voices_path):
            self.voices[element] = {}
            element_path = os.path.join(voices_path, element)
            for text in os.listdir(element_path):
                if text.endswith('.wav'):
                    text_path = os.path.join(element_path, text)
                    text = text[:-4]
                    self.voices[element][text] = arcade.load_sound(text_path)
                    self.voices[element][text].path = text_path

    ####################
    # MARK: engine
    ####################

    def draw(self):

        # NOTE:
        # sprites will be drawn in the order they are in the sprite list;
        # sorting based on depth ensures that items will be drawn in the correct order;
        # sorting can be slow if there's a very large number of sprites;
        # so this could could be made more efficient to only sort when needed
        self.sprites.sort(key=lambda sprite: sprite.depth)

        # draw the sprites;
        # this includes all of the background imagery;
        # it is sorted in order of depth so that the sprites are drawn correctly
        self.sprites.draw()

        # for debugging purposes, we can draw some more info;
        # it would be better to have the floor/wall sprites included in the sprite list
        # so that they can be rendered in the correct depth
        if self.debug:
            #self.floor.draw()
            #self.wall.draw()
            for sprite in self.sprites:
                sprite.draw_hit_box()

        # update camera after drawing sprites because
        # sometimes the camera might want to draw on top of existing sprites
        self.camera.update()

        # save the frame into the video
        self._save_video_frame()

    def record_storyboard_frame(self):
        if not hasattr(self, 'storyboard_index'):
            self.storyboard_index = 0
        else:
            self.storyboard_index += 1
        image_path = os.path.join(self.storyboard_dir, f'event{self.storyboard_index:04}.png')
        logger.trace(f'saving frame {image_path}')
        image = arcade.get_image(0, 0, self.screen_width, self.screen_height)
        image.save(image_path)

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

    def update_positions(self):

        # first handle static positions
        for name, pos in list(self._name_positions.items()):
            sprite = self._name_to_sprite[name]
            x, y = self.position_to_coordinates(sprite, pos)
            sprite.center_x = x
            sprite.center_y = y + sprite.config.get('y-offset', 0)

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

    ####################
    # MARK: internal utils
    ####################

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

    def _reset_element_physics(self, sprite):
        try:
            self.physics_engine.remove_sprite(sprite)
        except KeyError:
            pass
        body_type = arcade.PymunkPhysicsEngine.DYNAMIC
        if sprite.config.get('body_type') == 'static':
            body_type = arcade.PymunkPhysicsEngine.STATIC
        self.physics_engine.add_sprite(
            sprite,
            friction=1.0,
            collision_type="element",
            moment_of_inertia=arcade.PymunkPhysicsEngine.MOMENT_INF,
            max_horizontal_velocity=200,
            max_vertical_velocity=1000,
            body_type=body_type,
        )

    def remove(self, name):
        self.sprites.remove(self._name_to_sprite[name])
        del self._name_to_sprite[name]
        if name in self._name_positions:
            del self._name_positions[name]

    def position_to_coordinates(self, sprite, position):
        if position in self.placements:
            x = self.placements[position]['x']
            y = sprite.height / 2 + self.placements[position]['y']

            # if absolute position is off-stage, move it to be on-stage
            if x < sprite.width/2:
                x = sprite.width/2
            if x > self.screen_width - sprite.width/2:
                x = self.screen_width - sprite.width/2

        elif ':' in position:
            loc, target_name = position.split(':')
            loc = loc.strip()
            target_name = target_name.strip()

            if target_name not in self._name_to_sprite:
                logger.trace(f'target_name="{target_name}" not in self._name_to_sprite')
                return (0, 0)

            target = self._name_to_sprite[target_name]

            offset_x = 0
            offset_y = -target.center_y + self.floor_height + self.floor_offset + sprite.center_y - sprite.bottom
            if sprite.config.get('background'):
                offset_y = -target.center_y + sprite.height / 2 + self.placements['stage-center']['y']
            if 'inside' in loc:
                padding = -10
            else:
                padding = 40

            if 'above' in loc:
                offset_y = (target.top - target.center_y) - (sprite.bottom - sprite.center_y) + padding
            if 'below' in loc:
                offset_y = (target.bottom - target.center_y) - (sprite.top - sprite.center_y) + padding
            if 'on' in loc or 'infront' in loc:
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

    #################### 
    # MARK: commands
    #################### 

    def reset_scene(self, scene):
        self.camera.reset()

        # empty out all containers
        self.sprites = arcade.SpriteList()
        self._name_to_sprite = {}
        self._name_positions = {}
        self._movements = {}
        self._foreground_elements = set()

        # FIXME:
        # should this be elsewhere?
        scene.setdefault('walls', False)
        scene.setdefault('floor_height', 0.2)
        floor_height = int(self.screen_height * scene['floor_height'])
        self.floor_height = floor_height

        # load scene config
        if scene['type'] == 'static':
            background_path = scene.get('filename')
            if not os.path.isfile(background_path):
                background_path = os.path.join(self.working_folder, os.path.join('static', background_path + '.png'))
            self.background = arcade.load_texture(background_path)

            self.background_sprite = arcade.Sprite()
            self.background_sprite.texture = self.background
            self.background_sprite.scale_x = self.screen_width / self.background.width
            self.background_sprite.scale_y = self.screen_height / self.background.height
            self.background_sprite.left = 0
            self.background_sprite.bottom = 0
            self.sprites.append(self.background_sprite)

            self.camera.set_goal(scene['camera_movement'])

        elif scene['type'] in ['simple-interior', 'simple-exterior', 'plain-background']:

            # load the background image
            background_path = scene.get('wall', scene.get('background', scene.get('background_image_path')))
            if not os.path.isfile(background_path):
                background_path = os.path.join('scene/background', background_path)
            self.background = arcade.load_texture(background_path)
            lr_padding = 0.2 * self.screen_width
            background_newheight = self.screen_width / (self.background.width / self.background.height) + 2 * lr_padding * self.screen_height / self.screen_width
            self.background_LBWH = arcade.LBWH(
                    -lr_padding,
                    floor_height,
                    floor_height + self.screen_width + lr_padding * 2,
                    background_newheight,
                    )

            self.background_sprite = arcade.Sprite()
            self.background_sprite.name = 'self.background_sprite'
            self.background_sprite.texture = self.background
            self.background_sprite.scale_x = self.background_LBWH.width / self.background.width
            self.background_sprite.scale_y = self.background_LBWH.height / self.background.height
            self.background_sprite.left = self.background_LBWH.left
            self.background_sprite.bottom = self.background_LBWH.bottom
            self.background_sprite.depth = BACKGROUND_DEPTH - 0.5
            self.sprites.append(self.background_sprite)

            farbackground_path = scene.get('outside', scene.get('farbackground_image_path'))
            if farbackground_path:
                if not os.path.isfile(farbackground_path):
                    farbackground_path = os.path.join('scene/background', farbackground_path)
                if not os.path.isfile(farbackground_path):
                    farbackground_path = 'img/error.png'
                farbackground = arcade.Sprite(farbackground_path)
                farbackground.name = 'self.farbackground'
                farbackground.depth = BACKGROUND_DEPTH - 9
                farbackground.scale_x = self.background_sprite.scale_x
                farbackground.scale_y = self.background_sprite.scale_y
                farbackground.left = self.background_sprite.left
                farbackground.bottom = self.background_sprite.bottom + 4
                self.sprites.append(farbackground)

            floor_path = scene.get('floor', scene.get('floor_image_path'))
            if floor_path:
                if not os.path.isfile(floor_path):
                    floor_path = os.path.join('scene/floor', floor_path)
                img_floor = arcade.Sprite(floor_path)
                img_floor.name = 'self.img_floor'
                img_floor.depth = BACKGROUND_DEPTH - 10
                img_floor.scale_x = self.background_sprite.scale_x
                img_floor.scale_y = self.background_sprite.scale_y
                img_floor.left = self.background_sprite.left
                img_floor.bottom = self.background_sprite.bottom - self.background_LBWH.height // 2
                self.sprites.append(img_floor)

        else:
            raise ValueError(f'scene["type"]="{scene["type"]}" invalid')

        # setup the physics engine
        self.physics_engine = arcade.PymunkPhysicsEngine(damping=1.0, gravity=(0, -1500))

        # create a floor for the scene
        self.floor = arcade.SpriteList()
        self.floor_offset = -32
        floor_path = 'tmp/Ground&Stone/Ground/ground2.png'
        floor_img = arcade.load_image(floor_path)
        floor_width = int(floor_img.width * (floor_height / floor_img.height))
        floor_img = floor_img.resize((floor_width, floor_height))
        floor_texture = arcade.Texture(floor_img, hit_box_algorithm=arcade.hitbox.BoundingHitBoxAlgorithm())
        for i in range(-20, 30):
            for depth in range(-2, 3):
                sprite = arcade.Sprite(floor_texture)
                sprite.center_x = floor_width * i
                sprite.center_y = floor_height / 2 + self.floor_offset - depth * 32
                sprite.depth = depth
                self.floor.append(sprite)

                if self.debug:
                    self.sprites.append(sprite)
        self.physics_engine.add_sprite_list(
            self.floor,
            friction=0.7,
            collision_type="floor",
            body_type=arcade.PymunkPhysicsEngine.STATIC,
        )

        # elements should only collide with floors of the same depth
        def floor_handler(element, floor, arbiter, space, data):
            collide = floor.depth >= element.depth
            #logger.debug(f'element.name={element.name}, element.depth={element.depth}, floor.depth={floor.depth}, collide={collide}')
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

    def add_voice(self, name, text, target=None):
        # playing a sound effect
        if name == 'audio':
            path = 'audio/knock1.wav'
            sound = arcade.load_sound(path)
            self.pyglet_sound_player = arcade.play_sound(sound)
            self.video_recorder.add_audio(path)

        # someone is talking
        else:
            self.camera.recent_sprites.append(name)
            self.pyglet_sound_player = arcade.play_sound(self.voices[name][text])
            self.video_recorder.add_audio(self.voices[name][text].path)

            if name not in self._name_to_sprite:
                logger.debug(f'"{name}" is talking but not in the scene')

            elif name in self._name_to_sprite:

                # make the speaker look at the target if provided
                speaker = self._name_to_sprite[name]
                if target:
                    sprite = self._name_to_sprite[target]
                    if sprite.center_x < speaker.center_x:
                        speaker.character_face_direction = LEFT_FACING
                    elif sprite.center_x > speaker.center_x:
                        speaker.character_face_direction = RIGHT_FACING

                # make all the other sprites look at the speaker
                # FIXME:
                # this should be pushed into the Element.pymunk_moved method
                # to get the sprite to look in the right direction after it has moved
                for sprite in self.sprites:
                    if hasattr(sprite, 'config') and sprite.config.get('alive'):
                        if sprite.center_x < speaker.center_x:
                            sprite.character_face_direction = RIGHT_FACING
                        elif sprite.center_x > speaker.center_x:
                            sprite.character_face_direction = LEFT_FACING
    def add_movement(self, name, position):
        sprite = self._name_to_sprite[name]
        sprite.depth = 1.0
        self._reset_element_physics(sprite)
        self._movements[name] = position
        if name in self._name_positions:
            del self._name_positions[name]
        self.camera.recent_sprites.append(name)

    def interact(self, sub_name, obj_name):
        sub = self._name_to_sprite[sub_name]
        sub.set_state('interact')
        obj = self._name_to_sprite[obj_name]
        if obj.state == 'closed':
            obj.set_state('open')
        else:
            obj.set_state('closed')
        self.camera.recent_sprites.append(sub_name)
        self.camera.recent_sprites.append(obj_name)

    def add_element(self, name, sprite=None, position=None, background=False, depth=0.0):
        assert name not in self._name_to_sprite
        if sprite is None:
            sprite = Element(name)
        #sprite.depth = depth
        self.sprites.append(sprite)
        self._name_to_sprite[name] = sprite
        self._name_positions[name] = position

        if position:
            x, y = self.position_to_coordinates(sprite, position)
            sprite.center_x = x
            sprite.center_y = y + sprite.config.get('y-offset', 0) - depth*32

        if isinstance(sprite, Element) and not sprite.config.get('background', False):
            self._reset_element_physics(sprite)

        # for background objects, we need to cut a hole in the background texture
        if sprite.config.get('background'):
            from PIL import Image
            from PIL import ImageDraw
            new_bg = self.background_sprite.texture.image.copy().convert('RGBA')
            draw = ImageDraw.Draw(new_bg)

            sprite.depth = BACKGROUND_DEPTH - 7

            # first, convert screen coords to self.background texture coords
            def screen_to_texture_coords(screen_x, screen_y):
                scaled_width = self.background_LBWH.width
                scaled_height = self.background_LBWH.height
                bg_left = self.background_LBWH.left
                bg_bottom = self.background_LBWH.bottom
                texture_x = (screen_x - bg_left) / scaled_width * self.background.width
                texture_y = (1 - (screen_y - bg_bottom) / scaled_height) * self.background.height
                return texture_x, texture_y
            x0, y1 = screen_to_texture_coords(sprite.left, sprite.bottom)
            x1, y0 = screen_to_texture_coords(sprite.right, sprite.top)

            padding = 15
            x0 += padding
            x1 -= padding
            y0 += padding
            y1 -= padding
            draw.rectangle((x0, y0, x1, y1), fill=(0, 0, 0, 0))
            self.background_sprite.texture = arcade.Texture(new_bg)


class GameWindow(arcade.Window):

    def __init__(self, working_folder):

        self.working_folder = working_folder

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

        # the scene manager will handle all of the rendering
        self.scene = SceneManager(
                self.working_folder,
                screen_width = self.screen_width,
                screen_height = self.screen_height,
                )

        # load the script
        script_path = os.path.join(working_folder, 'script.json')
        self.load_script(script_path)

    def load_script(self, script_path):

        # load the JSON file
        with open(script_path) as fin:
            script = json.load(fin)

        # load events
        self.events = script['events']
        self.events_config = {
            'autostep': True,
            'min_time': 0,
            }
        self.event_index = 0
        self.subevents = []
        self.set_event(self.events[self.event_index])

    def set_event(self, event):
        # FIXME:
        # at least some of this logic should be pushed into SceneManager
        logger.info(f'event={event}')
        assert self.subevents == []
        self.scene.record_storyboard_frame()

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

        if event['type'] == 'reset_scene':
            self.scene.reset_scene(event['scene_config'])
            for i, element in enumerate(event.get('element_positions', [])):
                logger.debug(f'placing element="{element}"')
                self.scene.add_element(
                    element['name'],
                    position=element['position'],
                    background=element.get('background', False),
                    )

        elif event['type'] == 'dialogue':
            #if event.get('target') in self.scene._name_to_sprite:
            bubble = SpeechBubble(event['text'])
            bubble_name = '__EVENT_BUBBLE__'
            self.scene.add_element(bubble_name, bubble, 'above: ' + event['element'])
            self.event_info['event_sprite_names'].append(bubble_name)
            self.scene.add_voice(event['element'], event['text'], event.get('target'))

        elif event['type'] == 'sound_effect':
            bubble = KapowBubble(event['text'])
            bubble_name = '__EVENT_BUBBLE__'
            self.scene.add_element(bubble_name, bubble, event['position'])
            self.event_info['event_sprite_names'].append(bubble_name)
            self.scene.add_voice('audio', event['text'])

        elif event['type'] == 'spawn_element':
            self.scene.add_element(event['element'], position=event['position'], depth=-2.0)

        elif event['type'] == 'movement':
            self.subevents.append(event)

        elif event['type'] == 'interact':
            self.subevents.append({
                'type': 'movement',
                'element': event['subject'],
                'position': 'inside-front: '+event['object'],
                })
            self.subevents.append(event)

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
    parser.add_argument('--working_folder')
    args = parser.parse_args()

    window = GameWindow(working_folder=args.working_folder)
    arcade.run()
