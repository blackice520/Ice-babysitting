"""设置对话框 —— 图形化修改全局热键 + 手柄按键映射。

功能:
1. 热键可切换:点击输入框后直接按键盘组合键即完成录制("`"、"ctrl+space"、"f8" 等)
2. 手柄按键映射:下拉选择 手柄按键 -> 动作(含“不绑定”)
3. 恢复默认 / 保存

保存后由 MainWindow 重新注册热键并刷新手柄映射,立即生效。
"""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout,
)

from .gamepad import BTN, BTN_LABELS, DEFAULT_GAMEPAD_MAP, poll_buttons, buttons_to_names
from .hotkey_manager import parse_hotkey

# 动作中文名
ACTION_LABELS = {
    "toggle_play": "播放 / 暂停",
    "seek_forward": "快进 5 秒（长按倍速）",
    "seek_backward": "快退 5 秒",
    "toggle_maximize": "最大化 / 还原",
    "toggle_hide": "隐藏 / 显示窗口",
    "toggle_clickthrough": "鼠标穿透模式",
}

DEFAULT_HOTKEYS = {
    "toggle_play": "`",
    "seek_forward": "6",
    "seek_backward": "5",
    "toggle_maximize": "ctrl+space",
    "toggle_hide": "9",
    "toggle_clickthrough": "0",
}

# 允许绑定手柄的动作(顺序即显示顺序)
GAMEPAD_ACTIONS = [
    "toggle_play", "seek_forward", "seek_backward",
    "toggle_hide", "toggle_clickthrough",
]

# ---- Qt 键 -> 本项目热键字符串 ----
_QT_KEY_NAMES = {
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Escape: "esc",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_QuoteLeft: "`",
    Qt.Key.Key_Minus: "-",
    Qt.Key.Key_Equal: "=",
    Qt.Key.Key_BracketLeft: "[",
    Qt.Key.Key_BracketRight: "]",
    Qt.Key.Key_Semicolon: ";",
    Qt.Key.Key_Apostrophe: "'",
    Qt.Key.Key_Comma: ",",
    Qt.Key.Key_Period: ".",
    Qt.Key.Key_Slash: "/",
    Qt.Key.Key_Backslash: "\\",
}
for _i in range(1, 13):
    _QT_KEY_NAMES[getattr(Qt.Key, f"Key_F{_i}")] = f"f{_i}"

# 纯修饰键(Qt 键值 -> 名称),按下这些键时等待真正的“主键”
_QT_MOD_KEYS = {
    Qt.Key.Key_Control: "ctrl",
    Qt.Key.Key_Shift: "shift",
    Qt.Key.Key_Alt: "alt",
    Qt.Key.Key_Meta: "win",
}


def qt_event_to_hotkey(event):
    """把一次 QKeyEvent 转成热键字符串,失败返回 None(例如只按了修饰键)。"""
    key = event.key()
    if key in _QT_MOD_KEYS:
        return None  # 只按了修饰键,继续等主键

    # 主键名
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        main = chr(key).lower()
    elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        main = chr(key)
    else:
        main = _QT_KEY_NAMES.get(key)
    if not main:
        return None

    mods = event.modifiers()
    parts = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        parts.append("ctrl")
    if mods & Qt.KeyboardModifier.AltModifier:
        parts.append("alt")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        parts.append("shift")
    if mods & Qt.KeyboardModifier.MetaModifier:
        parts.append("win")
    parts.append(main)
    return "+".join(parts)


class HotkeyEdit(QLineEdit):
    """点击后按下键盘组合键即录制的输入框。"""

    def __init__(self, text=""):
        super().__init__(text)
        self.setReadOnly(True)
        self.setPlaceholderText("点击后按下按键组合…")
        self.setToolTip("点击此框,然后直接按下你想绑定的按键(如 `、ctrl+space、f8)")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.clearFocus()
            return
        text = qt_event_to_hotkey(event)
        if text:
            self.setText(text)
            self.clearFocus()
        # 其它情况(只按修饰键)忽略,等待主键


