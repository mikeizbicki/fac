"""
Example of Pymunk Physics Engine Platformer
"""

import math
import arcade
import json

SCREEN_TITLE = "PyMunk Platformer"

# Constants used to track if the player is facing left or right
RIGHT_FACING = 0
LEFT_FACING = 1


class CharacterSprite(arcade.Sprite):

    def __init__(
            self,
            image_path
            ):
        """Init"""
        # Let parent initialize
        super().__init__(scale=1)

        self.FRICTION = 1.0
        self.MASS = 2.0
        self.MAX_HORIZONTAL_SPEED = 450
        self.MAX_VERTICAL_SPEED = 1600
        self.MOVE_FORCE_ON_GROUND = 8000
        self.MOVE_FORCE_IN_AIR = 900
        self.JUMP_IMPULSE = 1800
        self.MOMENT_OF_INERTIA=arcade.PymunkPhysicsEngine.MOMENT_INF

        # Images from Kenney.nl's Character pack
        #image_path = 'family_story/story2_moses/chapter01/section00/sprites/aaron.png'
        #image_path = 'family_story/story2_moses/chapter01/section00/sprites/aaron.png'
        img = arcade.load_image(image_path)
        new_height = 300
        new_width = int(img.width * (new_height / img.height))
        img = img.resize((new_width, new_height))
        self.texture = arcade.Texture(img)

    def pymunk_moved(self, physics_engine, dx, dy, d_angle):
        """Handle being moved by the pymunk engine"""

        # Close enough to not-moving to have the animation go to idle.
        DEAD_ZONE = 0.1


class GameWindow(arcade.Window):

    def __init__(self):

        # init arcade Window
        width = 1536
        height = 1024
        super().__init__(width, height, 'test')

        self.placements = {
            'stage-left': {'x': 100, 'y': 300},
            'stage-right': {'x': self.width-100, 'y': 300},
            'center': {'x': self.width/2, 'y': 300},
            }


    def setup(self, path_story='family_story/story2_moses', chapter=1, section=3):

        # setup the physics engine
        self.physics_engine = arcade.PymunkPhysicsEngine(damping=1.0, gravity=(0, -1500))

        # this is a hackish way to get a "floor" for the scene 
        map_name = ":resources:/tiled_maps/test_map_1.json"
        tile_map = arcade.load_tilemap(map_name, 1.5)
        self.wall_list = tile_map.sprite_lists["Platforms"]
        self.physics_engine.add_sprite_list(
            self.wall_list,
            friction=0.7,
            collision_type="wall",
            body_type=arcade.PymunkPhysicsEngine.STATIC,
        )

        # load chapter info 
        path_chapter = f'{path_story}/chapter01/'
        with open(f'{path_chapter}/text') as fin:
            json_chapter = json.load(fin)
        json_section = json_chapter.get('sections', [])[section]

        # load the background image
        path_background = f'{path_story}/sublocations/{json_section["sublocation"]}.png'
        self.background = arcade.load_texture(path_background)
        self.background_color = arcade.color.AMAZON

        # load blocking info
        path_section = f'{path_chapter}/section{section:02}/'
        path_blocking = f'{path_section}/blocking.json'
        with open(path_blocking) as fin:
            blocking = json.load(fin)

        # create character sprites
        self.character_list = arcade.SpriteList()
        for i, character in enumerate(blocking.get('characters', [])):
            path_sprite = f'{path_section}/sprites/{character["name"]}.png'.lower()
            sprite = CharacterSprite(path_sprite)
            sprite.center_x = self.placements[character['placement']]['x'] + i
            sprite.center_y = self.placements[character['placement']]['y']
            self.character_list.append(sprite)
            self.physics_engine.add_sprite(
                sprite,
                friction=sprite.FRICTION,
                mass=sprite.MASS,
                moment_of_inertia=sprite.MOMENT_OF_INERTIA,
                collision_type="player",
                max_horizontal_velocity=sprite.MAX_HORIZONTAL_SPEED,
                max_vertical_velocity=sprite.MAX_VERTICAL_SPEED,
            )

    def on_update(self, delta_time):
        self.physics_engine.step()

    def on_draw(self):
        self.clear()

        # draw the background texture
        arcade.draw_texture_rect(
            self.background,
            arcade.LBWH(0, 0, self.width, self.height),
        )

        self.wall_list.draw()
        
        # draw the characters
        self.character_list.draw()


if __name__ == "__main__":
    window = GameWindow()
    window.setup()
    arcade.run()
