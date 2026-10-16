"""应用图标的基础绘制件与多个"大雪花 + 小雪花"构图方案。

供 tools/logo_variants.py(出总览预览)与 tools/make_icon.py(出正式 .ico)共用,
这样选定方案后只需在 make_icon.py 里指定编号即可,不必重抄一遍绘制代码。

坐标约定:所有尺寸都按画布边长 s 的比例给出,与分辨率无关。
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen

WHITE = QColor(255, 255, 255, 250)

# 冰蓝渐变(自上而下:亮冰 -> 中蓝 -> 深蓝)
BG_TOP, BG_MID, BG_BOT = "#63C2FF", "#2F7BE8", "#123E92"

# 备选配色:(名称, 顶, 中, 底)
PALETTES = [
    ("冰川蓝(当前)", BG_TOP, BG_MID, BG_BOT),
    ("冰晶青", "#A9F0EE", "#2FB3C9", "#0E5F72"),
    ("夜空蓝", "#2B3A6B", "#141C3A", "#070B18"),
]


def draw_background(p: QPainter, s: float,
                    top=BG_TOP, mid=BG_MID, bot=BG_BOT):
    """冰蓝渐变圆角方块 + 顶部高光,给一点冰面质感。"""
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0.00, QColor(top))
    grad.setColorAt(0.48, QColor(mid))
    grad.setColorAt(1.00, QColor(bot))
    inset = s * 0.015
    radius = s * 0.235
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(inset, inset, s - 2 * inset, s - 2 * inset),
                      radius, radius)

    hl = QLinearGradient(0, 0, 0, s * 0.55)
    hl.setColorAt(0.0, QColor(255, 255, 255, 70))
    hl.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(hl))
    p.drawRoundedRect(QRectF(inset, inset, s - 2 * inset, s * 0.5),
                      radius, radius)


def snowflake(p: QPainter, cx: float, cy: float, r: float, lw: float,
              detail=True, dot=True, color=None):
    """画一朵雪花:6 根主枝;detail=True 时每枝加两段分叉(越靠外越小)。"""
    c = WHITE if color is None else QColor(color)
    pen = QPen(c)
    pen.setWidthF(lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    for i in range(6):
        a = math.radians(60 * i - 90)
        ca, sa = math.cos(a), math.sin(a)
        p.drawLine(QPointF(cx, cy), QPointF(cx + r * ca, cy + r * sa))
        if not detail:
            continue
        # (位置比例, 分叉长度比例, 张角)
        for frac, blen, ang in ((0.52, 0.32, 42.0), (0.84, 0.16, 36.0)):
            bx, by = cx + r * frac * ca, cy + r * frac * sa
            for sign in (-1.0, 1.0):
                ab = a + sign * math.radians(ang)
                length = r * blen
                p.drawLine(QPointF(bx, by),
                           QPointF(bx + length * math.cos(ab),
                                   by + length * math.sin(ab)))

    if dot:
        rr = max(lw * 0.95, r * 0.13)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QPointF(cx, cy), rr, rr)


def small_flake(p: QPainter, cx: float, cy: float, r: float, s: float,
                detail=True, filled=False, color=None):
    """小雪花。按尺寸自动降级,保证小图标里不会糊成一团:

    - s < 34  : 退化成"亮点"(仍能读出大带小的构图)
    - s < 56  : 只画 6 根主枝,不加分叉
    - 其余    : 与主雪花同结构(分叉略简化)
    filled=True 用粗线画成实心剪影,与描边大雪花形成对比。
    """
    c = WHITE if color is None else QColor(color)
    if s < 34:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        rr = r * 0.62
        p.drawEllipse(QPointF(cx, cy), rr, rr)
        return
    if filled:
        snowflake(p, cx, cy, r, r * 0.54, detail=False, dot=False, color=c)
        return
    lw = r * (0.30 if s >= 56 else 0.40)
    snowflake(p, cx, cy, r, lw,
              detail=(detail and s >= 56), dot=False, color=c)


# --------------------------------------------------------------------------
# 备选构图。签名统一为 (p, s, detail):
#   s      = 画布边长
#   detail = 是否画分叉(该尺寸下),由调用方按尺寸给出
# --------------------------------------------------------------------------

def v1_star(p, s, detail):
    """星伴 —— 大雪花居中偏左上,右下角一颗小雪花。"""
    snowflake(p, 0.455 * s, 0.445 * s, 0.305 * s, s * 0.056, detail=detail)
    small_flake(p, 0.757 * s, 0.748 * s, 0.125 * s, s, detail)


def v2_twin(p, s, detail):
    """双雪 —— 对角两颗,比例约 3:2,呼应感强。"""
    snowflake(p, 0.400 * s, 0.400 * s, 0.255 * s, s * 0.050, detail=detail)
    small_flake(p, 0.720 * s, 0.720 * s, 0.168 * s, s, detail)


def v3_fall(p, s, detail):
    """雪落 —— 一大两小散布,有飘落感。"""
    snowflake(p, 0.425 * s, 0.475 * s, 0.285 * s, s * 0.054, detail=detail)
    small_flake(p, 0.782 * s, 0.272 * s, 0.098 * s, s, detail)
    small_flake(p, 0.712 * s, 0.755 * s, 0.074 * s, s, detail)


def v4_orbit(p, s, detail):
    """环绕 —— 大雪花居中,三颗小雪花按 120° 环绕。

    雪花主枝在 270°+60°k 方向,所以小雪花必须落在 120°k 的"臂间空档"上,
    否则会正好叠在主枝上(踩过这个坑)。
    """
    snowflake(p, 0.500 * s, 0.500 * s, 0.243 * s, s * 0.050, detail=detail)
    for k in range(3):
        a = math.radians(120 * k)
        cx = 0.5 * s + 0.312 * s * math.cos(a)
        cy = 0.5 * s + 0.312 * s * math.sin(a)
        small_flake(p, cx, cy, 0.072 * s, s, detail)


def v5_contrast(p, s, detail):
    """实心 —— 描边大雪花 + 实心小雪花,强弱对比最明显。"""
    snowflake(p, 0.445 * s, 0.440 * s, 0.300 * s, s * 0.052, detail=detail)
    small_flake(p, 0.752 * s, 0.752 * s, 0.128 * s, s, detail, filled=True)


def v6_tight(p, s, detail):
    """紧贴 —— 两颗相邻几乎相切但不重叠,构图最饱满。"""
    snowflake(p, 0.420 * s, 0.420 * s, 0.280 * s, s * 0.054, detail=detail)
    small_flake(p, 0.742 * s, 0.742 * s, 0.142 * s, s, detail)


def v7_glow(p, s, detail):
    """透光 —— 大雪花半透明,小雪花纯白,拉开前后层次。

    注意:半透明在缩到小尺寸后会被背景吃掉(实测 32px 以下几乎看不见),
    所以小尺寸自动改回不透明 —— 图标首先要小得清,层次感是锦上添花。
    """
    big_color = QColor(255, 255, 255, 135) if s >= 56 else None
    snowflake(p, 0.450 * s, 0.442 * s, 0.305 * s, s * 0.056,
              detail=detail, color=big_color)
    small_flake(p, 0.757 * s, 0.750 * s, 0.130 * s, s, detail)


def v8_light(p, s, detail):
    """浅底 —— 与"星伴"同构图,换成更亮的浅冰蓝底。"""
    v1_star(p, s, detail)


# (编号, 名称, 一句话说明, 绘制函数, 自定义配色或 None)
VARIANTS = [
    (1, "星伴", "大雪花居中偏左上,右下角一颗小雪花", v1_star, None),
    (2, "双雪", "对角两颗大小雪花,比例约 3:2", v2_twin, None),
    (3, "雪落", "一大两小散布,有飘落感", v3_fall, None),
    (4, "环绕", "大雪花居中,三颗小雪花环绕", v4_orbit, None),
    (5, "实心", "描边大雪花 + 实心小雪花,对比最强", v5_contrast, None),
    (6, "紧贴", "两颗相邻近相切,构图最饱满", v6_tight, None),
    (7, "透光", "大雪花半透明、小雪花纯白,有层次", v7_glow, None),
    (8, "浅底", "同「星伴」构图,底色更亮更清爽", v8_light,
     ("#A8E2FF", "#58A6F5", "#2C6FD6")),
]


def draw(variant: int, p: QPainter, s: float, detail=None,
         palette=None):
    """按编号绘制完整图标(背景 + 雪花)。

    palette 可传 (顶, 中, 底) 覆盖该方案默认底色。
    """
    if detail is None:
        detail = s >= 32        # 32px 起仍带分叉(超采样后缩回,线还立得住)
    item = next(v for v in VARIANTS if v[0] == variant)
    _num, _name, _desc, fn, bg = item
    if palette is None:
        palette = bg
    if palette is None:
        draw_background(p, s)
    else:
        draw_background(p, s, *palette)
    fn(p, s, detail)
