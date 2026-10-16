"""ICE-Babysitting —— 纯本地小窗浏览器

纯本地、免费、无任何联网验证的应用。
技术栈:PyQt6 + WebView2(Edge Chromium 内核)+ pythonnet
"""

import os
import shutil
import sys

if getattr(sys, "frozen", False):
    # PyInstaller 打包后:程序本体在 exe 目录
    APP_DIR = os.path.dirname(sys.executable)
else:
    # 源码运行:项目根目录
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_NAME = "ICE-Babysitting"
__version__ = "2.1.1"


def asset_path(name):
    """资源文件路径。

    源码运行时取项目根目录下的 assets/;打包(onedir)后取 _internal/assets/。
    """
    base = getattr(sys, "_MEIPASS", None) or APP_DIR
    return os.path.join(base, "assets", name)


ICON_PATH = asset_path("ice-babysitting.ico")

# ---------------- 数据目录 ----------------
# 关键决策:数据(配置/登录态/日志)存在【用户主目录 ~/.ice-babysitting】,而不是 exe 目录。
# 这样更新/替换程序文件时,登录态和窗口状态完全不受影响。
# 用户可设置环境变量 ICE_BABYSITTING_CONFIG_DIR 自定义位置。
ENV_OVERRIDE = "ICE_BABYSITTING_CONFIG_DIR"

# 旧版本(数据放在程序目录下)的迁移清单,只在"首次迁移数据"时读取一次。
_MIGRATE_ITEMS = ("config.json", "profile", "logs")


def _get_data_dir():
    env = os.environ.get(ENV_OVERRIDE, "").strip()
    if env:
        return os.path.abspath(env)
    return os.path.join(os.path.expanduser("~"), ".ice-babysitting")


DATA_DIR = _get_data_dir()


def _note(msg):
    """迁移提示。打包成 windowed 程序后没有控制台,sys.stdout 可能是 None,
    这时 print 会抛异常 —— 所以必须兜住,否则会中断后面的迁移。"""
    try:
        print(msg)
    except Exception:
        pass


def _copy_once(src, dst):
    """src 存在且 dst 不存在时才复制。返回是否真的复制了。"""
    if not os.path.exists(src) or os.path.exists(dst):
        return False
    try:
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return True
    except Exception:
        return False


def _migrate_legacy_data():
    """一次性数据迁移:把"数据放在程序目录"的旧版本数据搬到用户目录。

    规则:只在新位置**还没有**对应文件时复制,绝不覆盖已有数据;
    迁移后旧文件保留(不删),万一有问题还能退回去。整个过程幂等,失败也不影响启动。
    """
    try:
        # 必须先建好目标目录:否则第一个"单文件复制"(config.json)会因
        # 目标目录不存在而失败 —— 它会被静默跳过,只有后面的目录复制
        # (copytree 会顺带建出父目录)才成功,结果配置丢了。(实测踩过)
        os.makedirs(DATA_DIR, exist_ok=True)

        for name in _MIGRATE_ITEMS:
            if _copy_once(os.path.join(APP_DIR, name),
                          os.path.join(DATA_DIR, name)):
                _note(f"[迁移] {os.path.join(APP_DIR, name)} → {DATA_DIR}")
    except Exception:
        pass


# 模块加载时执行一次迁移(幂等:新目录已有数据则什么都不做)
_migrate_legacy_data()
