"""Placeholder 'reacted' images for testing the reaction test component.
NOT real product photography: each is stamped PLACEHOLDER."""
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRC, OUT = sys.argv[1], sys.argv[2]
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'

def stamp(im, text):
    d = ImageDraw.Draw(im)
    w, h = im.size
    f = ImageFont.truetype(FONT, max(14, w // 48))
    tw = d.textlength(text, font=f)
    d.text(((w - tw) / 2, h - h // 22), text, font=f, fill=(150, 150, 150, 255))

def cuff_tile(size):
    t = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(t)
    r = size * 0.16
    lw = max(2, size // 26)
    cy = size * 0.5
    for cx in (size * 0.30, size * 0.70):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=255, width=lw)
    d.line([size * 0.30 + r * 0.6, cy - r * 1.05, size * 0.70 - r * 0.6, cy - r * 1.05], fill=255, width=lw)
    return t

# HydroCuff: a cuff pattern comes through on the black shell where it is wet.
h = Image.open(f'{SRC}/hydro-1400.png').convert('RGBA')
a = np.asarray(h).astype(np.float32)
luma = a[..., :3] @ np.array([0.299, 0.587, 0.114])
fabric = (luma < 70) & (a[..., 3] > 200)
w, ht = h.size
tile = cuff_tile(w // 9)
pat = Image.new('L', h.size, 0)
ts = tile.size[0]
for row, y in enumerate(range(0, ht, int(ts * 0.8))):
    off = (ts // 2) if row % 2 else 0
    for x in range(-off, w, ts):
        pat.paste(tile, (x, y), tile)
p = np.asarray(pat).astype(np.float32) / 255.0
out = a.copy()
wet = fabric.astype(np.float32)
out[..., :3] *= (1 - 0.18 * wet)[..., None]            # wet shell reads a touch darker
col = np.array([168, 168, 176], dtype=np.float32)
k = (p * wet * 0.85)[..., None]
out[..., :3] = out[..., :3] * (1 - k) + col * k
hi = Image.fromarray(out.clip(0, 255).astype(np.uint8), 'RGBA')
stamp(hi, 'PLACEHOLDER - SIMULATED REACTION - NOT A PHOTO')
hi.save(f'{OUT}/crooks-reaction-placeholder-hydrocuff-water.png', optimize=True)

# Double-Agent Puffa: the black shell shifts colour where it is warm.
p_im = Image.open(f'{SRC}/puffa-full.png').convert('RGBA')
a = np.asarray(p_im).astype(np.float32)
luma = a[..., :3] @ np.array([0.299, 0.587, 0.114])
shell = (luma < 150) & (a[..., 3] > 20)
t = (luma / 150.0).clip(0, 1)[..., None]
lo = np.array([46, 18, 66], dtype=np.float32)
hi_c = np.array([196, 150, 228], dtype=np.float32)
tint = lo * (1 - t) + hi_c * t
out = a.copy()
m = shell[..., None].astype(np.float32)
out[..., :3] = out[..., :3] * (1 - m) + tint * m
pi = Image.fromarray(out.clip(0, 255).astype(np.uint8), 'RGBA')
stamp(pi, 'PLACEHOLDER - SIMULATED REACTION - NOT A PHOTO')
pi.save(f'{OUT}/crooks-reaction-placeholder-puffa-heat.png', optimize=True)
print('ok')
