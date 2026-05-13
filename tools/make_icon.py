# -*- coding: utf-8 -*-
"""FFAN 应用图标生成器 — 六边形 + 紫青渐变 + 几何 F 字符 + 金色点缀

设计原则:
  - 六边形外形 (角朝上) — 与圆形/方形 app 区分, 不与 op.gg / blitz / riot 撞
  - 径向渐变 (深紫 → 青绿) — 匹配 UI 主题色
  - 金色 F 字符 — 品牌锚点
  - 右下小三角金点 — 打破对称, 增加动感

输出:
  web/icon-1024.png        高分辨率源
  web/icon-256.png         README / 网页用
  web/icon.ico             Windows 应用图标 (含 16/32/48/64/128/256 多尺寸)

用法:
  python tools/make_icon.py
"""
from __future__ import annotations
import math
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.stderr.write("需要 Pillow: pip install Pillow\n")
    sys.exit(1)


# ============================================================================
# 设计参数
# ============================================================================
# 配色 (RGB, 0-255)
COLOR_BG_CENTER  = (45,  27, 105)    # 深紫中心 #2D1B69
COLOR_BG_EDGE    = (26, 143, 163)    # 青绿边缘 #1A8FA3
COLOR_BORDER     = (72, 209, 209)    # 边框 (青绿亮)  #48D1D1
COLOR_INNER_RING = (179, 157, 255)   # 内描边 (紫)    #B39DFF
COLOR_F          = (240, 199, 94)    # F 字符金色    #F0C75E
COLOR_ACCENT     = (255, 138, 77)    # 右下点缀 (橙) #FF8A4D

# 几何比例
HEX_SCALE        = 0.46              # 六边形外接圆 / canvas size
INNER_RING_SCALE = 0.42              # 内描边 hex
F_HEIGHT_SCALE   = 0.46              # F 高度
F_WIDTH_SCALE    = 0.28              # F 宽度 (实际 = 高 * 比例)
F_STROKE_SCALE   = 0.055             # F 笔画粗度
BORDER_WIDTH_SCALE = 0.014           # 外描边粗度
ACCENT_SCALE     = 0.085             # 右下三角大小


