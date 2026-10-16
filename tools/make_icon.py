"""生成应用图标 assets/ice-babysitting.ico(多尺寸)与预览图。

设计来源:tools/logo_designs.py —— 那里集中放着所有"大雪花 + 小雪花"构图方案,
改 VARIANT 编号即可切换(先用 tools/logo_variants.py 出总览挑一遍)。

- 每个尺寸都**单独绘制**(而非从 256 缩放),保证小图标边缘清晰;
- 小尺寸会自动降级(去掉分叉 / 小雪花退化成亮点),避免缩到 16px 糊成一团。

跑法: .venv/Scripts/python.exe tools/make_icon.py
"""
import os
import struct
import sys

from PyQt6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QGuiApplication, QImage, QPainter,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import logo_designs as L  # noqa: E402

# ---- 选定方案:改这个编号即可(见 tools/logo_variants.py 的总览图) ----
VARIANT = 3             # 「雪落」:大雪花 + 一大两小,有飘落动感
PALETTE = None          # 想换底色就传 ("#顶", "#中", "#底"),见 L.PALETTES

SIZES = [16, 24, 32, 48, 64, 128, 256]
SS = 4  # 超采样倍数(先放大 4 倍绘制,再缩回去,边缘更干净)


def render_image(size: int) -> QImage:
    big = QImage(size * SS, size * SS, QImage.Format.Format_ARGB32_Premultiplied)
    big.fill(Qt.GlobalColor.transparent)
    p = QPainter(big)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(SS, SS)
    L.draw(VARIANT, p, float(size), palette=PALETTE)
    p.end()
    return big.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


def to_png(img: QImage) -> bytes:
    # 注意:必须用无参 QBuffer(自带内部缓冲区)。
    # 写成 QBuffer(QByteArray()) 会把缓冲区交给一个临时对象,
    # 它被 GC 回收后 QBuffer 就成了悬空指针,save() 时直接段错误(实测踩过)。
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(items, out_path):
    """按 ICO 容器格式打包(Vista+ 支持 PNG 载荷,无需额外依赖)。"""
    n = len(items)
    header = struct.pack('<HHH', 0, 1, n)
    offset = 6 + 16 * n
    entries, blobs = b'', b''
    for size, blob in items:
        dim = 0 if size >= 256 else size          # 0 表示 256
        entries += struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32,
                               len(blob), offset)
        offset += len(blob)
        blobs += blob
    with open(out_path, 'wb') as f:
        f.write(header + entries + blobs)


def main():
    app = QGuiApplication(sys.argv)          # 预览图要画文字,需要 GUI 环境
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outdir = os.path.join(root, 'assets')
    os.makedirs(outdir, exist_ok=True)

    item = next(v for v in L.VARIANTS if v[0] == VARIANT)
    name = item[1]

    images = {s: render_image(s) for s in SIZES}
    ico = os.path.join(outdir, 'ice-babysitting.ico')
    write_ico([(s, to_png(images[s])) for s in SIZES], ico)
    print('已生成 %s (%.1f KB, %d 个尺寸: %s)'
          % (ico, os.path.getsize(ico) / 1024, len(SIZES),
             ', '.join(str(s) for s in SIZES)))
    print('使用方案 #%d「%s」' % (VARIANT, name))

    # ---- 预览图:左边 256 大图,右边各小尺寸并排 ----
    W, H = 880, 320
    prev = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    prev.fill(QColor('#F7F8FA'))
    pp = QPainter(prev)
    pp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pp.drawImage(QRectF(36, 32, 256, 256), images[256])
    f = pp.font(); f.setPixelSize(12); pp.setFont(f)
    pp.setPen(QColor('#6E7781'))
    pp.drawText(QRectF(36, 292, 256, 20), Qt.AlignmentFlag.AlignCenter, '256px')
    x = 340
    for s in (128, 64, 48, 32, 24, 16):
        pp.drawImage(QPointF(x, 32 + (128 - s) / 2.0), images[s])
        pp.drawText(QRectF(x - 14, 170, s + 28, 20),
                    Qt.AlignmentFlag.AlignCenter, '%d' % s)
        x += s + 30
    pp.setPen(QColor('#1F2328'))
    f.setPixelSize(14); pp.setFont(f)
    pp.drawText(QRectF(340, 214, 500, 24), Qt.AlignmentFlag.AlignLeft,
                'ICE-Babysitting  应用图标(方案 #%d %s)' % (VARIANT, name))
    pp.setPen(QColor('#6E7781'))
    f.setPixelSize(12); pp.setFont(f)
    pp.drawText(QRectF(340, 240, 520, 60), Qt.TextFlag.TextWordWrap,
                '冰蓝渐变圆角方块 + 大雪花带小雪花。每个尺寸单独绘制:'
                '32px 以上保留雪花分叉,更小的尺寸自动去掉分叉、'
                '小雪花退化成亮点,保证任务栏小图标也清晰不糊。')
    pp.end()
    prev_path = os.path.join(outdir, 'logo_preview.png')
    prev.save(prev_path)
    print('预览图:', prev_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
