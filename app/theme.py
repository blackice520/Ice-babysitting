"""浅色主题 —— 白底 + 圆角,干净清爽。

配色体系:
  背景层   #FFFFFF (纯白)   #F7F8FA (浅灰面板)
  描边     #E5E8EC (浅灰)   #D7DCE2 (深一档)
  强调色   #2F6FEB (蓝)     rgba(47,111,235,·) 各种浅色底
  危险色   #E5484D (红,仅关闭/告警)
  文字     #1F2328 (主)  #6E7781 (次)  #9AA4AE (弱)

圆角分两层:
  1. 窗口外框圆角 —— 由 Win11 的 DWM 原生圆角负责(见 utils/win32_api.set_rounded_corners),
     这是唯一能同时把 WebView2 原生子窗口一起裁圆的做法。
  2. 内部控件圆角 —— 由下面的 QSS border-radius 负责。
"""
from PyQt6.QtGui import QColor

# ---- 颜色常量 ----
BG_TOP = QColor("#FFFFFF")
BG_BOTTOM = QColor("#F7F8FA")
PANEL = QColor("#FFFFFF")
PANEL_DARK = QColor("#F7F8FA")
BORDER = QColor("#E5E8EC")

ACCENT = QColor("#2F6FEB")
ACCENT_DARK = QColor("#1F5AD0")
TEXT_MAIN = QColor("#1F2328")
TEXT_DIM = QColor("#6E7781")
TEXT_FAINT = QColor("#9AA4AE")
DANGER = QColor("#E5484D")

# ---- 控件圆角 ----
RADIUS = 6          # 按钮/输入框
RADIUS_PANEL = 8    # 面板/提示块

