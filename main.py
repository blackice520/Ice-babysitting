"""ICE-Babysitting 入口。

启动流程:
1. 初始化日志 / 配置(自动恢复上次状态)
2. 创建主窗口(自动加载上次网址,带登录态)
3. 注册全局热键
4. 进入事件循环
"""
import os
import sys


def _install_crash_hook():
    """早期崩溃捕获:打包版 exe 崩溃时把信息写到 exe 目录 crash.log。

    覆盖两类问题:
    - C 层崩溃/abort(faulthandler 抓栈)
    - Python 异常(sysexcepthook 写 traceback)
    """
    try:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.getcwd()
        crash_log = os.path.join(base, "crash.log")

        import faulthandler
        faulthandler.enable(file=open(crash_log, "w"))

        def _hook(tp, val, tb):
            import traceback
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(tp, val, tb)))

        sys.excepthook = _hook
    except Exception:
        pass


_install_crash_hook()


def _setup_qt_env():
    """Qt 高 DPI 设置(WebView2 不需要 QtWebEngine 的兼容 flags)。"""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")


def _acquire_single_instance():
    """单实例保护:防止同时打开两个实例。

    为什么必须做(实测踩坑):
      1) 两个实例各自安装键盘钩子/轮询手柄,同一个按键会被响应两次 ——
         播放/暂停互相抵消,表现就是"按了没反应";
      2) 两个实例各自在内存里缓存一份配置,后保存的会把先保存的覆盖掉,
         表现就是"我设置好的按键,重开又回到默认值"。

    用命名互斥体(Local\\ 会话级)判断;创建失败时放行,不影响正常使用。
    返回 (mutex_handle, 是否独占)。
    """
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.GetLastError.restype = wintypes.DWORD
        handle = kernel32.CreateMutexW(None, False, "Local\\ICEBabysitting_SingleInstance")
        if not handle:
            return None, True  # 无法创建就放行,不让用户被挡在门外
        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return handle, False
        return handle, True
    except Exception:
        return None, True


def main():
    _setup_qt_env()

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QMessageBox

    # Qt6 默认启用高 DPI(无需 AA_EnableHighDpiScaling)

    from app.config import Config
    from app.hotkey_manager import HotkeyManager
    from app.logger import setup_logger
    from app.main_window import MainWindow
    from app import APP_NAME, ICON_PATH, theme

    log = setup_logger()
    config = Config()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    # 任务栏/窗口图标(打包后资源在 _internal/assets 下,见 app.asset_path)
    try:
        app.setWindowIcon(QIcon(ICON_PATH))
    except Exception:
        pass
    app.setQuitOnLastWindowClosed(True)

    theme.apply_theme(app)

    # 单实例检查:必须在 QApplication 之后(要用 QMessageBox 提示用户)
    _mutex, is_first = _acquire_single_instance()
    if not is_first:
        log.warning("检测到已有一个实例在运行,本实例退出(避免按键被响应两次/配置互相覆盖)")
        QMessageBox.information(
            None, APP_NAME,
            "ICE-Babysitting已经在运行了。\n\n"
            "请直接使用已经打开的窗口。\n"
            "如需重新启动,请先关闭原来那个。"
        )
        sys.exit(0)

    hotkeys = HotkeyManager()
    # 全局热键用低级键盘钩子(WH_KEYBOARD_LL)+独立线程,与浏览器内核无冲突。

    win = MainWindow(config, hotkeys)
    win.show()

    log.info("进入主循环")
    code = app.exec()
    hotkeys.unregister_all()
    config.flush()
    sys.exit(code)


if __name__ == "__main__":
    main()
