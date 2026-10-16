"""生成"大雪花 + 小雪花"多版图标方案的总览预览,用于挑选。

输出: assets/logo_variants.png
      八个构图方案 + 一格配色参考。每格含 256 大图与 64/48/32/16 小尺寸,
      便于同时判断"远看辨识度"和"任务栏小图标会不会糊"。

跑法: .venv/Scripts/python.exe tools/logo_variants.py
选定后: 在 tools/make_icon.py 里把 VARIANT 改成对应编号即可出正式 .ico
"""
import os
import sys

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QGuiApplication, QImage, QPainter, QPen,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logo_designs as L  # noqa: E402

SS = 4                       # 超采样倍数:先放大绘制再缩回,边缘更干净
PREVIEW_SIZES = [64, 48, 32, 16]
BIG = 256

CELL_W, CELL_H = 336, 448
COLS = 3
PAD = 16
HEADER_H = 62

# 第 9 格(index 8)专放配色参考
COLOR_CELL = 8


def render(size: int, variant: int, palette=None) -> QImage:
    big = QImage(size * SS, size * SS, QImage.Format.Format_ARGB32_Premultiplied)
    big.fill(Qt.GlobalColor.transparent)
    p = QPainter(big)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(SS, SS)
    L.draw(variant, p, float(size), palette=palette)
    p.end()
    return big.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


def _card(p, x, y):
    p.setPen(QPen(QColor('#E2E6EB'), 1))
    p.setBrush(QBrush(QColor('#FFFFFF')))
    p.drawRoundedRect(QRectF(x, y, CELL_W, CELL_H), 12, 12)


def _badge(p, x, y, text):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#2F6FEB'))
    p.drawRoundedRect(QRectF(x, y, 26, 22), 6, 6)
    p.setPen(QColor('#FFFFFF'))
    f = QFont(); f.setPixelSize(13); f.setBold(True); p.setFont(f)
    p.drawText(QRectF(x, y, 26, 22), Qt.AlignmentFlag.AlignCenter, text)


def _label(p, x, y, w, h, text, size=12, color='#6E7781', bold=False,
           align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
           wrap=False):
    p.setPen(QColor(color))
    f = QFont(); f.setPixelSize(size); f.setBold(bold); p.setFont(f)
    flags = align
    if wrap:
        flags |= Qt.TextFlag.TextWordWrap
    p.drawText(QRectF(x, y, w, h), flags, text)


def _draw_variant_cell(p, x, y, num, name, desc, fn):
    _card(p, x, y)
    _badge(p, x + 12, y + 12, str(num))
    _label(p, x + 46, y + 12, CELL_W - 58, 22, name, size=12)

    big = render(BIG, num)
    p.drawImage(QRectF(x + (CELL_W - BIG) / 2.0, y + 42, BIG, BIG), big)

    total = sum(PREVIEW_SIZES) + 12 * (len(PREVIEW_SIZES) - 1)
    sx = x + (CELL_W - total) / 2.0
    sy = y + 42 + BIG + 14
    for s in PREVIEW_SIZES:
        p.drawImage(QPointF(sx, sy + (64 - s)), render(s, num))
        _label(p, sx - 6, sy + 68, s + 12, 14, str(s), size=10,
               color='#9AA4AE', align=Qt.AlignmentFlag.AlignCenter)
        sx += s + 12

    _label(p, x + 14, sy + 88, CELL_W - 28, 36, desc, size=11,
           color='#5A6570', align=Qt.AlignmentFlag.AlignHCenter, wrap=True)


def _draw_color_cell(p, x, y):
    """第 9 格:同一构图(星伴)下的三种配色参考。"""
    _card(p, x, y)
    _badge(p, x + 12, y + 12, '9')
    _label(p, x + 46, y + 12, CELL_W - 58, 22, '配色参考(同构图)', size=12)

    size = 92
    gap = 10
    total = size * len(L.PALETTES) + gap * (len(L.PALETTES) - 1)
    sx = x + (CELL_W - total) / 2.0
    for name, top, mid, bot in L.PALETTES:
        p.drawImage(QRectF(sx, y + 70, size, size),
                    render(128, 1, palette=(top, mid, bot)).scaled(
                        size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
        _label(p, sx - 8, y + 168, size + 16, 30, name, size=10,
               color='#5A6570', align=Qt.AlignmentFlag.AlignHCenter, wrap=True)
        sx += size + gap

    _label(p, x + 14, y + 224, CELL_W - 28, 40,
           '底色调性只是参考,和上面 8 版构图可以任意组合 ——\n'
           '说「5 号构图 + 冰晶青」这种组合也行。',
           size=11, color='#5A6570',
           align=Qt.AlignmentFlag.AlignHCenter, wrap=True)


def main():
    app = QGuiApplication(sys.argv)      # 画文字需要 GUI 环境
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outdir = os.path.join(root, 'assets')
    os.makedirs(outdir, exist_ok=True)

    cells = list(L.VARIANTS) + [None]   # 末位 None = 配色参考格
    rows = (len(cells) + COLS - 1) // COLS
    W = PAD + COLS * (CELL_W + PAD)
    H = HEADER_H + PAD + rows * (CELL_H + PAD)

    canvas = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(QColor('#EEF1F5'))
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    _label(p, PAD + 4, 14, W - 2 * PAD, 24,
           'ICE-Babysitting · 图标方案备选(大雪花 + 小雪花)',
           size=17, color='#1F2328', bold=True)
    _label(p, PAD + 4, 38, W - 2 * PAD, 18,
           '每格:上方 256px 大图,下方 64 / 48 / 32 / 16 —— '
           '顺便看小尺寸会不会糊。告诉我编号即可。',
           size=12, color='#6E7781')

    for i, item in enumerate(cells):
        r, c = divmod(i, COLS)
        x = PAD + c * (CELL_W + PAD)
        y = HEADER_H + PAD + r * (CELL_H + PAD)
        if item is None:
            _draw_color_cell(p, x, y)
        else:
            _draw_variant_cell(p, x, y, item[0], item[1], item[2], item[3])

    p.end()
    out = os.path.join(outdir, 'logo_variants.png')
    canvas.save(out)
    print('已生成总览预览:', out, '(%d x %d)' % (W, H))
    return 0


if __name__ == '__main__':
    sys.exit(main())