_MAIN_QSS = """
* {
    font-family: "Microsoft YaHei";
    outline: none;
}

QMainWindow, QWidget#Root {
    background-color: #FFFFFF;
    color: #1F2328;
}

/* ---------- 标题栏 ---------- */
QWidget#TitleBar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #E5E8EC;
}
QLabel#TitleText {
    color: #2F6FEB;
    font-size: 12px;
    font-weight: bold;
    letter-spacing: 1px;
}
/* 文字按钮:置顶 / 穿透 / 设置 —— 字号收小,并留出透明边框以便"常亮"态尺寸不跳 */
QPushButton#TitleBtn {
    background: transparent;
    border: 1px solid transparent;
    color: #6E7781;
    font-size: 12px;
    font-weight: normal;
    min-height: 24px;
    padding: 0 9px;
    border-radius: 6px;
}
QPushButton#TitleBtn:hover {
    background: rgba(47, 111, 235, 0.10);
    color: #2F6FEB;
}
QPushButton#TitleBtn:pressed {
    background: rgba(47, 111, 235, 0.20);
}
/* "常亮":置顶 / 穿透 处于开启状态时,按钮保持高亮,一眼可辨 */
QPushButton#TitleBtn[active="true"] {
    background: rgba(47, 111, 235, 0.12);
    border-color: #2F6FEB;
    color: #2F6FEB;
    font-weight: bold;
}
/* 窗口按钮:最小化 / 最大化 / 关闭 —— 用 min/max 钳成同一个方块,
   否则 —/□/✕ 三个字形宽度不同,按钮会一个大一个小 */
/* 图标由矢量绘制(见 main_window._glyph_icon),这里只管按钮的方块尺寸 */
QPushButton#TitleBtnWin, QPushButton#TitleBtnClose {
    background: transparent;
    border: none;
    min-width: 34px;
    max-width: 34px;
    min-height: 26px;
    max-height: 26px;
    padding: 0;
    border-radius: 6px;
}
QPushButton#TitleBtnWin:hover, QPushButton#TitleBtnClose:hover {
    background: rgba(47, 111, 235, 0.10);
    color: #2F6FEB;
}
QPushButton#TitleBtnWin:pressed, QPushButton#TitleBtnClose:pressed {
    background: rgba(47, 111, 235, 0.20);
}
QPushButton#TitleBtnClose:hover {
    background: #E5484D;
    color: #FFFFFF;
}

/* ---------- 工具栏 ---------- */
QWidget#ToolBar {
    background-color: #F7F8FA;
    border-bottom: 1px solid #E5E8EC;
}
QPushButton#ToolBtn {
    background: #FFFFFF;
    border: 1px solid #E5E8EC;
    color: #6E7781;
    font-size: 12px;
    min-width: 28px;
    min-height: 22px;
    border-radius: 6px;
}
QPushButton#ToolBtn:hover {
    border-color: #2F6FEB;
    color: #2F6FEB;
    background: rgba(47, 111, 235, 0.07);
}
QPushButton#ToolBtn:pressed {
    background: rgba(47, 111, 235, 0.16);
}
QLineEdit#UrlEdit {
    background: #FFFFFF;
    border: 1px solid #E5E8EC;
    border-radius: 6px;
    padding: 4px 10px;
    color: #1F2328;
    font-size: 12px;
    selection-background-color: #2F6FEB;
    selection-color: #FFFFFF;
}
QLineEdit#UrlEdit:focus {
    border-color: #2F6FEB;
}

/* ---------- 状态栏 ---------- */
QWidget#StatusBar {
    background-color: #F7F8FA;
    border-top: 1px solid #E5E8EC;
}
QLabel#StatusText {
    color: #6E7781;
    font-size: 11px;
}
QLabel#StatusText[accent="true"] {
    color: #2F6FEB;
}
QLabel#StatusText[warn="true"] {
    color: #E5484D;
}

/* ---------- 滑块(透明度/音量) ---------- */
QSlider#MiniSlider::groove:horizontal {
    height: 3px;
    background: #E5E8EC;
    border-radius: 1px;
}
QSlider#MiniSlider::handle:horizontal {
    width: 10px;
    margin: -4px 0;
    border-radius: 5px;
    background: #2F6FEB;
    border: 1px solid #2F6FEB;
}
QSlider#MiniSlider::sub-page:horizontal {
    background: #2F6FEB;
    border-radius: 1px;
}

/* ---------- 菜单 ---------- */
QMenu {
    background-color: #FFFFFF;
    color: #1F2328;
    border: 1px solid #E5E8EC;
    border-radius: 8px;
    padding: 4px;
}
QMenu::item {
    padding: 5px 18px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: rgba(47, 111, 235, 0.12);
    color: #2F6FEB;
}
QMenu::separator {
    height: 1px;
    background: #E5E8EC;
    margin: 4px 8px;
}

QToolTip {
    background-color: #FFFFFF;
    color: #1F2328;
    border: 1px solid #2F6FEB;
    border-radius: 6px;
    padding: 4px 8px;
}

/* ---------- 设置对话框 ---------- */
QDialog {
    background-color: #FFFFFF;
}
QLabel#DlgSection {
    color: #2F6FEB;
    font-size: 12px;
    font-weight: bold;
    letter-spacing: 1px;
}
QLabel#DlgLabel {
    color: #3A4149;
    font-size: 12px;
}
QLabel#DlgHint {
    color: #6E7781;
    font-size: 11px;
    background: #F7F8FA;
    border: 1px solid #E5E8EC;
    border-radius: 8px;
    padding: 8px 10px;
}
QFrame#DlgDivider {
    color: #E5E8EC;
    background: #E5E8EC;
    max-height: 1px;
}
QLabel#DlgDetect {
    color: #2F6FEB;
    font-size: 12px;
    background: #F7F8FA;
    border: 1px solid #E5E8EC;
    border-radius: 6px;
    padding: 5px 10px;
}
QLineEdit#HotkeyEdit {
    background: #FFFFFF;
    border: 1px solid #E5E8EC;
    border-radius: 6px;
    padding: 4px 10px;
    color: #1F2328;
    font-size: 12px;
}
QLineEdit#HotkeyEdit:focus {
    border-color: #2F6FEB;
    color: #2F6FEB;
}
QComboBox#PadCombo {
    background: #FFFFFF;
    border: 1px solid #E5E8EC;
    border-radius: 6px;
    padding: 4px 10px;
    color: #1F2328;
    font-size: 12px;
}
QComboBox#PadCombo:hover {
    border-color: #2F6FEB;
}
QComboBox#PadCombo::drop-down {
    border: none;
    width: 18px;
}
QComboBox#PadCombo QAbstractItemView {
    background: #FFFFFF;
    color: #1F2328;
    border: 1px solid #E5E8EC;
    selection-background-color: rgba(47, 111, 235, 0.14);
    selection-color: #2F6FEB;
}
QPushButton#DlgBtnGhost {
    background: #FFFFFF;
    border: 1px solid #E5E8EC;
    border-radius: 6px;
    color: #6E7781;
    font-size: 12px;
    padding: 6px 16px;
}
QPushButton#DlgBtnGhost:hover {
    border-color: #2F6FEB;
    color: #2F6FEB;
}
QPushButton#DlgBtnPrimary {
    background: #2F6FEB;
    border: 1px solid #2F6FEB;
    border-radius: 6px;
    color: #FFFFFF;
    font-size: 12px;
    font-weight: bold;
    padding: 6px 18px;
}
QPushButton#DlgBtnPrimary:hover {
    background: #1F5AD0;
    border-color: #1F5AD0;
}

/* ---------- 复选框(播放选项) ---------- */
/* 不写任何 QCheckBox 规则:一旦给控件设了样式,Qt 就改用 QSS 引擎画指示器,
   勾选态会变成"实心色块"而丢掉对勾。交给系统样式绘制,勾选态最清晰。 */
"""


def apply_theme(app):
    app.setStyleSheet(_MAIN_QSS)
