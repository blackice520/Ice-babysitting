"""Win32 工具封装:窗口置顶/鼠标穿透/原生拖动缩放 等系统级能力。

- 鼠标穿透:WS_EX_TRANSPARENT | WS_EX_LAYERED(让鼠标事件穿过窗口打到游戏)
- 置顶:优先走 Qt WindowStaysOnTopHint,这里提供 Win32 兜底方案
- 原生拖动/缩放:用【物理像素】做运算,解决多屏不同缩放(如 125%/150%)时
  拖动窗口"越拖越大"的问题。原因见下面 get_cursor_pos_native 的注释。
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
GWL_EXSTYLE = -20

# ---- SetWindowPos ----
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL


def get_cursor_pos_native():
    """鼠标位置,单位=【物理像素】(虚拟桌面全局坐标,不随屏幕缩放变化)。

    为什么必须用物理像素:
      QMouseEvent.globalPos() / QWidget.pos() 是"逻辑像素",而每块屏幕的
      缩放比可以不同(如主屏 125%、副屏 150%)。窗口跨越两块屏时,同一个
      物理位置在逻辑坐标系里的数值会突变 —— 用"按下时的旧偏移 + 新鼠标逻辑
      坐标"去 move(),算出来的落点必错,窗口会跳动;再叠加 Qt/Windows 为
      保持物理尺寸而做的 DPI 缩放,就形成正反馈:每翻一次屏,尺寸乘一次
      缩放比,表现为"拖着拖着窗口一直变大"。
      物理像素在整个虚拟桌面上是统一、连续、稳定的,所以用它做拖动运算。
    """
    p = POINT()
    if not user32.GetCursorPos(ctypes.byref(p)):
        raise OSError("GetCursorPos 失败")
    return int(p.x), int(p.y)


def get_window_rect_native(hwnd):
    """窗口矩形 (x, y, w, h),单位=【物理像素】。"""
    r = RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
        raise OSError("GetWindowRect 失败")
    return int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)


def move_window_native(hwnd, x, y):
    """只改位置不改尺寸地移动窗口(物理像素)。SWP_NOSIZE 保证拖动不会有任何尺寸变化。"""
    return bool(user32.SetWindowPos(wintypes.HWND(hwnd), None, int(x), int(y),
                                    0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE))


def set_window_rect_native(hwnd, x, y, w, h):
    """按物理像素设置窗口位置与尺寸(缩放用)。"""
    return bool(user32.SetWindowPos(wintypes.HWND(hwnd), None, int(x), int(y),
                                    int(w), int(h), SWP_NOZORDER | SWP_NOACTIVATE))


def _get_ex_style(hwnd):
    return user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)


def set_click_through(hwnd, enabled):
    """开启后鼠标事件直接穿透本窗口(用于"边打游戏边看攻略、不想挡住操作")。"""
    if not hwnd:
        return False
    style = _get_ex_style(hwnd)
    if enabled:
        style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
    else:
        style &= ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, style)
    return True


def is_click_through(hwnd):
    if not hwnd:
        return False
    return bool(_get_ex_style(hwnd) & WS_EX_TRANSPARENT)


# ---- DWM 窗口圆角(Win11 build 22000+) ----
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3


def set_rounded_corners(hwnd, small=False):
    """让窗口获得 Win11 的原生圆角(带抗锯齿),返回是否成功。

    为什么必须用 DWM 而不是在 QSS 里写 border-radius:
      本程序是无边框窗口(WS_POPUP),而网页区是 WebView2 的**独立原生子窗口**。
      Qt 自己画的 border-radius 只能圆到 Qt 绘制的那部分,WebView2 那块
      方角会硬生生露在圆弧外面;DWM 是在系统合成器层面裁整个窗口的,
      子窗口也会一起被裁圆,所以只有这条路能真正把整窗做圆。
    Win10 及更早系统不支持该属性,返回 False,界面退化为直角,功能不受影响。
    """
    if not hwnd:
        return False
    try:
        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        pref = ctypes.c_int(DWMWCP_ROUNDSMALL if small else DWMWCP_ROUND)
        hr = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(pref), ctypes.sizeof(pref))
        return hr == 0
    except Exception:
        return False
