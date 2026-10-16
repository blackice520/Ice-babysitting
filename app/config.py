"""配置管理 —— 状态保存/恢复的核心。

针对以下历史问题:
1. 曾出现"存了但启动时不读" -> 现在启动必读、关闭时必写。
2. 曾出现"保存的是初始值,不是真实窗口状态;句柄获取失败"
   -> 我们保存时实时读取窗口真实 geometry,不在关闭时才读一次,而是
      移动/缩放过程中持续更新(带防抖落盘),关闭时再兜底写一次。
3. 登录态:由 WebView 的持久化 profile 负责(见 webview_container.py)。

配置用 JSON,存放在用户数据目录(~/.ice-babysitting)下 config.json,便于用户查看和备份。
"""
import json
import os
import threading
import time

from . import DATA_DIR

_DEFAULT_HOTKEYS = {
    "toggle_play": "`",            # ~ 播放/暂停(默认)
    "seek_forward": "6",           # 快进 5 秒;**长按同一个键 = 倍速播放**(对齐 B站)
    "seek_backward": "5",          # 快退 5 秒(长按连发)
    "toggle_maximize": "ctrl+space",  # 最大化/还原
    "toggle_hide": "9",            # 隐藏/显示(打游戏时临时藏起小窗)
    "toggle_clickthrough": "0",    # 鼠标穿透开关(默认 0)
}

# 手柄按键 -> 动作 默认映射(XInput 标准按键名,见 app/gamepad.py)
_DEFAULT_GAMEPAD = {
    "toggle_play": "a",
    "seek_forward": "rb",
    "seek_backward": "lb",
    "toggle_hide": "start",
    "toggle_clickthrough": "y",
}

_DEFAULTS = {
    "window": {
        "x": 100,
        "y": 100,
        "width": 480,
        "height": 640,
        "maximized": False,
        "opacity": 1.0,
        "topmost": True,
        "click_through": False,
    },
    "browser": {
        "home_url": "https://www.bilibili.com",
        "last_url": "https://www.bilibili.com",
    },
    "hotkeys": dict(_DEFAULT_HOTKEYS),
    "gamepad": {
        "enabled": True,
        "mapping": dict(_DEFAULT_GAMEPAD),
    },
    "misc": {
        "volume": 1.0,
        "playback_rate": 1.0,
        "seek_step_sec": 5,
        "boost_rate": 3.0,     # 长按倍速播放的目标倍速(B站长按右方向键同为 3 倍速)
        "auto_sound": True,    # 打开网页视频时自动解除静音(Chromium 自动播放会默认静音)
    },
}


class Config:
    def __init__(self, path=None):
        if path is None:
            path = os.path.join(DATA_DIR, "config.json")
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()
        self._dirty = False
        self._last_save = 0.0

    def _load(self):
        data = json.loads(json.dumps(_DEFAULTS))  # 深拷贝默认值
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    user = json.load(f)
                self._merge(data, user)
            except Exception:
                # 配置损坏时备份并回退默认,不让用户数据直接丢失
                try:
                    os.replace(self.path, self.path + ".bak")
                except Exception:
                    pass
        return data

    # 这些配置项必须"整体替换",不能深合并:
    #   hotkeys / gamepad.mapping 属于"集合型"配置 —— 用户解绑某个按键后,
    #   若按字典深合并,默认值会被重新补回来,表现为
    #   "改了设置,重开又回到默认值"。
    _ATOMIC_PATHS = {("hotkeys",), ("gamepad", "mapping")}

    @staticmethod
    def _merge(base, override, path=()):
        for k, v in override.items():
            cur_path = path + (k,)
            if (isinstance(v, dict) and isinstance(base.get(k), dict)
                    and cur_path not in Config._ATOMIC_PATHS):
                Config._merge(base[k], v, cur_path)
            else:
                base[k] = v

    def get(self, section, key=None, default=None):
        with self._lock:
            if key is None:
                return self._data.get(section, default)
            return self._data.get(section, {}).get(key, default)

    def set(self, section, key, value, save=True):
        # 注意:先更新数据再释放锁,然后再 save()。
        # save() 内部要获取 self._lock,而 threading.Lock 不可重入,
        # 在持锁状态下调用 save() 会死锁(实测主线程卡死)。
        with self._lock:
            self._data.setdefault(section, {})[key] = value
        if save:
            self.save()

    def update(self, section, mapping, save=True):
        with self._lock:
            self._data.setdefault(section, {}).update(mapping)
        if save:
            self.save()

    def save(self):
        """防抖落盘:0.5 秒内多次调用只写一次。"""
        now = time.time()
        with self._lock:
            self._data["_saved_at"] = now
            if now - self._last_save < 0.5:
                self._dirty = True
                return
            self._write_locked()
            self._last_save = now

    def flush(self):
        """关闭前兜底,立即写盘。"""
        with self._lock:
            self._write_locked()

    def _write_locked(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            self._dirty = False
        except Exception:
            pass
