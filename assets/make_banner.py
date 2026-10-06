"""Renders assets/banner.png (1280x640): README header and GitHub social preview.
Editorial style: warm grain background, tilted cards with soft shadows, Georgia / Segoe / Consolas.
Needs Windows fonts (C:/Windows/Fonts) and Pillow. Run: python assets/make_banner.py"""
import math
import pathlib
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 2                      # render at 2x, downsample at the end: sizes below are final pixels
W, H = 1280 * S, 640 * S
FONTS = "C:/Windows/Fonts/"
MIN_PX = 26                # nothing a reader must parse is smaller than this in the final image


def font(name, px):
    assert px >= MIN_PX or name.startswith("consola") and px >= 22, f"{name} {px}px is below the floor"
    return ImageFont.truetype(FONTS + name, int(px * S))


def P(v):
    return int(v * S)


BG, INK, MUTED = (244, 240, 231), (27, 27, 26), (120, 115, 106)
RED, MARK, GREEN, SALMON = (200, 64, 43), (255, 214, 102), (46, 122, 76), (255, 122, 99)

bg = Image.new("RGB", (W, H), BG)
grad = Image.linear_gradient("L").resize((W, H))
bg = Image.composite(Image.new("RGB", (W, H), (236, 230, 217)), bg, grad.point(lambda v: v // 3))
random.seed(7)
noise = Image.effect_noise((W // 2, H // 2), 18).resize((W, H)).convert("L")
bg = Image.blend(bg, Image.merge("RGB", (noise, noise, noise)), 0.035)
img = bg.convert("RGBA")


def highlight(base, box):
    m = Image.new("RGBA", base.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(m).polygon([(x0 - P(8), y0 + P(20)), (x1 + P(12), y0 + P(13)),
                               (x1 + P(8), y1 + P(7)), (x0 - P(12), y1 + P(12))], fill=MARK + (235,))
    return Image.alpha_composite(base, m)


# ---- hook
M = P(64)
hook = font("georgiab.ttf", 54)
d = ImageDraw.Draw(img)
l1, l2a, l2b = "Your Postgres image works here.", "On older CPUs it ", "crashes."
y1, y2 = P(44), P(110)
xb = M + d.textlength(l2a, font=hook)
img = highlight(img, d.textbbox((xb, y2), l2b, font=hook))
d = ImageDraw.Draw(img)
for x, y, t in [(M, y1, l1), (M, y2, l2a), (xb, y2, l2b)]:
    d.text((x, y), t, font=hook, fill=INK)


# ---- cards
def card(w, h, fill, label, label_fill, lines, dots=False):
    c = Image.new("RGBA", (P(w), P(h)), (0, 0, 0, 0))
    cd = ImageDraw.Draw(c)
    cd.rounded_rectangle([0, 0, P(w) - 1, P(h) - 1], radius=P(22), fill=fill)
    if dots:
        for i, col in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
            cx = P(30 + i * 22)
            cd.ellipse([cx - P(6), P(28), cx + P(6), P(40)], fill=col)
        cd.text((P(w - 26), P(34)), label, font=font("consola.ttf", 22), fill=label_fill, anchor="rm")
    else:
        cd.text((P(26), P(34)), label, font=font("seguisb.ttf", 26), fill=label_fill, anchor="lm")
    for text, f, col, dy in lines:
        cd.text((P(w / 2), P(h / 2 + dy)), text, font=f, fill=col, anchor="mm")
    return c


def place(base, c, cx, cy, angle):
    r = c.rotate(angle, resample=Image.BICUBIC, expand=True)
    pad = P(60)
    sh = Image.new("RGBA", (r.width + 2 * pad, r.height + 2 * pad), (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", r.size, (60, 45, 30, 255)), (pad, pad), r.split()[3].point(lambda a: a * 0.30))
    sh = sh.filter(ImageFilter.GaussianBlur(P(18)))
    base.alpha_composite(sh, (P(cx) - sh.width // 2, P(cy) - sh.height // 2 + P(14)))
    base.alpha_composite(r, (P(cx) - r.width // 2, P(cy) - r.height // 2))


def arrow(base, pts, label=None, label_at=None):
    (x0, y0), (cx, cy), (x1, y1) = [(P(a), P(b)) for a, b in pts]
    path = [((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1,
             (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1) for t in [i / 60 for i in range(61)]]
    dd = ImageDraw.Draw(base)
    dd.line(path[:-4], fill=INK, width=P(4), joint="curve")
    ang = math.atan2(path[-1][1] - path[-5][1], path[-1][0] - path[-5][0])
    L, Wd, tip = P(20), P(11), path[-1]
    back = (tip[0] - L * math.cos(ang), tip[1] - L * math.sin(ang))
    dd.polygon([tip, (back[0] + Wd * math.sin(ang), back[1] - Wd * math.cos(ang)),
                (back[0] - Wd * math.sin(ang), back[1] + Wd * math.cos(ang))], fill=INK)
    if label:
        dd.text((P(label_at[0]), P(label_at[1])), label, font=font("segoeuii.ttf", 26), fill=MUTED, anchor="mm")


crash = card(370, 190, (30, 30, 28), "postgres.log", (150, 146, 136),
             [("terminated by signal 4:", font("consola.ttf", 24), (170, 165, 155), -6),
              ("Illegal instruction", font("consolab.ttf", 31), SALMON, 38)], dots=True)
probe = card(340, 190, (255, 253, 248), "the check", MUTED,
             [("7 CPU models", font("georgiab.ttf", 40), INK, -2),
              ("x86 and ARM, old to new", font("segoeui.ttf", 26), MUTED, 46)])
found = card(310, 190, (255, 236, 179), "crashes on", (138, 110, 40),
             [("vpermt2d", font("consolab.ttf", 46), INK, -2),
              ("in array_to_vector", font("segoeui.ttf", 26), (110, 90, 40), 46)])

place(img, crash, 238, 350, -3)
place(img, probe, 645, 365, 2)
place(img, found, 1058, 350, -2)
arrow(img, [(418, 318), (446, 282), (472, 318)], "replays it", (446, 254))
arrow(img, [(820, 392), (858, 446), (898, 392)], "names it", (858, 474))

# ---- fix line + address
d = ImageDraw.Draw(img)
fy = P(546)
d.ellipse([M, fy - P(20), M + P(40), fy + P(20)], fill=GREEN)
d.line([(M + P(11), fy + P(1)), (M + P(18), fy + P(9)), (M + P(30), fy - P(8))], fill=(255, 255, 255), width=P(5), joint="curve")
d.text((M + P(56), fy), "then the build fix, e.g. make OPTFLAGS=\"\"", font=font("seguisb.ttf", 30), fill=INK, anchor="lm")
d.text((W - M, P(604)), "github.com/intikhab49/pgvector-cpu-check", font=font("segoeui.ttf", 26), fill=MUTED, anchor="rm")

out = pathlib.Path(__file__).with_name("banner.png")
img.convert("RGB").resize((1280, 640), Image.LANCZOS).save(out, optimize=True)
print(out)
