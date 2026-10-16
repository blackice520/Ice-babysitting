"""ICE-Babysitting 安装程序 —— 打包成单个「ICE-Babysitting_安装包.exe」。

功能:
  1. 选择安装目录(默认装到当前用户的 LOCALAPPDATA,无需管理员)
  2. 解压内置的程序负载(payload.zip)到目标目录
  3. 创建桌面快捷方式 + 开始菜单快捷方式
  4. 生成卸载脚本,并在开始菜单放「卸载 ICE-Babysitting」
  5. 安装完成后可直接启动

命令行(供自动化/静默安装,便于测试):
  --silent            静默安装,不显示界面
  --dir  <路径>        指定安装目录
  --no-desktop        不创建桌面快捷方式
  --no-run            安装后不启动
"""
import os
import sys
import zipfile

APP_NAME = "ICE-Babysitting"
EXE_NAME = "ICE-Babysitting.exe"
PUBLISHER = "本地学习项目"

IS_FROZEN = getattr(sys, "frozen", False)


def resource_path(name):
    """取打包进安装程序的资源路径。"""
    if IS_FROZEN:
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def default_install_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs", APP_NAME)


def _start_menu_dir():
    return os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "Microsoft", "Windows", "Start Menu", "Programs",
    )


def _desktop_dir():
    return os.path.join(os.path.expanduser("~"), "Desktop")


def make_shortcut(lnk_path, target, arguments="", workdir="", icon="", desc=""):
    """用 WScript.Shell 创建 .lnk 快捷方式。"""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        lnk = shell.CreateShortCut(lnk_path)
        lnk.TargetPath = target
        if arguments:
            lnk.Arguments = arguments
        if workdir:
            lnk.WorkingDirectory = workdir
        if icon:
            lnk.IconLocation = icon
        if desc:
            lnk.Description = desc
        lnk.Save()
        return True
    except Exception:
        # 兜底:用 PowerShell 创建
        try:
            import subprocess
            ps = (
                f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk_path}');"
                f"$s.TargetPath='{target}';"
                f"$s.Arguments='{arguments}';"
                f"$s.WorkingDirectory='{workdir}';"
                f"$s.IconLocation='{icon}';"
                f"$s.Description='{desc}';$s.Save()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           creationflags=0x08000000, check=False)
            return os.path.exists(lnk_path)
        except Exception:
            return False


UNINSTALL_BAT = r"""@echo off
chcp 65001 >nul
title 卸载 {app}
echo 正在卸载 {app} ...
echo.
echo 是否同时删除个人数据(配置 / 登录态,位于 %USERPROFILE%\.ice-babysitting)?
choice /c YN /m "删除数据请按 Y,保留请按 N"
if errorlevel 2 goto keepdata
if errorlevel 1 rd /s /q "%USERPROFILE%\.ice-babysitting" 2>nul
:keepdata
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\{app}.lnk" 2>nul
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\卸载 {app}.lnk" 2>nul
del /q "%USERPROFILE%\Desktop\{app}.lnk" 2>nul
cd /d "%TEMP%"
rd /s /q "{target}" 2>nul
echo.
echo 卸载完成。
pause
"""


def do_install(target, desktop=True, progress=None, log=None):
    """把安装包内的 payload.zip 解压到 target,并创建快捷方式。

    progress: callable(percent:int, text:str) 可选
    log:      callable(str) 可选
    """
    def _p(pct, text=""):
        if progress:
            progress(pct, text)

    def _log(text):
        if log:
            log(text)

    payload = resource_path("payload.zip")
    if not os.path.exists(payload):
        raise FileNotFoundError(f"安装包损坏:缺少 {payload}")

    os.makedirs(target, exist_ok=True)

    # 1) 解压程序文件
    with zipfile.ZipFile(payload, "r") as zf:
        members = zf.infolist()
        total = max(1, len(members))
        for i, m in enumerate(members, 1):
            zf.extract(m, target)
            if i % 5 == 0 or i == total:
                _p(int(i / total * 90), f"正在释放文件 {i}/{total}")
    _log(f"已释放 {len(members)} 个文件到 {target}")

    exe_path = os.path.join(target, EXE_NAME)
    if not os.path.exists(exe_path):
        raise FileNotFoundError(f"解压后未找到 {EXE_NAME}")

    # 2) 生成卸载脚本
    uninstall_path = os.path.join(target, "卸载.bat")
    win_target = target.replace("/", "\\")
    with open(uninstall_path, "w", encoding="utf-8") as f:
        f.write(UNINSTALL_BAT.format(app=APP_NAME, target=win_target))
    _p(93, "生成卸载程序…")

    # 3) 快捷方式
    _p(96, "创建快捷方式…")
    icon = exe_path
    sm = _start_menu_dir()
    os.makedirs(sm, exist_ok=True)
    make_shortcut(os.path.join(sm, f"{APP_NAME}.lnk"), exe_path, workdir=target,
                  icon=icon, desc="小窗浏览器")
    make_shortcut(os.path.join(sm, f"卸载 {APP_NAME}.lnk"), uninstall_path,
                  workdir=target, icon=icon, desc=f"卸载 {APP_NAME}")
    if desktop:
        try:
            make_shortcut(os.path.join(_desktop_dir(), f"{APP_NAME}.lnk"), exe_path,
                          workdir=target, icon=icon, desc="小窗浏览器")
        except Exception:
            pass

    _p(100, "安装完成")
    return exe_path


