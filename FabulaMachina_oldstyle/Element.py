from .utils import *
import arcade
import glob
import json
import math
import os
import re
import time

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

        self.name = name
        root_dir = f'elements/{name}'

        # load JSON info
        json_path = os.path.join(root_dir, 'sprite.json')
        try:
            with open(json_path) as fin:
                self.config = json.load(fin)
        except FileNotFoundError:
            logger.error(f'json_path="{json_path}" not found')
            self.config = {}
        self.config.setdefault('default_state', 'idle')
        self.config.setdefault('default_depth', 0)
        self.config.setdefault('min_state_time', 1.5)
        self.config.setdefault('height', 1.0)
        self.config.setdefault('movement_type', 'dynamic')
        #logger.debug(f'created element "{name}"; config={self.config}')

        self.depth = self.config['default_depth']

        # load state textures
        self.textures = {}
        for image_path in ['img/error.png'] + sorted(glob.glob(root_dir + '/sprites/*.png')):
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
        # the first time we set the state, init state-tracking variables
        if not hasattr(self, 'state') or state != self.state:
            self.x_odometer = 0
            self.state_seq_id = 0
            self.state = state
            self.state_start_time = time.time()

        # now we actually set the state,
        # but emit appropriate errors if the state cannot be found
        if state not in self.textures:
            logger.error(f'Element(name="{self.name}").set_state(): "{state}" not in self.textures')
            state = 'error'
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
                if 'walk' in self.textures:
                    self.set_state('walk')
                else:
                    self.set_state(self.config['default_state'])
                    logger.warning("pymunk has caused the object to move; but the walk state is not available; using default_state={self.config['default_state']}")
                period = 64
                max_angle = 20
                self.angle = math.cos(self.center_x / period) * max_angle
            else:
                self.angle = 0
                if time.time() - self.state_start_time >= self.config['min_state_time']:
                    self.set_state('idle')

            if abs(self.x_odometer) > DISTANCE_TO_CHANGE_TEXTURE:

                # Reset the odometer
                self.x_odometer = 0

                # Advance the walking animation
                #logger.debug(f'pymunk_moved name={self.name} dx={dx} state={self.state}')
                self.state_seq_id += 1
                max_seq_id = len(self.textures.get(self.state, {}).get(self.character_face_direction, {}))
                if self.state_seq_id >= max_seq_id:
                    self.state_seq_id = 0



