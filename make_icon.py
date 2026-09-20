"""图标生成脚本：方案 C「对话双泡」→ app.ico + PNG 预览（可重跑再生）。

设计（2026-09-20 拍板）：
- 深蓝夜空底 (#0F172A) 圆角方 22.5% 半径（Windows 11 风格）
- 白色对话气泡（原文）内嵌 teal→sky 渐变五柱声波（居中高两侧低）
- teal→sky 渐变对话气泡（译文）错位叠放右下，内两条白色字幕行
- 配色与应用主题 token 同源：#14B8A6 → #0EA5E9（theme.py）

渲染：Pillow，8x 超采样后 LANCZOS 缩小（抗锯齿圆角/圆头柱）。
输出：app.ico（256/128/64/48/32/24/16）+ icon_preview_256.png（用于快速目检）+ icon_master_1024.png
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- 设计 token ----------
TEAL = (20, 184, 166)      # #14B8A6
SKY = (14, 165, 233)       # #0EA5E9
NIGHT = (15, 23, 42)       # #0F172A
WHITE = (255, 255, 255)

S = 8  # 超采样倍数
CANVAS = 256 * S


def lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def grad_color(x: float, x0: float, x1: float) -> tuple:
    """横向 teal→sky 渐变（对角向近似：以 x 为主）。"""
    t = max(0.0, min(1.0, (x - x0) / (x1 - x0)))
    return lerp(TEAL, SKY, t)


def rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def build() -> Image.Image:
    img = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # ---------- 底板：深蓝圆角方 ----------
    margin = 10 * S
    d.rounded_rectangle(
        [margin, margin, CANVAS - margin, CANVAS - margin],
        radius=int((CANVAS - 2 * margin) * 0.225),
        fill=NIGHT,
    )

    # 渐变按到底板几何坐标计算
    p0, p1 = margin, CANVAS - margin

    # ---------- 白色气泡（原文，左上） ----------
    wbx = 18 * S
    wby = 26 * S
    wbw = 130 * S
    wbh = 88 * S
    wbr = 30 * S
    rounded_rect(d, [wbx, wby, wbx + wbw, wby + wbh], wbr, WHITE)
    # 气泡尾巴（左下角，指向说话者）
    d.polygon(
        [(wbx + 22 * S, wby + wbh - 4 * S), (wbx + 44 * S, wby + wbh - 4 * S), (wbx + 18 * S, wby + wbh + 24 * S)],
        fill=WHITE,
    )

    # ---------- 声波五柱（渐变，居中对称） ----------
    bar_w = 13 * S
    gap = 9 * S
    heights = [26, 46, 60, 40, 22]  # 相对高度（S 单位再乘）
    total_w = 5 * bar_w + 4 * gap
    bx = wbx + (wbw - total_w) // 2
    cy = wby + wbh // 2  # 垂直居中
    for i, h in enumerate(heights):
        h_px = h * S
        x0 = bx + i * (bar_w + gap)
        x1 = x0 + bar_w
        color = grad_color((x0 + x1) / 2, p0, p1)
        rounded_rect(
            d,
            [x0, cy - h_px // 2, x1, cy + h_px // 2],
            radius=bar_w // 2,
            fill=color,
        )

    # ---------- 渐变气泡（译文，右下，叠放） ----------
    gbx = 108 * S
    gby = 92 * S
    gbw = 130 * S
    gbh = 88 * S
    gbr = 30 * S
    # 渐变底色：先画到独立图层，再逐列渐变填充（简化：用横向线性贴色）
    # 用逐列画法实现气泡渐变（在裁剪的 rounded rect 内）
    grad = Image.new("RGBA", (gbw, gbh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for xx in range(gbw):
        gd.line([(xx, 0), (xx, gbh)], fill=grad_color(gbx + xx, p0, p1))
    mask = Image.new("L", (gbw, gbh), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, gbw - 1, gbh - 1], radius=gbr, fill=255)
    md.polygon(
        [(gbw - 44 * S, gbh - 1), (gbw - 22 * S, gbh - 1), (gbw - 8 * S, gbh + 22 * S)],
        fill=255,
    )
    img.paste(grad, (gbx, gby), mask)

    # ---------- 译文两条字幕行（白色圆角条） ----------
    d.rounded_rectangle(
        [gbx + 20 * S, gby + 24 * S, gbx + 20 * S + 78 * S, gby + 24 * S + 16 * S],
        radius=8 * S,
        fill=WHITE,
    )
    d.rounded_rectangle(
        [gbx + 20 * S, gby + 50 * S, gbx + 20 * S + 52 * S, gby + 50 * S + 16 * S],
        radius=8 * S,
        fill=(255, 255, 255, 190),
    )

    return img


def main() -> None:
    img = build()
    down = img.resize((256, 256), Image.LANCZOS)
    down.save(os.path.join(HERE, "icon_master_1024.png".replace("1024", "master") if False else "icon_master_256.png"))
    big = img.resize((1024, 1024), Image.LANCZOS) if False else down
    # ico：多尺寸（含 16px 小图）
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    down.save(
        os.path.join(HERE, "app.ico"),
        format="ICO",
        sizes=sizes,
    )
    # 预览：浅/深两块背景各贴一枚
    prev = Image.new("RGBA", (640, 320), (0, 0, 0, 0))
    light = Image.new("RGBA", (320, 320), (244, 244, 242, 255))
    dark = Image.new("RGBA", (320, 320), (28, 28, 30, 255))
    prev.paste(light, (0, 0))
    prev.paste(dark, (320, 0))
    for ox in (96, 416):
        prev.alpha_composite(down, (ox, 32))
    prev.save(os.path.join(HERE, "icon_preview.png"))
    print("done:", os.path.join(HERE, "app.ico"))


if __name__ == "__main__":
    main()