# ---------------- 图形界面 ----------------
def run_gui(argv):
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    from PyQt6.QtWidgets import (
        QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
        QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
    )

    class Worker(QThread):
        tick = pyqtSignal(int, str)
        done = pyqtSignal(str)
        fail = pyqtSignal(str)

        def __init__(self, target, desktop):
            super().__init__()
            self.target = target
            self.desktop = desktop

        def run(self):
            try:
                exe = do_install(
                    self.target, self.desktop,
                    progress=lambda pct, text: self.tick.emit(pct, text),
                )
                self.done.emit(exe)
            except Exception as e:
                self.fail.emit(str(e))

    class Win(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(f"{APP_NAME} 安装程序")
            self.setFixedWidth(520)
            v = QVBoxLayout(self)
            v.setContentsMargins(22, 18, 22, 16)
            v.setSpacing(10)

            title = QLabel(f"安装 {APP_NAME}")
            title.setStyleSheet("font-size:17px;font-weight:bold;")
            v.addWidget(title)
            sub = QLabel("纯本地运行 · 无需联网验证")
            sub.setStyleSheet("color:#666;")
            v.addWidget(sub)

            v.addSpacing(6)
            v.addWidget(QLabel("安装位置:"))
            row = QHBoxLayout()
            self.edit = QLineEdit(default_install_dir())
            browse = QPushButton("浏览…")
            browse.clicked.connect(self.choose_dir)
            row.addWidget(self.edit, 1)
            row.addWidget(browse)
            v.addLayout(row)

            self.chk_desktop = QCheckBox("创建桌面快捷方式")
            self.chk_desktop.setChecked(True)
            v.addWidget(self.chk_desktop)

            self.chk_run = QCheckBox("安装完成后立即启动")
            self.chk_run.setChecked(True)
            v.addWidget(self.chk_run)

            self.bar = QProgressBar()
            self.bar.setValue(0)
            self.bar.setVisible(False)
            v.addWidget(self.bar)

            self.status = QLabel("")
            self.status.setStyleSheet("color:#666;")
            v.addWidget(self.status)

            v.addSpacing(4)
            btns = QHBoxLayout()
            btns.addStretch(1)
            self.btn_install = QPushButton("开始安装")
            self.btn_install.setDefault(True)
            self.btn_install.clicked.connect(self.start)
            btn_cancel = QPushButton("取消")
            btn_cancel.clicked.connect(self.close)
            btns.addWidget(btn_cancel)
            btns.addWidget(self.btn_install)
            v.addLayout(btns)
            self.worker = None

        def choose_dir(self):
            d = QFileDialog.getExistingDirectory(self, "选择安装位置", self.edit.text())
            if d:
                self.edit.setText(os.path.join(d, APP_NAME))

        def start(self):
            target = self.edit.text().strip()
            if not target:
                QMessageBox.warning(self, "提示", "请先选择安装位置。")
                return
            self.btn_install.setEnabled(False)
            self.bar.setVisible(True)
            self.status.setText("准备安装…")
            self.worker = Worker(target, self.chk_desktop.isChecked())
            self.worker.tick.connect(self.on_tick)
            self.worker.done.connect(self.on_done)
            self.worker.fail.connect(self.on_fail)
            self.worker.start()

        def on_tick(self, pct, text):
            self.bar.setValue(pct)
            if text:
                self.status.setText(text)

        def on_done(self, exe):
            self.bar.setValue(100)
            QMessageBox.information(
                self, "安装完成",
                f"{APP_NAME} 已安装完成!\n\n程序位置:\n{exe}\n\n"
                "已创建开始菜单快捷方式" +
                (",以及桌面快捷方式。" if self.chk_desktop.isChecked() else "。"))
            if self.chk_run.isChecked():
                try:
                    os.startfile(exe)
                except Exception:
                    pass
            self.close()

        def on_fail(self, msg):
            self.btn_install.setEnabled(True)
            self.bar.setVisible(False)
            self.status.setText("安装失败")
            QMessageBox.critical(self, "安装失败", f"安装过程中出错:\n{msg}")

    app = QApplication(argv)
    w = Win()
    w.show()
    return app.exec()


def main():
    argv = sys.argv[1:]
    if "--silent" in argv:
        target = default_install_dir()
        if "--dir" in argv:
            target = argv[argv.index("--dir") + 1]
        desktop = "--no-desktop" not in argv
        exe = do_install(target, desktop,
                         progress=lambda p, t: print(f"[{p:3d}%] {t}", flush=True))
        print(f"安装完成: {exe}", flush=True)
        if "--no-run" not in argv:
            try:
                os.startfile(exe)
            except Exception:
                pass
        return 0
    return run_gui(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
