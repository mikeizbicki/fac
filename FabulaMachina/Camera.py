import arcade
from .Element import *
from .utils import *


class Camera():
    def __init__(self, scene_manager):
        self.camera = arcade.Camera2D()
        self.scene_manager = scene_manager
        self.aspect_ratio = 16/9
        self.debug = True
        self.reset()

    def reset(self):
        self._camera_must_draw_sprites = set()
        self.recent_sprites = []
        self.prev_lrbt = None
        self.prev_target_lrbt = None
        self.goal = None

    def set_goal(self, goal):
        self.goal = goal
        if goal.get('start_position'):
            if goal['type'] == 'zoom-out':
                zoom = 3
            elif goal['type'] == 'zoom-in':
                zoom = 1
            elif goal['type'] == 'pan':
                zoom = 2
            else:
                raise ValueError
            self.prev_lrbt = self.position_to_lrbt(goal['start_position'], zoom)

    def position_to_lrbt(self, position, zoom):
        max_height = self.scene_manager.screen_height
        max_width = self.scene_manager.screen_width

        padding = 64

        width = max_width / zoom
        height = max_height / zoom

        center_x = max_width / 2
        center_y = max_height / 2
        if 'left' in position:
            center_x = width / 2 + padding * (zoom - 1)
        if 'right' in position:
            center_x = max_width - width / 2 - padding * (zoom - 1)
        if 'bottom' in position:
            center_y = height / 2 + padding * (zoom - 1)
        if 'top' in position:
            center_y = max_height - height / 2 - padding * (zoom - 1)

        lrbt = arcade.LRBT(
            center_x - width / 2,
            center_x + width / 2,
            center_y - height / 2,
            center_y + height / 2,
            )
        return self.fit_lrbt_to_screen(lrbt)

    def fit_lrbt_to_screen(self, lrbt):
        max_height = self.scene_manager.screen_height
        max_width = self.scene_manager.screen_width

        if lrbt.bottom < 0:
            lrbt = arcade.LRBT(lrbt.left, lrbt.right, 0, lrbt.top - lrbt.bottom)
        elif lrbt.top > max_height:
            lrbt = arcade.LRBT(lrbt.left, lrbt.right, lrbt.bottom - (lrbt.top - max_height), max_height)
        if lrbt.left < 0:
            lrbt = arcade.LRBT(0, lrbt.right - lrbt.left, lrbt.bottom, lrbt.top)
        elif lrbt.right > max_width:
            lrbt = arcade.LRBT(lrbt.left - (lrbt.right - max_width), max_width, lrbt.bottom, lrbt.top)

        return lrbt

    def correct_aspect_ratio(self, lrbt):
        '''
        adjust lrbt for the correct aspect ratio;
        this is necessary because the lrbt is a *minimum* portion of the scene that must be displayed;
        it is likely to be either too tall or too wide depending on the positioning of the elements it is trying to capture;
        the code below expands the lrbt to include more background so that the aspect ratio will be maintained
        '''
        width = lrbt.right - lrbt.left
        height = lrbt.top - lrbt.bottom
        aspect = width / height
        if aspect > self.aspect_ratio:
            ydiff = (width / self.aspect_ratio - height) / 2
            lrbt = arcade.LRBT(lrbt.left, lrbt.right, lrbt.bottom-ydiff, lrbt.top+ydiff)
        if aspect < self.aspect_ratio:
            xdiff = (height * self.aspect_ratio - width) / 2
            lrbt = arcade.LRBT(lrbt.left-xdiff, lrbt.right+xdiff, lrbt.bottom, lrbt.top)
        return lrbt


class StaticCamera(Camera):
    '''
    This Camera always shows everything in the scene and never moves.
    It is useful for debugging item placements,
    and to get a "director's view" of what is happening.
    '''

    def update(self):

        # draw a box around the scene
        lrbt = arcade.LRBT(
                0,
                self.scene_manager.screen_width,
                0,
                self.scene_manager.screen_height,
                )
        arcade.draw_rect_outline(lrbt, arcade.color.BRIGHT_MAROON, 10)

        # move camera 
        padding = 200
        lrbt = arcade.LRBT(
                -padding,
                self.scene_manager.screen_width + padding,
                -padding,
                self.scene_manager.screen_height + padding,
                )
        lrbt = self.correct_aspect_ratio(lrbt)

        # set camera as visible
        self.camera.use()
        self.camera.update_values(lrbt, viewport=False, position=True)


