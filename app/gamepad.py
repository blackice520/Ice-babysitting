"""手柄支持 —— XInput 轮询。

背景:全局热键用的是键盘钩子(WH_KEYBOARD_LL),它只能"看见"键盘按键。
手柄按键属于 HID / XInput 信号,键盘钩子收不到,所以默认无法用手柄控制。

本模块用 Windows XInput API 主动轮询手柄按键,把按键映射到与热键相同的
动作(播放/暂停、快进快退、隐藏、穿透),从而让手柄(含掌机)能控制视频。

关于"手柄背键"(掌机/精英手柄背面的 M1/M2 或 P1-P4 拨片):
  XInput 标准只暴露 A/B/X/Y/LB/RB/Start/Back/十字键/摇杆/扳机,
  **背键不是标准 XInput 按键**——它由设备厂商的配套软件映射:
    · Steam Deck / Steam Input、ROG Armoury Crate、Legion Space、
      掌机助手(Handheld Companion)、reWASD、Xbox Accessories 等
  注意:北通 PC 端软件(北通智控软件 / 手柄助手)的按键重映射**只支持
  “手柄键 → 手柄键”,不提供“手柄键 → 键盘键”**(键鼠映射是留给手游映射
  与“键鼠转换器”硬件的功能)。因此要用手柄背键控制播放/暂停,有两条路:
    方案 A(零额外软件):把背键映射成标准手柄键(推荐 Back / 视图),
        即可被本模块轮询识别 —— 在“设置 → 手柄按键映射”里把对应动作
        绑到该标准键即可。代价:游戏里也会触发这个标准键。
    方案 B(无游戏内冲突):把背键映射成标准手柄键,再用第三方键盘映射
        工具(AntiMicroX / JoyToKey 等)把该标准键转成键盘键(如 ` )。
        本程序的键盘钩子(WH_KEYBOARD_LL)不过滤模拟输入,能正常收到,
        而游戏看不到这个键盘键,等于背键变成了热键。
"""
import ctypes
from ctypes import wintypes

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .logger import get_logger

# ---- XInput 按键位掩码 ----
BTN = {
    "dpad_up": 0x0001, "dpad_down": 0x0002, "dpad_left": 0x0004, "dpad_right": 0x0008,
    "start": 0x0010, "back": 0x0020,
    "left_thumb": 0x0040, "right_thumb": 0x0080,
    "lb": 0x0100, "rb": 0x0200,
    "a": 0x1000, "b": 0x2000, "x": 0x4000, "y": 0x8000,
}

# 中文显示名(设置界面用)
BTN_LABELS = {
    "dpad_up": "十字键上", "dpad_down": "十字键下", "dpad_left": "十字键左", "dpad_right": "十字键右",
    "start": "Start / 菜单", "back": "Back / 视图",
    "left_thumb": "左摇杆按下", "right_thumb": "右摇杆按下",
    "lb": "LB / L1 / 左肩键", "rb": "RB / R1 / 右肩键",
    "a": "A / ×", "b": "B / ○", "x": "X / □", "y": "Y / △",
}

ERROR_DEVICE_NOT_CONNECTED = 1167
ERROR_SUCCESS = 0

# 默认映射:动作 -> 手柄按键
DEFAULT_GAMEPAD_MAP = {
    "toggle_play": "a",
    "seek_forward": "rb",
    "seek_backward": "lb",
    "toggle_hide": "start",
    "toggle_clickthrough": "y",
}


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", wintypes.DWORD),
        ("Gamepad", XINPUT_GAMEPAD),
    ]


_lib_cache = None


def _load_xinput():
    """按优先级加载 XInput 动态库(不同 Windows 版本提供的名字不同)。"""
    for name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
        try:
            lib = ctypes.windll.LoadLibrary(name)
        except OSError:
            continue
        try:
            lib.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
            lib.XInputGetState.restype = wintypes.DWORD
            return lib
        except AttributeError:
            continue
    return None