class SettingsDialog(QDialog):
    """设置对话框。保存时通过 `saved` 信号通知主窗口重新应用。"""

    saved = pyqtSignal(dict, dict, bool)  # (hotkeys, gamepad_mapping, auto_sound)

    def __init__(self, hotkeys_cfg, gamepad_cfg, misc_cfg=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ICE-Babysitting · 设置")
        self.setModal(True)
        # 主窗口是“始终置顶”的;对话框也要置顶,否则会被压在后面,
        # 而且下拉框弹出层也可能被主窗口盖住。
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(430)
        self._hotkey_edits = {}
        self._pad_combos = {}
        self._auto_sound_default = bool((misc_cfg or {}).get("auto_sound", True))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        # ---------- 热键区 ----------
        layout.addWidget(self._section_title("全局热键(点击输入框后直接按键录制)"))
        hk_grid = QGridLayout()
        hk_grid.setHorizontalSpacing(10)
        hk_grid.setVerticalSpacing(8)
        hk_grid.setColumnStretch(1, 1)
        for row, action in enumerate(ACTION_LABELS):
            label = QLabel(ACTION_LABELS[action])
            label.setObjectName("DlgLabel")
            edit = HotkeyEdit(str(hotkeys_cfg.get(action, DEFAULT_HOTKEYS.get(action, ""))))
            edit.setObjectName("HotkeyEdit")
            self._hotkey_edits[action] = edit
            hk_grid.addWidget(label, row, 0)
            hk_grid.addWidget(edit, row, 1)
        layout.addLayout(hk_grid)

        layout.addWidget(self._divider())

        # ---------- 手柄区 ----------
        layout.addWidget(self._section_title(
            "手柄按键映射(背键请先用设备软件映射成标准键,详见说明)"))
        pad_grid = QGridLayout()
        pad_grid.setHorizontalSpacing(10)
        pad_grid.setVerticalSpacing(8)
        pad_grid.setColumnStretch(1, 1)
        for row, action in enumerate(GAMEPAD_ACTIONS):
            label = QLabel(ACTION_LABELS[action])
            label.setObjectName("DlgLabel")
            combo = QComboBox()
            combo.setObjectName("PadCombo")
            combo.addItem("不绑定", "")
            for name in BTN:
                combo.addItem(BTN_LABELS.get(name, name), name)
            current = str(gamepad_cfg.get(action, "")) if gamepad_cfg else ""
            idx = combo.findData(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._pad_combos[action] = combo
            pad_grid.addWidget(label, row, 0)
            pad_grid.addWidget(combo, row, 1)
        layout.addLayout(pad_grid)

        layout.addWidget(self._divider())

        # ---------- 播放选项 ----------
        layout.addWidget(self._section_title("播放选项"))
        self._chk_auto_sound = QCheckBox("打开网页视频时自动开启声音")
        self._chk_auto_sound.setObjectName("DlgCheck")
        self._chk_auto_sound.setChecked(self._auto_sound_default)
        self._chk_auto_sound.setToolTip(
            "浏览器内核会强制静音「自动播放」的视频,所以每次进视频页默认都是静音的。\n"
            "勾选:视频一开始播放就自动恢复声音(每个视频只处理一次,之后你手动静音不会被改回)。\n"
            "取消:保持网页原本的静音状态。\n"
            "改完点“保存并应用”即时生效,不用重启。")
        layout.addWidget(self._chk_auto_sound)

        hint = QLabel(
            "⚠ 两点前提:\n"
            "① 手柄按键会被「游戏」和本程序同时收到 —— 本程序只“读取”手柄、无法拦截,\n"
            "   所以用标准手柄键(如 Back/LB/A)在游戏里也会触发对应功能。\n"
            "② PC 端北通软件(智控软件 / 手柄助手)的背键 M1/M2 只能重映射成【手柄按键】,\n"
            "   不支持映射成【键盘键】。\n"
            "因此用背键控制播放/暂停的两条路:\n"
            "· 省事:把 M1 映射成 Back,在上方“手柄按键映射”里把「播放 / 暂停」选成 Back。\n"
            "  (代价:游戏里按背键也会触发 Back 的功能)\n"
            "· 零冲突:把 M1 映射成 Back,再用 AntiMicroX / JoyToKey 等免费工具\n"
            "  把 Back 转成键盘键 ` ,这里“全局热键”保持默认 ` 即可 —— 游戏看不到键盘键。")
        hint.setObjectName("DlgHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # ---------- 手柄实时检测 ----------
        detect_row = QHBoxLayout()
        detect_row.setSpacing(10)
        dlabel = QLabel("手柄实时检测")
        dlabel.setObjectName("DlgLabel")
        self._detect_label = QLabel("等待手柄…")
        self._detect_label.setObjectName("DlgDetect")
        detect_row.addWidget(dlabel)
        detect_row.addWidget(self._detect_label, 1)
        layout.addLayout(detect_row)

        self._detect_timer = QTimer(self)
        self._detect_timer.setInterval(80)
        self._detect_timer.timeout.connect(self._poll_gamepad)
        self._detect_timer.start()

        layout.addWidget(self._divider())

        # ---------- 按钮区 ----------
        btns = QHBoxLayout()
        restore = QPushButton("恢复默认")
        restore.setObjectName("DlgBtnGhost")
        restore.clicked.connect(self._restore_defaults)
        cancel = QPushButton("取消")
        cancel.setObjectName("DlgBtnGhost")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存并应用")
        save.setObjectName("DlgBtnPrimary")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        btns.addWidget(restore)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(save)
        layout.addLayout(btns)

    # ---------------- 小工具 ----------------
    @staticmethod
    def _section_title(text):
        lbl = QLabel(text)
        lbl.setObjectName("DlgSection")
        return lbl

    @staticmethod
    def _divider():
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("DlgDivider")
        return line

    def _restore_defaults(self):
        for action, edit in self._hotkey_edits.items():
            edit.setText(DEFAULT_HOTKEYS.get(action, ""))
        for action, combo in self._pad_combos.items():
            idx = combo.findData(DEFAULT_GAMEPAD_MAP.get(action, ""))
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._chk_auto_sound.setChecked(True)

    def _poll_gamepad(self):
        """实时显示当前按下的手柄按键,便于确认背键映射后发出的是什么信号。"""
        try:
            connected, mask = poll_buttons()
        except Exception:
            connected, mask = False, 0
        if not connected:
            self._detect_label.setText("未连接手柄")
            return
        names = buttons_to_names(mask)
        if names:
            self._detect_label.setText("已连接 · 当前按下:" + " + ".join(names))
        else:
            self._detect_label.setText("已连接 · 按下手柄任意键查看")

    def done(self, code):
        if getattr(self, "_detect_timer", None) is not None:
            self._detect_timer.stop()
        super().done(code)

    # ---------------- 保存 ----------------
    def _on_save(self):
        hotkeys = {}
        seen = {}
        for action, edit in self._hotkey_edits.items():
            text = edit.text().strip()
            if not text:
                self._warn(f"“{ACTION_LABELS[action]}”还没有设置按键。")
                return
            try:
                parse_hotkey(text)
            except ValueError as e:
                self._warn(f"“{ACTION_LABELS[action]}”的按键无效:{e}")
                return
            norm = text.lower()
            if norm in seen:
                self._warn(f"按键冲突:“{text}”同时绑定了"
                           f"“{ACTION_LABELS[seen[norm]]}”和“{ACTION_LABELS[action]}”。")
                return
            seen[norm] = action
            hotkeys[action] = text

        mapping = {}
        used_btn = {}
        for action, combo in self._pad_combos.items():
            btn = combo.currentData()
            if not btn:
                continue
            if btn in used_btn:
                self._warn(f"手柄按键冲突:“{BTN_LABELS.get(btn, btn)}”同时绑定了"
                           f"“{ACTION_LABELS[used_btn[btn]]}”和“{ACTION_LABELS[action]}”。")
                return
            used_btn[btn] = action
            mapping[action] = btn

        self.saved.emit(hotkeys, mapping, bool(self._chk_auto_sound.isChecked()))
        self.accept()

    def _warn(self, text):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "设置提示", text)
