"""主窗口 —— 无边框赛博风小窗浏览器。

实现要点(全部针对前两代踩过的坑):
1. 窗口状态实时保存:moveEvent/resizeEvent 持续更新 config,关闭时兜底 flush。
2. 启动恢复:读取上次的 位置/大小/最大化/透明度/置顶/上次网址。
3. 无边框自绘标题栏 + 边缘拖拽缩放(游戏小窗也需要能随手调大小)。
4. 全局热键动作绑定(播放/快进快退/倍速/音量/最大化/隐藏/置顶/穿透/退出)。
"""
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QColor, QCursor, QGuiApplication, QIcon, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
    QSlider, QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__
from .logger import get_logger
from .webview_container import WebViewContainer
from .gamepad import GamepadManager
from .settings_dialog import SettingsDialog, ACTION_LABELS
from . import theme
from .utils import win32_api

# 边缘缩放热区(像素)
_EDGE = 6
_MIN_W, _MIN_H = 320, 400

# 配置里的窗口几何明显损坏(整块跑到屏幕外)时,重置为这个尺寸
_RESET_W, _RESET_H = 960, 700

# 标题栏窗口按钮的矢量图标边长(逻辑像素)
_WINBTN_ICON = 16
_BTN_FG = "#6E7781"       # 图标常态色
_BTN_FG_ACTIVE = "#2F6FEB"  # 悬停/激活色
_CLOSE_FG_ACTIVE = "#FFFFFF"  # 关闭键悬停时背景变红,图标转白

_glyph_cache = {}


def _glyph_icon(kind, color=_BTN_FG, active=_BTN_FG_ACTIVE):
    """用 QPainter 矢量绘制标题栏窗口按钮的图标。

    为什么不用文字字形(— □ ✕):不同字形的墨迹大小天生不一样,还受字体影响 ——
    同一个字号下 □ 明显比 ✕ 小,靠调字号没法同时对齐三者。
    矢量绘制能精确控制每根线的位置/粗细,三个按钮完全统一,也不会出现字体缺字。
    """
    key = (kind, color, active)
    cached = _glyph_cache.get(key)
    if cached is not None:
        return cached

    ic = QIcon()
    s = _WINBTN_ICON
    dpr = 2  # 超采样绘制,避免锯齿
    for mode, col in ((QIcon.Mode.Normal, color),
                      (QIcon.Mode.Active, active),
                      (QIcon.Mode.Selected, active)):
        pm = QPixmap(s * dpr, s * dpr)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(col))
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if kind == "min":
            p.drawLine(QPointF(s * 0.15, s * 0.5), QPointF(s * 0.85, s * 0.5))
        elif kind == "max":
            p.drawRect(QRectF(s * 0.155, s * 0.155, s * 0.69, s * 0.69))
        elif kind == "restore":
            p.drawRect(QRectF(s * 0.15, s * 0.34, s * 0.51, s * 0.51))
            p.drawLine(QPointF(s * 0.34, s * 0.18), QPointF(s * 0.82, s * 0.18))
            p.drawLine(QPointF(s * 0.82, s * 0.18), QPointF(s * 0.82, s * 0.66))
            p.drawLine(QPointF(s * 0.82, s * 0.66), QPointF(s * 0.66, s * 0.66))
        elif kind == "close":
            p.drawLine(QPointF(s * 0.205, s * 0.205), QPointF(s * 0.795, s * 0.795))
            p.drawLine(QPointF(s * 0.795, s * 0.205), QPointF(s * 0.205, s * 0.795))
        p.end()
        ic.addPixmap(pm, mode)
    _glyph_cache[key] = ic
    return ic

# 穿透时鼠标悬停窗口的透明度
_THROUGH_HOVER_OPACITY = 0.4

_EDGE_CURSORS = {
    "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
}


class _ResizeHandle(QWidget):
    """窗口边缘的透明缩放手柄。

    独立小控件盖在窗口四边/四角上(不进入布局,raise 到最前),
    专门接收边缘的鼠标事件做窗口缩放。
    好处:网页(QWebEngineView)区域完全不安装任何过滤器,
    网页内的点击/滚动 100% 交给浏览器,不会再出现"点不动网页"的问题。
    """

    def __init__(self, parent, edge):
        super().__init__(parent)
        self._edge = edge
        self._win = parent
        self.setCursor(_EDGE_CURSORS[edge])

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._win._begin_resize(self._edge, e.globalPos())

    def mouseMoveEvent(self, e):
        self._win._do_resize(e.globalPos())

    def mouseReleaseEvent(self, e):
        self._win._end_resize()


