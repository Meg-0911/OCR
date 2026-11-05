"""Color masks used to separate handwriting by ink in mixed-language scans."""
import numpy as np


PROFILES = ('red_qn', 'blue_qn_red_han')


def ink_mask(image, color):
    pixels = np.asarray(image.convert('RGB'), dtype=np.int16)
    red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    if color == 'red':
        return (red - green > 22) & (red - blue > 3) & (green < 205) & (red < 235) & (
            (blue - green > -5) | (red - green > 55)
        )
    if color == 'blue':
        return (blue - red > 18) & (blue - green > 8) & (red < 205) & (green < 220) & (blue < 245)
    raise ValueError(f'Unsupported ink color: {color}')


def profile_colors(profile):
    if profile == 'blue_qn_red_han':
        return 'blue', 'red'
    if profile == 'red_qn':
        return 'red', 'neutral'
    raise ValueError(f'Unsupported ink profile: {profile}')