class GamepadManager(QObject):
    """轮询手柄按键,`按下/松开` 时发出动作名信号(与热键动作同名)。

    用法:
        gm = GamepadManager(config)
        gm.action_down.connect(on_down)   # 参数:动作名
        gm.action_up.connect(on_up)
        gm.start()
    """

    action_down = pyqtSignal(str)
    action_up = pyqtSignal(str)
    connection_changed = pyqtSignal(bool)

    POLL_MS = 16  # ~60Hz

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._log = get_logger()
        self._config = config
        self._lib = _load_xinput()
        self._map = {}          # 按钮名 -> 动作名
        self._prev_buttons = 0
        self._connected = False
        self._slot = -1
        self._timer = None

    # ---------------- 生命周期 ----------------
    def start(self):
        if self._lib is None:
            self._log.info("未找到 XInput 运行库,手柄支持不可用")
            return False
        self.reload_mapping()
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(self.POLL_MS)
            self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._log.info("手柄轮询已启动(映射: %s)", self._map)
        return True

    def stop(self):
        if self._timer is not None:
            self._timer.stop()
        self._prev_buttons = 0

    def reload_mapping(self):
        """从配置重新读取“手柄按键 -> 动作”的映射。"""
        cfg = self._config.get("gamepad") or {}
        mapping = cfg.get("mapping") if isinstance(cfg.get("mapping"), dict) else None
        if mapping is None:
            mapping = dict(DEFAULT_GAMEPAD_MAP)
        # 反转为 按钮名 -> 动作(只保留合法按钮名)
        self._map = {}
        for action, btn in mapping.items():
            if btn in BTN:
                self._map[btn] = action

    # ---------------- 轮询 ----------------
    def _read_buttons(self):
        """返回 (是否连接, 按键掩码)。"""
        if self._lib is None:
            return False, 0
        state = XINPUT_STATE()
        # 优先沿用上次成功的槽位,否则遍历 0..3
        slots = [self._slot] if self._slot >= 0 else []
        slots += [i for i in range(4) if i != self._slot]
        for i in slots:
            if i < 0:
                continue
            try:
                ret = self._lib.XInputGetState(i, ctypes.byref(state))
            except Exception:
                continue
            if ret == ERROR_SUCCESS:
                self._slot = i
                return True, int(state.Gamepad.wButtons)
        return False, 0

    def _poll(self):
        connected, buttons = self._read_buttons()

        if connected != self._connected:
            self._connected = connected
            self._log.info("手柄%s", "已连接" if connected else "已断开")
            try:
                self.connection_changed.emit(connected)
            except Exception:
                pass

        if not connected:
            self._prev_buttons = 0
            return

        changed = buttons ^ self._prev_buttons
        if not changed:
            self._prev_buttons = buttons
            return

        for name, mask in BTN.items():
            if not (changed & mask):
                continue
            action = self._map.get(name)
            if not action:
                continue
            pressed = bool(buttons & mask)
            try:
                if pressed:
                    self.action_down.emit(action)
                else:
                    self.action_up.emit(action)
            except Exception:
                self._log.exception("手柄事件处理失败: %s", action)

        self._prev_buttons = buttons


# ---------------- 供“检测界面”使用的无状态辅助函数 ----------------
def _get_lib():
    global _lib_cache
    if _lib_cache is None:
        _lib_cache = _load_xinput()
    return _lib_cache


def poll_buttons():
    """读取当前手柄按键:返回 (是否连接, 按键位掩码)。用于设置界面的实时检测。"""
    lib = _get_lib()
    if lib is None:
        return False, 0
    state = XINPUT_STATE()
    for i in range(4):
        try:
            if lib.XInputGetState(i, ctypes.byref(state)) == ERROR_SUCCESS:
                return True, int(state.Gamepad.wButtons)
        except Exception:
            continue
    return False, 0


def buttons_to_names(mask):
    """把按键掩码转成中文名列表。"""
    return [BTN_LABELS.get(name, name) for name, m in BTN.items() if mask & m]