class MainWindow(QMainWindow):
    def __init__(self, config, hotkeys):
        super().__init__()
        self._log = get_logger()
        self._config = config
        self._hotkeys = hotkeys

        self._click_through = False
        self._hover_timer = None
        self._topmost = bool(config.get("window", "topmost", True))
        self._dragging = False
        self._drag_offset = QPoint()
        self._drag_offset_native = None  # 物理像素的抓取偏移(见 mousePressEvent)
        self._resizing = False
        self._resize_edge = None
        self._resize_native_ok = False   # 缩放是否走物理像素方案
        self._press_rect_native = None
        self._press_cursor_native = (0, 0)
        self._min_native = (_MIN_W, _MIN_H)
        self._press_geom = QRect()
        self._geom_dirty = False
        self._geom_timer = None
        self._hold_timer = None  # 长按连发定时器(快退键)
        # 快进键的"点按 / 长按"区分(点按=快进5秒,长按=倍速播放,对齐 B站)
        self._fwd_timer = None       # 点按判定的单次定时器
        self._fwd_held = False       # 快进键当前是否按住
        self._fwd_boosting = False   # 当前是否处于"长按倍速"状态
        self._holding_speed = False  # 倍速是否由长按临时提升(用于防止写进配置)
        self._hover_activate_timer = None  # 鼠标悬停自动激活(游戏场景 hover 修复)
        self._gamepad = None  # 手柄轮询管理器
        self._pad_hold_timers = {}  # 手柄长按连发定时器:action -> QTimer
        self._hotkey_watchdog = None  # 键盘钩子看门狗定时器

        self._build_ui()
        self._restore_window_state()
        self._bind_hotkeys()
        self._bind_gamepad()
        self._start_hover_activate()
        self._start_hotkey_watchdog()
        self._log.info("%s v%s 启动完成", APP_NAME, __version__)

    # ---------------- UI ----------------
    def _build_ui(self):
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        if self._topmost:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(_MIN_W, _MIN_H)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        self._vbox = QVBoxLayout(root)
        self._vbox.setContentsMargins(1, 1, 1, 1)
        self._vbox.setSpacing(0)

        self._title_bar = self._build_title_bar()
        self._vbox.addWidget(self._title_bar)

        self._web = WebViewContainer(self._config)
        self._toolbar = self._build_toolbar()
        self._vbox.addWidget(self._toolbar)

        # WebView2 是原生子窗口,会盖住 Qt 控件;四周内缩 8px,
        # 给边缘缩放手柄留出 Qt 区域(否则手柄被 WebView2 窗口遮挡,无法缩放)。
        self._web_host = QWidget()
        self._web_host.setObjectName("WebHost")
        _wh = QVBoxLayout(self._web_host)
        _wh.setContentsMargins(_EDGE, _EDGE, _EDGE, _EDGE)
        _wh.setSpacing(0)
        _wh.addWidget(self._web)
        self._vbox.addWidget(self._web_host, 1)

        self._status_bar = self._build_status_bar()
        self._vbox.addWidget(self._status_bar)

        # 边缘缩放用独立透明手柄实现(见 _ResizeHandle),
        # 网页区域不安装任何事件过滤器,保证网页交互 100% 正常。
        self._install_resize_handles()

        self._web.url_changed.connect(self._on_url_changed)
        self._web.js_result.connect(self._on_js_result)

        self._apply_rounded_corners()

    def _apply_rounded_corners(self):
        """给无边框窗口套上 Win11 原生圆角。

        注意:setWindowFlags(如切换置顶)会重建原生窗口,圆角属性会丢,
        所以每次重建之后都要重新设一次。
        """
        try:
            ok = win32_api.set_rounded_corners(int(self.winId()))
            self._log.info("窗口圆角: %s", "已启用(Win11 DWM)" if ok else "系统不支持,使用直角")
        except Exception:
            self._log.exception("设置窗口圆角失败")

    def _build_title_bar(self):
        bar = QWidget()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(34)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 4, 0)
        lay.setSpacing(6)

        title = QLabel(APP_NAME)
        title.setObjectName("TitleText")

        self._btn_pin = self._make_title_btn("置顶", "切换置顶（开启时按钮常亮）", self._toggle_topmost)
        self._btn_through = self._make_title_btn("穿透", "鼠标穿透,不挡操作(热键 0)", self._toggle_click_through)
        self._btn_settings = self._make_title_btn("设置", "修改全局热键 / 手柄按键", self._open_settings)
        # 最小化/最大化/关闭统一用 TitleBtnWin 样式(固定 34x26)+ 矢量图标,
        # 三者的大小与线宽完全一致(以前用 —/□/✕ 字形,宽度和墨迹大小都对不齐)
        self._btn_min = self._make_title_btn("", "最小化", self.showMinimized,
                                             win=True, glyph="min")
        self._btn_max = self._make_title_btn("", "最大化/还原(热键 Ctrl+空格)",
                                             self._toggle_maximize, win=True, glyph="max")
        btn_close = self._make_title_btn("", "退出", self.close, win=True, glyph="close")
        # 关闭键悬停时底色变红,图标要跟着转白
        btn_close.setIcon(_glyph_icon("close", _BTN_FG, _CLOSE_FG_ACTIVE))
        btn_close.setObjectName("TitleBtnClose")

        lay.addWidget(title)
        lay.addStretch(1)
        lay.addWidget(self._btn_pin)
        lay.addWidget(self._btn_through)
        lay.addWidget(self._btn_settings)
        lay.addSpacing(4)
        lay.addWidget(self._btn_min)
        lay.addWidget(self._btn_max)
        lay.addWidget(btn_close)
        return bar

    def _build_toolbar(self):
        bar = QWidget()
        bar.setObjectName("ToolBar")
        bar.setFixedHeight(38)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(4)

        self._btn_back = self._make_tool_btn("←", "后退", self._web.back)
        self._btn_fwd = self._make_tool_btn("→", "前进", self._web.forward)
        self._btn_reload = self._make_tool_btn("⟳", "刷新", self._web.reload)
        self._btn_home = self._make_tool_btn("⌂", "回到主页", self._web.go_home)

        self._url_edit = QLineEdit()
        self._url_edit.setObjectName("UrlEdit")
        self._url_edit.setPlaceholderText("输入网址,回车访问(如 bilibili.com)")
        self._url_edit.returnPressed.connect(self._on_url_entered)

        lay.addWidget(self._btn_back)
        lay.addWidget(self._btn_fwd)
        lay.addWidget(self._btn_reload)
        lay.addWidget(self._btn_home)
        lay.addWidget(self._url_edit, 1)
        return bar

    def _build_status_bar(self):
        bar = QWidget()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(28)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(8)

        self._status = QLabel("就绪")
        self._status.setObjectName("StatusText")
        self._status.setProperty("accent", True)

        self._rate_label = QLabel("倍速 1.0x")
        self._rate_label.setObjectName("StatusText")
        self._vol_label = QLabel("音量 100%")
        self._vol_label.setObjectName("StatusText")
        self._pad_label = QLabel("")
        self._pad_label.setObjectName("StatusText")

        lay.addWidget(self._status)
        lay.addStretch(1)
        lay.addWidget(self._pad_label)
        lay.addWidget(self._rate_label)
        lay.addWidget(self._vol_label)
        return bar

    def _make_title_btn(self, text, tip, slot, win=False, glyph=None):
        """标题栏按钮。

        win=True 用于最小化/最大化/关闭:不使用字形字符,改用 _glyph_icon
        矢量绘制的图标,三个按钮的大小和线宽完全一致。
        """
        b = QPushButton("" if win else text)
        b.setObjectName("TitleBtnWin" if win else "TitleBtn")
        if win:
            b.setIcon(_glyph_icon(glyph))
            b.setIconSize(QSize(_WINBTN_ICON, _WINBTN_ICON))
            b.setProperty("glyph", glyph)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _make_tool_btn(self, text, tip, slot):
        b = QPushButton(text)
        b.setObjectName("ToolBtn")
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    # ---------------- 状态恢复/保存 ----------------
    def _restore_window_state(self):
        cfg = self._config
        x = int(cfg.get("window", "x", 100))
        y = int(cfg.get("window", "y", 100))
        w = int(cfg.get("window", "width", 480))
        h = int(cfg.get("window", "height", 640))
        # 关键:收敛几何值。历史版本在多屏不同缩放下拖动会"越拖越大",
        # 并把畸变后的尺寸写进配置 —— 这里做一次合法性钳制,
        # 任何超过屏幕、或跑到屏幕外的旧数据都会被自动拉回正常范围(自愈)。
        x, y, w, h = self._sane_window_rect(x, y, w, h)
        self.setGeometry(x, y, w, h)
        cfg.update("window", {"x": x, "y": y, "width": w, "height": h}, save=True)
        op = float(cfg.get("window", "opacity", 1.0))
        # 重要:opacity == 1.0 时不要调用 setWindowOpacity!
        # 一旦调用,Windows 窗口会变成"分层窗口"(WS_EX_LAYERED),
        # QtWebEngine(Chromium)在分层窗口上初始化会崩溃(实测退出码 127)。
        # 用户实际调低透明度(op < 1.0)时才需要分层。
        if op < 1.0:
            self.setWindowOpacity(op)
        self._update_pin_ui()
        self._update_through_ui()
        QTimer.singleShot(0, self._apply_maximized)

    def _sane_window_rect(self, x, y, w, h):
        """把(可能畸变的)窗口几何收敛到当前显示器可用范围内。

        处理两类脏数据:
        1. 尺寸超过所在屏幕(多屏异缩放下拖动叠加造成);
        2. 位置完全跑到屏幕外(拖出边界后保存,重启看不见窗口);
           这种情况连尺寸一起重置 —— 因为整块在屏外是"畸形尺寸被写进配置"
           的典型特征,不能把它当成用户偏好继续沿用。
        """
        screens = QGuiApplication.screens()
        w = max(_MIN_W, int(w))
        h = max(_MIN_H, int(h))
        if not screens:
            return x, y, w, h

        # 情况 2:整块都在所有屏幕之外 → 数据不可信,位置+尺寸一起重置
        if not any(s.geometry().intersects(QRect(x, y, w, h)) for s in screens):
            area = (QGuiApplication.primaryScreen() or screens[0]).availableGeometry()
            w = min(_RESET_W, area.width())
            h = min(_RESET_H, area.height())
            return int(area.left() + 40), int(area.top() + 40), int(w), int(h)

        target = None
        cx, cy = x + w // 2, y + h // 2
        for s in screens:                       # 优先:中心点所在屏幕
            if s.geometry().contains(cx, cy):
                target = s
                break
        if target is None:                      # 退而求其次:有交叠的屏幕
            for s in screens:
                if s.geometry().intersects(QRect(x, y, w, h)):
                    target = s
                    break
        if target is None:
            target = QGuiApplication.primaryScreen() or screens[0]

        area = target.availableGeometry()
        w = min(w, area.width())                # 情况 1:尺寸不许超过屏幕
        h = min(h, area.height())
        if not area.contains(cx, cy):           # 中心点不在屏内 → 拉回屏幕左上角附近
            x = area.left() + 40
            y = area.top() + 40
        else:                                   # 至少留出标题栏可抓取的余量
            x = min(max(x, area.left() - w + 160), area.right() - 160)
            y = min(max(y, area.top()), area.bottom() - 40)
        return int(x), int(y), int(w), int(h)

    def _apply_maximized(self):
        if self._config.get("window", "maximized", False):
            self.showMaximized()

    def _save_window_geometry(self):
        """保存"真实"几何:最大化时存还原后的矩形,避免恢复成大窗口。

        写盘前先做 _sane_window_rect 收敛,保证配置里永远不会出现
        超出屏幕尺寸或跑到屏幕外的脏数据。
        """
        cfg = self._config
        if self.isMaximized():
            g = self.normalGeometry()
            x, y, w, h = self._sane_window_rect(g.x(), g.y(), g.width(), g.height())
            cfg.update("window", {
                "x": x, "y": y, "width": w, "height": h, "maximized": True,
            }, save=True)
        else:
            x, y, w, h = self._sane_window_rect(
                self.x(), self.y(), self.width(), self.height())
            cfg.update("window", {
                "x": x, "y": y, "width": w, "height": h, "maximized": False,
            }, save=True)

    def moveEvent(self, e):
        super().moveEvent(e)
        self._mark_geometry_changed()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._mark_geometry_changed()
        self._update_resize_handles()

    def _mark_geometry_changed(self):
        """移动/缩放时只打标记,由防抖定时器统一落盘。

        为什么防抖:move/resize 事件高频触发,每次都同步写 config.json
        在 QtWebEngine 场景下会拖慢甚至干扰窗口初始化的消息处理;
        800ms 内合并为一次写入,关闭时再兜底写一次。
        """
        if self.isMaximized():
            return
        self._geom_dirty = True
        if self._geom_timer is None:
            self._geom_timer = QTimer(self)
            self._geom_timer.setSingleShot(True)
            self._geom_timer.setInterval(800)
            self._geom_timer.timeout.connect(self._flush_geometry)

    def _flush_geometry(self):
        if self._geom_dirty:
            self._geom_dirty = False
            self._save_window_geometry()

    def closeEvent(self, e):
        self._stop_hover_fade()
        self._save_window_geometry()
        self._config.update("window", {"opacity": self.windowOpacity()}, save=False)
        self._config.flush()
        self._hotkeys.unregister_all()
        if self._gamepad is not None:
            self._gamepad.stop()
        for t in self._pad_hold_timers.values():
            t.stop()
        self._log.info("已退出,状态已保存")
        super().closeEvent(e)

    # ---------------- 无边框拖动/缩放 ----------------
    def _install_resize_handles(self):
        """在窗口四边/四角创建透明缩放手柄。"""
        self._resize_handles = {}
        for edge in ("l", "r", "t", "b", "tl", "tr", "bl", "br"):
            h = _ResizeHandle(self, edge)
            h.hide()
            self._resize_handles[edge] = h
        self._update_resize_handles()

    def _update_resize_handles(self):
        """窗口尺寸/最大化状态变化时,重新摆放手柄。"""
        if self.isMaximized():
            for h in self._resize_handles.values():
                h.hide()
            return
        w, h = self.width(), self.height()
        e = _EDGE
        geom = {
            "l": (0, e, e, h - 2 * e),
            "r": (w - e, e, e, h - 2 * e),
            "t": (e, 0, w - 2 * e, e),
            "b": (e, h - e, w - 2 * e, e),
            "tl": (0, 0, e, e),
            "tr": (w - e, 0, e, e),
            "bl": (0, h - e, e, e),
            "br": (w - e, h - e, e, e),
        }
        for edge, (x, y, ww, hh) in geom.items():
            h = self._resize_handles[edge]
            h.setGeometry(x, y, ww, hh)
            h.raise_()
            h.show()

    def _begin_resize(self, edge, global_pos):
        self._resizing = True
        self._resize_edge = edge
        self._resize_native_ok = False
        # 优先:用物理像素记录基准(多屏不同缩放下唯一稳定的坐标系)
        try:
            self._press_rect_native = win32_api.get_window_rect_native(int(self.winId()))
            self._press_cursor_native = win32_api.get_cursor_pos_native()
            dpr = float(self.devicePixelRatioF()) or 1.0
            self._min_native = (int(_MIN_W * dpr), int(_MIN_H * dpr))
            self._resize_native_ok = True
        except Exception:
            self._log.exception("获取原生窗口矩形失败,缩放退回逻辑坐标方案")
        # 兜底:旧的逻辑坐标方案
        self._press_geom = self.geometry()
        self._press_global = global_pos

    def _do_resize(self, global_pos):
        if not (self._resizing and self._resize_edge):
            return
        if self._resize_native_ok:
            try:
                cx, cy = win32_api.get_cursor_pos_native()
                px, py, pw, ph = self._press_rect_native
                dx, dy = cx - self._press_cursor_native[0], cy - self._press_cursor_native[1]
                l, t, r, b = px, py, px + pw, py + ph
                mw, mh = self._min_native
                e = self._resize_edge
                if "l" in e:
                    l = min(r - mw, l + dx)
                if "r" in e:
                    r = max(l + mw, r + dx)
                if "t" in e:
                    t = min(b - mh, t + dy)
                if "b" in e:
                    b = max(t + mh, b + dy)
                win32_api.set_window_rect_native(int(self.winId()), l, t, r - l, b - t)
                return
            except Exception:
                self._resize_native_ok = False
                self._log.exception("原生缩放失败,退回逻辑坐标方案")
        self._apply_resize(global_pos - self._press_global)

    def _end_resize(self):
        self._resizing = False
        self._resize_edge = None
        self._resize_native_ok = False

    def mousePressEvent(self, e):
        # 边缘缩放由 _ResizeHandle 手柄处理;这里只管标题栏拖动
        if e.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            if e.pos().y() < 34:
                self._dragging = True
                # 用物理像素记录"光标相对窗口左上角"的偏移。
                # 绝不能用 e.globalPos()/frameGeometry() 这类逻辑坐标:
                # 两块屏缩放不同时,同一物理位置在逻辑坐标系里的数值会突变,
                # 于是"旧偏移 + 新坐标"算出的落点出错,窗口会在边界反复跳位,
                # 再叠加 DPI 缩放就把尺寸越滚越大(用户反馈的"拖着一直变大")。
                try:
                    cx, cy = win32_api.get_cursor_pos_native()
                    wx, wy, _, _ = win32_api.get_window_rect_native(int(self.winId()))
                    self._drag_offset_native = (cx - wx, cy - wy)
                except Exception:
                    self._drag_offset_native = None
                    self._log.exception("获取原生坐标失败,拖动退回逻辑坐标方案")
                self._drag_offset = e.globalPos() - self.frameGeometry().topLeft()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging:
            if self._drag_offset_native is not None:
                try:
                    cx, cy = win32_api.get_cursor_pos_native()
                    ox, oy = self._drag_offset_native
                    # SWP_NOSIZE:拖动过程绝不改变尺寸
                    win32_api.move_window_native(int(self.winId()), cx - ox, cy - oy)
                    return
                except Exception:
                    self._drag_offset_native = None
                    self._log.exception("原生拖动失败,退回逻辑坐标方案")
            self.move(e.globalPos() - self._drag_offset)
            return
        super().mouseMoveEvent(e)

    def _apply_resize(self, delta):
        g = QRect(self._press_geom)
        dx, dy = delta.x(), delta.y()
        e = self._resize_edge
        if "l" in e:
            g.setLeft(min(g.right() - _MIN_W, g.left() + dx))
        if "r" in e:
            g.setRight(max(g.left() + _MIN_W, g.right() + dx))
        if "t" in e:
            g.setTop(min(g.bottom() - _MIN_H, g.top() + dy))
        if "b" in e:
            g.setBottom(max(g.top() + _MIN_H, g.bottom() + dy))
        self.setGeometry(g)

    def mouseReleaseEvent(self, e):
        self._resizing = False
        self._dragging = False
        self._resize_edge = None
        self._resize_native_ok = False
        self._drag_offset_native = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.pos().y() < 34:
            self._toggle_maximize()
            return
        super().mouseDoubleClickEvent(e)

    # ---------------- 窗口操作 ----------------
    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._save_window_geometry()
        self._refresh_max_btn()

    def _refresh_max_btn(self):
        """最大化状态变化时切换按钮图标(方框 <-> 还原形状)。"""
        try:
            kind = "restore" if self.isMaximized() else "max"
            self._btn_max.setIcon(_glyph_icon(kind))
            self._btn_max.setProperty("glyph", kind)
        except Exception:
            pass

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            self._refresh_max_btn()

    def _toggle_topmost(self):
        self._topmost = not self._topmost
        flags = self.windowFlags()
        if self._topmost:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()  # setWindowFlags 会隐藏窗口,重新显示
        self._apply_rounded_corners()  # 原生窗口被重建了,圆角要补回来
        self._update_pin_ui()
        self._config.set("window", "topmost", self._topmost)

    def _toggle_click_through(self):
        self._click_through = not self._click_through
        ok = win32_api.set_click_through(int(self.winId()), self._click_through)
        if not ok:
            self._status.setText("穿透功能不可用")
            self._click_through = False
            return
        if self._click_through:
            # 沉浸模式:穿透时隐藏导航栏(标题栏+工具栏),
            # 窗口内只留网页,获得最大沉浸视野;再按 0 恢复。
            self._set_ui_immersive(True)
            # 穿透模式:鼠标移到窗口上时才变淡(提示该区域点不到),移开恢复清晰。
            # 用定时器轮询鼠标位置实现(穿透后窗口收不到鼠标事件,无法用事件判断)。
            self._hover_timer = QTimer(self)
            self._hover_timer.setInterval(120)
            self._hover_timer.timeout.connect(self._check_hover_fade)
            self._hover_timer.start()
            self._flash("已穿透:导航栏已隐藏,鼠标移到窗口上会变淡")
        else:
            self._set_ui_immersive(False)
            self._stop_hover_fade()
            self._flash("穿透已关闭,导航栏已恢复")
        self._update_through_ui()
        self._config.set("window", "click_through", self._click_through)

    def _set_ui_immersive(self, immersive):
        """沉浸模式:穿透时隐藏标题栏与工具栏,只保留网页区域。

        注意:**状态栏必须保留**。穿透后窗口不吃鼠标事件(任何按钮都点不到),
        退出只能靠键盘热键,而"按 0 恢复"这条提示只能靠状态栏常驻显示。
        早期版本把状态栏一起隐藏了,于是提示写进了一个看不见的控件 ——
        用户进入穿透后完全不知道该按哪个键出来(实测确认)。
        """
        for w in (self._title_bar, self._toolbar):
            try:
                w.setVisible(not immersive)
            except Exception:
                pass
        if immersive:
            self._show_through_hint()

    def _stop_hover_fade(self):
        if self._hover_timer is not None:
            self._hover_timer.stop()
            self._hover_timer = None
        op = float(self._config.get("window", "opacity", 1.0))
        self.setWindowOpacity(op if op < 1.0 else 1.0)

    def _check_hover_fade(self):
        """穿透开启时:鼠标在窗口内 -> 变淡;移开 -> 恢复清晰。"""
        if not self._click_through or not self.isVisible():
            return
        inside = self.frameGeometry().contains(QCursor.pos())
        target = _THROUGH_HOVER_OPACITY if inside else 1.0
        cur = self.windowOpacity()
        if abs(cur - target) > 0.05:
            self.setWindowOpacity(target)

    # ---------------- 鼠标悬停自动激活(游戏场景 hover 修复) ----------------
    def _start_hover_activate(self):
        """启动光标位置轮询:鼠标移入窗口时自动激活窗口。

        为什么需要:游戏前台时本程序是后台窗口,WebView2(Chromium)在
        未激活窗口里不处理鼠标 hover → 播放器进度条不弹出(实测 mm=0)。
        激活后 hover 恢复正常。鼠标移入说明用户想操作它,自动激活符合直觉;
        点回游戏窗口焦点即回归,不影响游戏。
        """
        if self._hover_activate_timer is None:
            self._hover_activate_timer = QTimer(self)
            self._hover_activate_timer.setInterval(150)
            self._hover_activate_timer.timeout.connect(self._check_hover_activate)
        self._hover_activate_timer.start()

    def _check_hover_activate(self):
        if not self.isVisible() or self.isMinimized():
            return
        if self._click_through:
            # 穿透模式:故意不抢焦点(鼠标要穿过窗口到下层)
            return
        # 关键:有模态对话框(设置窗口)或弹出控件(下拉框/菜单)时绝不抢焦点。
        # 否则 activateWindow() 会打断对话框,造成"下拉框一点就消失、
        # 热键输入框录不进按键"的问题。
        if QApplication.activeModalWidget() is not None:
            return
        if QApplication.activePopupWidget() is not None:
            return
        if self.isActiveWindow():
            return
        # 鼠标是否在窗口范围内(含标题栏区域)
        if self.frameGeometry().contains(QCursor.pos()):
            self.activateWindow()
            self.raise_()

    def toggle_hide(self):
        if self.isVisible():
            # 隐藏时视频也暂停,避免"盲看"错过内容
            self._web.pause()
            self.hide()
            # 隐藏后除 9(显示)外所有热键暂停响应,
            # 防止隐藏状态下误触 ~ 等键控制视频
            self._hotkeys.suspend_all_except({"toggle_hide"})
            self._log.info("已隐藏(热键 9,视频已暂停,其他热键已暂停)")
        else:
            self.show()
            self._hotkeys.resume_all()
            self._log.info("已显示(热键恢复)")

    def _update_pin_ui(self):
        self._btn_pin.setProperty("active", self._topmost)
        self._btn_pin.style().unpolish(self._btn_pin)
        self._btn_pin.style().polish(self._btn_pin)

    def _update_through_ui(self):
        self._btn_through.setProperty("active", self._click_through)
        self._btn_through.style().unpolish(self._btn_through)
        self._btn_through.style().polish(self._btn_through)

    # ---------------- 浏览器联动 ----------------
    def _on_url_entered(self):
        self._web.navigate(self._url_edit.text())

    def _on_url_changed(self, url):
        self._url_edit.setText(url)
        self._url_edit.setCursorPosition(0)

    def _on_js_result(self, result):
        if result.startswith("rate="):
            rate_text = result[5:]
            self._set_rate_label(rate_text)
            # 长按提升的倍速只是临时值,不能当成用户设置的常态倍速存进配置
            if not self._holding_speed:
                try:
                    self._config.set("misc", "playback_rate", float(rate_text))
                except ValueError:
                    pass
        elif result.startswith("vol="):
            self._vol_label.setText("音量 %d%%" % (float(result[4:]) * 100))
            try:
                self._config.set("misc", "volume", float(result[4:]))
            except ValueError:
                pass
        elif result == "no-video":
            self._flash("当前页面没有播放的视频")

    def _flash(self, text, warn=False):
        self._status.setText(text)
        self._status.setProperty("warn", warn)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        QTimer.singleShot(2500, self._reset_status)

    def _reset_status(self):
        self._status.setProperty("warn", False)
        # warn 属性撤销后必须重新 polish,否则粉色高亮会一直留着
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        if self._click_through:
            self._show_through_hint()
        else:
            self._status.setText("就绪")

    def _show_through_hint(self):
        """穿透时在状态栏常驻提示"怎么退出"。

        穿透后窗口不吃鼠标事件,任何按钮都点不到,热键是唯一出口;
        所以这条提示必须一直挂着,而且要用用户自己配置的那个键(可能被改过)。
        """
        key = self._config.get("hotkeys", "toggle_clickthrough", "0") or "0"
        self._status.setText("穿透中 · 按 %s 恢复导航栏" % key)

    # ---------------- 热键 ----------------
    def _bind_hotkeys(self):
        cfg = self._config.get("hotkeys")
        # 默认按键方案:
        #   ~ 播放/暂停、6 快进、5 快退、9 隐藏、0 穿透、Ctrl+Space 最大化
        self._hotkeys.register("toggle_play", cfg.get("toggle_play", "`"),
                               self._web.toggle_play)
        # 5/6 快退/快进:长按连发 —— 按下跳一次,按住定时连发,松开停止
        self._hotkeys.register_hold(
            "seek_forward", cfg.get("seek_forward", "6"),
            self._make_hold_seek(1), self._stop_hold_seek)
        # 快退:长按连发快退(与 B站 一致)
        self._hotkeys.register_hold(
            "seek_backward", cfg.get("seek_backward", "5"),
            self._make_hold_seek(-1), self._stop_hold_seek)
        # 快进:**点按=快进5秒,长按=倍速播放**(合并成一个键,和 B站 长按右方向键一致)。
        # 需要区分"点按"和"长按",所以按下后先等一小段时间,超时未松开才算长按。
        self._hotkeys.register_hold(
            "seek_forward", cfg.get("seek_forward", "6"),
            self._on_seek_fwd_down, self._on_seek_fwd_up)
        self._hotkeys.register("toggle_maximize", cfg.get("toggle_maximize", "ctrl+space"),
                               self._toggle_maximize)
        self._hotkeys.register("toggle_hide", cfg.get("toggle_hide", "9"),
                               self.toggle_hide)
        self._hotkeys.register("toggle_clickthrough", cfg.get("toggle_clickthrough", "0"),
                               self._toggle_click_through)

    def _rebind_hotkeys(self):
        """设置变更后重新注册全部热键。

        注意:这里用 unbind_hotkeys() 而不是 unregister_all() ——
        只换绑定表,不停止钩子线程。旧实现会 stop() 再 start(),
        一旦停止标志没被清除,新线程启动后立即退出,
        表现为"保存设置后键盘热键全部失效"(手柄是独立轮询,不受影响)。
        """
        try:
            self._hotkeys.unbind_hotkeys()
        except Exception:
            self._log.exception("卸载旧热键失败")
        self._bind_hotkeys()
        # 把钩子线程的真实状态写进日志,便于出问题时一眼定位
        self._log.info("热键已重新绑定 %d 项,键盘钩子线程:%s",
                       self._hotkeys.bound_action_count(),
                       "运行中" if self._hotkeys.is_alive() else "未运行(异常!)")
        # 万一线程真的掉了,立刻自愈
        self._hotkeys.ensure_alive()

    # ---------------- 键盘钩子看门狗 ----------------
    def _start_hotkey_watchdog(self):
        """周期自检键盘钩子线程;一旦静默退出就自动重建。

        背景:低级键盘钩子在极端情况下(系统休眠恢复、被安全软件拦截等)
        线程可能退出,而程序仍在正常显示"已注册",表现为
        "手柄好好的,键盘突然全没反应"。这里每 5 秒体检一次兜底。
        """
        if self._hotkey_watchdog is None:
            self._hotkey_watchdog = QTimer(self)
            self._hotkey_watchdog.setInterval(5000)
            self._hotkey_watchdog.timeout.connect(self._check_hotkey_health)
        self._hotkey_watchdog.start()

    def _check_hotkey_health(self):
        try:
            if self._hotkeys.ensure_alive():
                self._flash("键盘钩子曾异常退出,已自动恢复", warn=True)
        except Exception:
            self._log.exception("键盘钩子自检异常")

    # ---------------- 设置 ----------------
    def _open_settings(self):
        dlg = SettingsDialog(
            self._config.get("hotkeys") or {},
            self._config.get("gamepad", "mapping") or {},
            self._config.get("misc") or {},
            parent=self,
        )
        dlg.saved.connect(self._apply_settings)

        # 打开设置期间:
        # 1) 暂停“悬停自动激活”定时器 —— 它每 150ms 抢焦点,会打断下拉框/输入框
        # 2) 暂时挂起全局热键 —— 录制按键时不要把动作也触发了
        if self._hover_activate_timer is not None:
            self._hover_activate_timer.stop()
        try:
            self._hotkeys.suspend_all_except(set())
        except Exception:
            pass
        try:
            dlg.exec()
        finally:
            try:
                self._hotkeys.resume_all()
            except Exception:
                pass
            if self._hover_activate_timer is not None:
                self._hover_activate_timer.start()

    def _apply_settings(self, hotkeys, gamepad_mapping, auto_sound=True):
        """保存设置:写入配置 -> 重载热键 -> 刷新手柄映射 -> 应用声音开关。立即生效。"""
        self._config.update("hotkeys", hotkeys, save=False)
        self._config.update("gamepad", {"mapping": gamepad_mapping}, save=False)
        self._config.set("misc", "auto_sound", bool(auto_sound), save=True)

        self._rebind_hotkeys()
        if self._gamepad is not None:
            self._gamepad.reload_mapping()
        try:
            # 声音开关立即生效:注入的脚本读 window.__iceAutoSound,无需重启
            self._web.set_auto_sound(bool(auto_sound))
        except Exception:
            self._log.exception("应用声音设置失败")

        self._log.info("设置已保存:热键=%s 手柄映射=%s 自动开启声音=%s",
                       hotkeys, gamepad_mapping, auto_sound)
        self._flash("设置已保存并生效")

    # ---------------- 手柄 ----------------
    def _bind_gamepad(self):
        """启动手柄轮询(若配置启用且系统存在 XInput 运行库)。"""
        if not self._config.get("gamepad", "enabled", True):
            self._log.info("手柄支持已在配置中关闭")
            return
        self._gamepad = GamepadManager(self._config, self)
        self._gamepad.action_down.connect(self._on_gamepad_down)
        self._gamepad.action_up.connect(self._on_gamepad_up)
        self._gamepad.connection_changed.connect(self._on_gamepad_connected)
        self._gamepad.start()

    def _on_gamepad_connected(self, connected):
        self._pad_label.setText("手柄 已连接" if connected else "")
        self._flash("手柄已连接,可用按键控制视频" if connected else "手柄已断开")

    def _on_gamepad_down(self, action):
        """手柄按键按下:等价于热键触发;快进/快退支持长按连发。"""
        if action == "toggle_play":
            self._web.toggle_play()
        elif action == "seek_forward":
            self._on_seek_fwd_down()     # 手柄与键盘一致:点按快进 / 长按倍速
        elif action == "seek_backward":
            self._start_pad_seek("seek_backward", -1)
        elif action == "toggle_maximize":
            self._toggle_maximize()
        elif action == "toggle_hide":
            self.toggle_hide()
        elif action == "toggle_clickthrough":
            self._toggle_click_through()

    def _on_gamepad_up(self, action):
        if action == "seek_forward":
            self._on_seek_fwd_up()
        elif action == "seek_backward":
            self._stop_pad_seek(action)

    def _start_pad_seek(self, action, direction):
        """手柄快进/快退:按下先跳一次,按住则 260ms 连发。"""
        step = self._config.get("misc", "seek_step_sec", 5) * direction
        self._web.seek(step)
        timer = self._pad_hold_timers.get(action)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(260)
            timer.timeout.connect(lambda: self._web.seek(step))
            self._pad_hold_timers[action] = timer
        timer.start()

    def _stop_pad_seek(self, action):
        timer = self._pad_hold_timers.get(action)
        if timer is not None:
            timer.stop()

    # ---------------- 快退键长按连发 ----------------
    def _make_hold_seek(self, direction):
        """返回按下回调:立即跳一次 + 启动连发定时器(每 260ms 一跳)。"""
        step = self._config.get("misc", "seek_step_sec", 5) * direction

        def on_down():
            self._web.seek(step)
            if self._hold_timer is None:
                self._hold_timer = QTimer(self)
                self._hold_timer.setInterval(260)
                self._hold_timer.timeout.connect(
                    lambda: self._web.seek(step))
            if not self._hold_timer.isActive():
                self._hold_timer.start()

        return on_down

    def _stop_hold_seek(self):
        if self._hold_timer is not None:
            self._hold_timer.stop()

    # ---------------- 快进键:点按=快进 / 长按=倍速 ----------------
    # 对齐 B站:短按右方向键快进,按住不放则倍速播放。
    # 因此按下后先不动作,等 _TAP_HOLD_MS:期间松开=点按(快进一次),超时仍按住=长按(倍速)。
    _TAP_HOLD_MS = 260

    def _on_seek_fwd_down(self):
        if self._fwd_boosting:          # 已在倍速状态,忽略重复按下
            return
        self._fwd_held = True
        if self._fwd_timer is None:
            self._fwd_timer = QTimer(self)
            self._fwd_timer.setSingleShot(True)
            self._fwd_timer.timeout.connect(self._on_seek_fwd_hold)
        self._fwd_timer.start(self._TAP_HOLD_MS)

    def _on_seek_fwd_up(self):
        held = self._fwd_held
        self._fwd_held = False
        if self._fwd_timer is not None:
            self._fwd_timer.stop()
        if self._fwd_boosting:
            self._exit_speed_boost()
            return
        if held:
            # 阈值内松手 -> 判定点按:快进一次
            self._web.seek(self._config.get("misc", "seek_step_sec", 5))

    def _on_seek_fwd_hold(self):
        """按住超过阈值:进入倍速播放。"""
        if not self._fwd_held or self._fwd_boosting:
            return
        self._fwd_boosting = True
        self._holding_speed = True
        rate = float(self._config.get("misc", "boost_rate", 3.0))
        self._web.hold_speed(rate)
        # 主动刷新标签:不依赖 JS 结果回调(本环境下该回调不可靠,见 _on_js_result)
        self._set_rate_label(rate)
        self._flash("长按倍速 %.1fx(松开恢复)" % rate)
        self._log.info("长按倍速:开始 %.2fx", rate)

    def _exit_speed_boost(self):
        self._fwd_boosting = False
        self._holding_speed = False
        self._web.release_speed()
        self._set_rate_label(float(self._config.get("misc", "playback_rate", 1.0) or 1.0))
        self._log.info("长按倍速:松开,恢复原速")

    def _set_rate_label(self, rate):
        try:
            self._rate_label.setText("倍速 %.1fx" % float(rate))
        except (TypeError, ValueError):
            pass