def find_font(size_px):
    """找一个可用的粗体字体. 失败返回 PIL 默认 (会丑)."""
    candidates = [
        "C:/Windows/Fonts/seguibl.ttf",   # Segoe UI Black (现代几何感强)
        "C:/Windows/Fonts/segoeuib.ttf",  # Segoe UI Bold
        "C:/Windows/Fonts/arialbd.ttf",   # Arial Bold (fallback)
        "C:/Windows/Fonts/tahomabd.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size_px)
            except Exception:
                continue
    return ImageFont.load_default()


def make_icon(size=1024):
    """画 size×size 的图标. 返回 RGBA Image."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx, cy = size / 2, size / 2

    # 1. 径向渐变背景 (画很多同心圆, 从外向内画, 让中心是 center 色)
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    max_r = size * 0.52    # 渐变半径稍大于 hex, 留一点边
    steps = 220
    for i in range(steps, 0, -1):
        t = i / steps   # 1 (外) → 0 (中心)
        r = max_r * t
        rr = int(COLOR_BG_CENTER[0] + (COLOR_BG_EDGE[0] - COLOR_BG_CENTER[0]) * t)
        gg = int(COLOR_BG_CENTER[1] + (COLOR_BG_EDGE[1] - COLOR_BG_CENTER[1]) * t)
        bb = int(COLOR_BG_CENTER[2] + (COLOR_BG_EDGE[2] - COLOR_BG_CENTER[2]) * t)
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(rr, gg, bb, 255))

    # 2. 六边形 mask (角朝上)
    R_outer = size * HEX_SCALE
    hex_pts = []
    for i in range(6):
        angle = math.pi / 2 + math.pi / 3 * i
        x = cx + R_outer * math.cos(angle)
        y = cy - R_outer * math.sin(angle)
        hex_pts.append((x, y))

    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.polygon(hex_pts, fill=255)

    # 3. 应用 mask, 得到六边形渐变
    img.paste(grad, (0, 0), mask)

    # 4. 外描边 (青绿)
    draw = ImageDraw.Draw(img)
    bw = max(2, int(size * BORDER_WIDTH_SCALE))
    draw.polygon(hex_pts, outline=COLOR_BORDER, width=bw)

    # 5. 内描边 (紫, 细) — 给一点深度感
    R_inner = size * INNER_RING_SCALE
    inner_hex = []
    for i in range(6):
        angle = math.pi / 2 + math.pi / 3 * i
        x = cx + R_inner * math.cos(angle)
        y = cy - R_inner * math.sin(angle)
        inner_hex.append((x, y))
    draw.polygon(inner_hex, outline=COLOR_INNER_RING + (180,), width=max(1, int(size * 0.005)))

    # 6. 中心 "F" 字符 — 手画矩形构成 (确保几何感清晰, 不依赖字体)
    fh = size * F_HEIGHT_SCALE
    fw = fh * (F_WIDTH_SCALE / F_HEIGHT_SCALE * (F_HEIGHT_SCALE / F_WIDTH_SCALE))
    fw = size * F_WIDTH_SCALE
    sw = size * F_STROKE_SCALE
    fx = cx - fw / 2
    fy = cy - fh / 2

    # 微微左移让 F 视觉居中 (F 的右侧空 → 重心偏左)
    visual_shift = size * 0.015
    fx -= visual_shift

    # 竖线 (左)
    draw.rectangle([fx, fy, fx + sw, fy + fh], fill=COLOR_F)
    # 顶横线
    draw.rectangle([fx, fy, fx + fw, fy + sw], fill=COLOR_F)
    # 中横线 (略短)
    mid_y = fy + fh * 0.43
    draw.rectangle([fx, mid_y, fx + fw * 0.72, mid_y + sw * 0.85], fill=COLOR_F)

    # 7. 右下角金色三角点缀 (打破对称, 增加品牌识别度)
    acc = size * ACCENT_SCALE
    # 三角顶点放在六边形右下边缘内侧
    ax = cx + R_outer * math.cos(-math.pi / 3) * 0.78
    ay = cy + R_outer * math.sin(math.pi / 3) * 0.78
    tri = [
        (ax, ay - acc / 2),
        (ax + acc, ay),
        (ax, ay + acc / 2),
    ]
    draw.polygon(tri, fill=COLOR_ACCENT)

    # 8. 左上微光斑 (可选, 增加质感)
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for r in range(int(size * 0.18), 0, -1):
        alpha = int(60 * (1 - r / (size * 0.18)))
        glow_draw.ellipse(
            [cx - R_outer * 0.5 - r, cy - R_outer * 0.5 - r,
             cx - R_outer * 0.5 + r, cy - R_outer * 0.5 + r],
            fill=(255, 255, 255, alpha))
    # 用六边形 mask 限制光斑只在六边形内
    glow_masked = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_masked.paste(glow, (0, 0), mask)
    img = Image.alpha_composite(img, glow_masked)

    return img


def main():
    out_dir = Path(__file__).resolve().parent.parent / "web"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 主图 (1024 高分辨率)
    img1024 = make_icon(1024)
    img1024.save(out_dir / "icon-1024.png", optimize=True)
    print(f"  ✓ {out_dir / 'icon-1024.png'} (1024x1024)")

    # 256 给 README / 网页 / favicon 用
    img256 = img1024.resize((256, 256), Image.LANCZOS)
    img256.save(out_dir / "icon-256.png", optimize=True)
    print(f"  ✓ {out_dir / 'icon-256.png'} (256x256)")

    # ICO 多尺寸 (Windows 标准: 16, 32, 48, 64, 128, 256)
    ico_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    # 给小尺寸单独画 (16/32 直接缩可能糊, 重新绘制更清晰)
    # 实际上 1024 缩到 16 PIL 用 LANCZOS 还是不错的, 这里先简化
    img1024.save(out_dir / "icon.ico",
                 format="ICO", sizes=ico_sizes,
                 append_images=[img1024.resize(s, Image.LANCZOS) for s in ico_sizes[1:]])
    print(f"  ✓ {out_dir / 'icon.ico'} (multi-size: 16-256)")

    # 给 favicon 一个小副本
    fav = img1024.resize((32, 32), Image.LANCZOS)
    fav.save(out_dir / "favicon.png", optimize=True)
    print(f"  ✓ {out_dir / 'favicon.png'} (32x32 favicon)")


if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    print("=== FFAN 图标生成 ===")
    main()
    print("\n完成. 看 web/ 目录.")
    print("更新 build.spec icon='web/icon.ico' 然后重打包.")