class DynamicCamera(Camera):
    '''
    This is the standard Camera for use in "production".
    It tries to move around the scene and follow the action.
    '''

    def __init__(self, scene_manager):
        super().__init__(scene_manager)
        self.camera_move_clamp = 'l1'
        self.max_camera_velocity = 12
        self.prev_lrbt = None
        self.prev_target_lrbt = None

    def update(self):
        sprites_to_include = self._camera_must_draw_sprites | set(self.recent_sprites[-2:])
        max_height = self.scene_manager.screen_height
        max_width = self.scene_manager.screen_width
        cut = False

        # set target_lrbt, which is the bounding box of what we want the scene to capture
        if self.goal is not None:
            camera_velocity = 6
            movement_type = self.goal['type']
            if movement_type == 'zoom-out':
                zoom = 1
            elif movement_type == 'zoom-in':
                zoom = 2
            elif movement_type == 'pan':
                zoom = 2
            else:
                raise ValueError
            target_lrbt = self.position_to_lrbt(self.goal['end_position'], zoom)

        # when no goal specified, base target_lrbt off of the acting sprites
        if self.goal is None:
            camera_velocity = self.max_camera_velocity
            target_lrbt = None
            for sprite in self.scene_manager.sprites:
                if isinstance(sprite, Element):
                    if sprite.name in sprites_to_include:
                        if not target_lrbt:
                            target_lrbt = arcade.LRBT(sprite.left, sprite.right, sprite.bottom, sprite.top)
                        else:
                            target_lrbt = arcade.LRBT(
                                min(target_lrbt.left, sprite.left),
                                max(target_lrbt.right, sprite.right),
                                min(target_lrbt.bottom, sprite.bottom),
                                max(target_lrbt.top, sprite.top),
                                )
            if target_lrbt is None:
                target_lrbt = arcade.LRBT(0, max_width, 0, max_height)
            else:
                padding = 64
                target_lrbt = arcade.LRBT(
                    target_lrbt.left - padding,
                    target_lrbt.right + padding,
                    target_lrbt.bottom - padding,
                    target_lrbt.top + padding,
                    )

            # perform a cut if the distance to pan/zoom is too great
            # FIXME:
            # these thresholds should be optimized
            if self.prev_lrbt is not None:
                if abs(target_lrbt.x - self.prev_lrbt.x) > max_width / 2:
                    cut = True
                if abs(target_lrbt.y - self.prev_lrbt.y) > max_height / 2:
                    cut = True
                if abs(target_lrbt.width - self.prev_lrbt.width) > max_width / 3:
                    cut = True
                if abs(target_lrbt.height - self.prev_lrbt.height) > max_height / 3:
                    cut = True

        # lrbt represents what the camera is currently capturing;
        # if this is the first frame, then immediately cut to the target_lrbt;
        # otherwise, slowly move the camera to the target_lrbt
        lrbt = target_lrbt
        if not cut and self.prev_lrbt is not None:
            if self.camera_move_clamp == 'l0':
                lrbt = arcade.LRBT(
                        self.prev_lrbt.left + clamp(lrbt.left - self.prev_lrbt.left, camera_velocity),
                        self.prev_lrbt.right + clamp(lrbt.right - self.prev_lrbt.right, camera_velocity),
                        self.prev_lrbt.bottom + clamp(lrbt.bottom - self.prev_lrbt.bottom, camera_velocity),
                        self.prev_lrbt.top + clamp(lrbt.top - self.prev_lrbt.top, camera_velocity),
                        )

            elif self.camera_move_clamp == 'l1':
                total_diff = (
                        abs(self.prev_lrbt.left - lrbt.left) +
                        abs(self.prev_lrbt.right - lrbt.right) +
                        abs(self.prev_lrbt.bottom - lrbt.bottom) +
                        abs(self.prev_lrbt.top - lrbt.top)
                        )
                if total_diff >= camera_velocity:
                    move_ratio = camera_velocity / total_diff
                else:
                    move_ratio = 1
                lrbt = arcade.LRBT(
                        self.prev_lrbt.left + move_ratio * (lrbt.left - self.prev_lrbt.left),
                        self.prev_lrbt.right + move_ratio * (lrbt.right - self.prev_lrbt.right),
                        self.prev_lrbt.bottom + move_ratio * (lrbt.bottom - self.prev_lrbt.bottom),
                        self.prev_lrbt.top + move_ratio * (lrbt.top - self.prev_lrbt.top),
                        )
        self.prev_lrbt = lrbt

        # ensure that the camera does not leave the stage
        lrbt = self.correct_aspect_ratio(lrbt)
        lrbt = self.fit_lrbt_to_screen(lrbt)

        if self.debug:
            # draw an outline around the camera viewport
            arcade.draw_rect_outline(lrbt, arcade.color.BRIGHT_MAROON, 10)

            # reset the viewport to the entire screen
            x_padding = 100
            y_padding = x_padding / self.aspect_ratio
            lrbt = arcade.LRBT(
                    -x_padding,
                    self.scene_manager.screen_width + x_padding,
                    -y_padding,
                    self.scene_manager.screen_height + y_padding,
                    )

        # register the new camera position with the render
        self.camera.use()
        self.camera.update_values(lrbt, viewport=False, position=True)


def clamp(a, b):
    '''
    Ensure that -b <= a <= b.
    '''

    if a > b:
        return b
    elif a < -b:
        return -b
    else:
        return a
