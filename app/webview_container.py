"""WebView 容器 —— 内置浏览器核心(WebView2/Edge 内核)。

关键决策:使用 WebView2(Edge Chromium 现代内核)而不是
QtWebEngine(Chromium 83 太旧),这是它能正常访问 B 站等现代网站的根本原因。
本容器基于 qtwebview2 库实现,完全兼容 B 站。

设计:
1. 登录态持久化:user_data_folder 固定存程序目录 profile/ 下
   -> B 站等账号登录后,重启应用自动保持登录。
2. 网址记忆:每次页面跳转实时写回配置 last_url,启动时恢复。
3. 视频控制:通过注入 JS 操作页面里的 <video> 元素。
"""
import os

from PyQt6.QtCore import pyqtSignal

from qtwebview2 import QtWebView2Widget

from . import DATA_DIR
from .logger import get_logger

# 通用视频控制 JS(在 evaluate_js 的 async 包装里直接 return)
_JS_TOGGLE_PLAY = """
var v = document.querySelector('video');
if(!v) { return 'no-video'; }
if(v.paused){ v.play(); return 'play'; } else { v.pause(); return 'pause'; }
"""

_JS_PAUSE = """
var v = document.querySelector('video');
if(!v) { return 'no-video'; }
if(!v.paused){ v.pause(); return 'paused'; }
return 'already-paused';
"""

_JS_SEEK = """
var v = document.querySelector('video');
if(!v) { return 'no-video'; }
v.currentTime = Math.max(0, v.currentTime + %d);
return 'seeked';
"""

_JS_CHANGE_RATE = """
var v = document.querySelector('video');
if(!v) { return 'no-video'; }
var r = Math.min(16, Math.max(0.25, (v.playbackRate || 1) + %s));
v.playbackRate = r;
return 'rate=' + r;
"""

_JS_CHANGE_VOLUME = """
var v = document.querySelector('video');
if(!v) { return 'no-video'; }
var vol = Math.min(1, Math.max(0, (v.volume || 0.5) + %s));
v.volume = vol;
v.muted = false;
return 'vol=' + vol;
"""

# ---- 长按倍速(按住提倍速,松开还原) ----
# 用 window.__iceBaseRate 暂存"按下前的原速",不依赖 Python 侧状态,避免时序竞争。
_JS_HOLD_SPEED = """
(function(){
  var v = document.querySelector('video');
  if(!v) { return 'no-video'; }
  if(window.__iceBaseRate === undefined || window.__iceBaseRate === null){
    var r = v.playbackRate;
    if(typeof r !== 'number' || !(r > 0)){ r = 1; }
    // 站内播放器自己也可能响应同一个键(例如 B站长按右方向键本身就是3倍速),
    // 若此刻读到的已经是目标倍速,说明已经被先手改过了,不能把它误当作"原速"。
    if(Math.abs(r - (%s)) < 0.01){ r = 1; }
    window.__iceBaseRate = r;
  }
  v.playbackRate = %s;
  return 'rate=' + v.playbackRate;
})()
"""

_JS_RELEASE_SPEED = """
(function(){
  var v = document.querySelector('video');
  if(!v) { return 'no-video'; }
  var b = window.__iceBaseRate;
  window.__iceBaseRate = null;
  v.playbackRate = (typeof b === 'number' && b > 0) ? b : 1;
  return 'rate=' + v.playbackRate;
})()
"""

# ---- 自动开启声音 ----
# 为什么需要:Chromium 的自动播放策略规定"没有用户手势"的自动播放必须静音,
# 所以一进视频页 <video> 就是 muted 状态;B站这类站点的播放器还会自己去设 muted。
# 这里监听 play 事件,在"某个视频第一次真正播放"时解除静音。
# 关键:每个 video 只处理一次 —— 之后用户自己按静音,我们不会强行改回来。
# 开关:由 Python 侧注入 window.__iceAutoSound(见 _inject_sound_control)。
_JS_AUTO_SOUND = r"""
(function() {
    if (window.__iceAutoSoundInstalled) { return; }
    window.__iceAutoSoundInstalled = true;
    var handled = new WeakSet();
    function unmute(v) {
        if (window.__iceAutoSound === false) { return; }
        if (!v || v.tagName !== 'VIDEO') { return; }
        if (handled.has(v) || v.paused) { return; }
        handled.add(v);
        if (v.muted) { v.muted = false; }
        setTimeout(function() { if (v.muted) { v.muted = false; } }, 400);
        setTimeout(function() { if (v.muted) { v.muted = false; } }, 1500);
    }
    document.addEventListener('play', function(e) { unmute(e.target); }, true);
    document.addEventListener('loadeddata', function(e) { unmute(e.target); }, true);
    function scan() {
        var vs = document.getElementsByTagName('video');
        for (var i = 0; i < vs.length; i++) { unmute(vs[i]); }
    }
    if (document.readyState !== 'loading') { scan(); }
    document.addEventListener('DOMContentLoaded', scan);
    var n = 0;
    var timer = setInterval(function() {
        scan();
        n++;
        if (n > 20) { clearInterval(timer); }
    }, 500);
})();
"""


class WebViewContainer(QtWebView2Widget):
    url_changed = pyqtSignal(str)
    page_title_changed = pyqtSignal(str)
    js_result = pyqtSignal(str)

    def __init__(self, config, parent=None):
        self._log = get_logger()
        self._config = config
        self._core = None                      # CoreWebView2 引用(运行时改设置要用)
        self._auto_sound = bool(config.get("misc", "auto_sound", True))

        profile_dir = os.path.join(DATA_DIR, "profile")
        url = config.get("browser", "last_url", "https://www.bilibili.com")

        super().__init__(
            url=url,
            user_data_folder=profile_dir,
            context_menus=True,
            # 关键:新窗口(target=_blank / window.open)在当前窗口打开,
            # 不要跳到系统浏览器
            handle_new_window=False,
            init_settings_hook=self._on_core_ready,
            parent=parent,
        )
        self._log.info("恢复上次网址: %s", url)

    # ---------------- 页面事件 ----------------
    def _on_core_ready(self, core):
        """WebView2 核心初始化完成后:挂 URL/标题/新窗口事件 + 注入取消静音脚本。

        注意:这些事件在 .NET 线程触发,这里通过 Qt 信号安全转发到主线程。
        """
        try:
            core.SourceChanged += self._on_source_changed
            core.DocumentTitleChanged += self._on_title_changed
            # 新窗口请求 -> 在当前窗口打开(不跳系统浏览器)
            core.NewWindowRequested += self._on_new_window_requested
        except Exception:
            self._log.exception("挂载页面事件失败")
        self._set_white_background(core)
        self._inject_sound_control(core)

    def _set_white_background(self, core):
        """把 WebView2 的默认底色设成白色。

        默认底色是黑的:页面还没加载完、或 about:blank 时会露出大片黑,
        在浅色主题里非常突兀。改白之后加载过程观感与外壳一致。
        """
        try:
            import clr  # noqa: F401  (pythonnet 已在 qtwebview2 依赖里)
            from System.Drawing import Color
            core.DefaultBackgroundColor = Color.White
            self._log.info("WebView 底色已设为白色")
        except Exception:
            self._log.info("WebView 底色设置不可用(SDK 版本不支持),保持默认")

    def _inject_sound_control(self, core):
        """注入"自动开启声音"控制脚本。

        为什么需要:Chromium 自动播放策略规定"没有用户手势"的自动播放必须静音,
        所以一进视频页 <video> 就是 muted 状态;B站这类站点的播放器还会自己再设 muted。
        实际行为见 _JS_AUTO_SOUND:在"该视频第一次真正播放"时解除静音,每个 video 只做一次
        —— 之后用户自己按静音,不会被我们强行改回来。

        开关做法(关键):先注入一段把 window.__iceAutoSound 设成当前配置值的脚本,
        行为脚本再去读这个值。这样运行中改设置**无需重启**,连当前页面都能立即生效。
        """
        enabled = bool(self._config.get("misc", "auto_sound", True))
        self._auto_sound = enabled
        self._core = core
        try:
            core.AddScriptToExecuteOnDocumentCreatedAsync(self._auto_sound_flag_js(enabled))
            core.AddScriptToExecuteOnDocumentCreatedAsync(_JS_AUTO_SOUND)
            if enabled:
                core.IsMuted = False          # 顺带确保 WebView 引擎自身没被静音
            self._log.info("自动开启声音: %s", "已启用" if enabled else "已关闭")
        except Exception:
            self._log.exception("注入声音控制脚本失败")

    @staticmethod
    def _auto_sound_flag_js(enabled):
        return "window.__iceAutoSound = %s;" % ("true" if enabled else "false")

    def set_auto_sound(self, enabled):
        """运行时切换"自动开启声音":对当前页面立即生效,也影响之后打开的页面。"""
        enabled = bool(enabled)
        self._auto_sound = enabled
        js = self._auto_sound_flag_js(enabled)
        try:
            if self._core is not None:
                self._core.AddScriptToExecuteOnDocumentCreatedAsync(js)
                if enabled:
                    self._core.IsMuted = False
        except Exception:
            self._log.exception("更新声音控制脚本失败")
        try:
            self.evaluate_js(js)              # 当前页面立即生效
        except Exception:
            pass
        self._log.info("自动开启声音已%s", "启用" if enabled else "关闭")

    def _on_new_window_requested(self, sender, args):
        """拦截新窗口请求,在当前窗口内导航。"""
        try:
            url = args.Uri
            args.Handled = True
            if url:
                self._log.info("新窗口请求,在当前窗口打开: %s", url)
                self.load_url(url)
        except Exception:
            self._log.exception("新窗口处理失败")

    def _on_source_changed(self, sender, args):
        try:
            url = sender.Source
            if url and not url.startswith("about:"):
                self._config.set("browser", "last_url", url, save=True)
                self.url_changed.emit(url)
        except Exception:
            pass

    def _on_title_changed(self, sender, args):
        try:
            self.page_title_changed.emit(sender.DocumentTitle)
        except Exception:
            pass

    # ---------------- 导航 ----------------
    def navigate(self, url_text):
        s = url_text.strip()
        if not s:
            return
        if "://" not in s:
            s = "https://" + s
        self.load_url(s)

    def go_home(self):
        self.load_url(self._config.get("browser", "home_url", "https://www.bilibili.com"))

    def back(self):
        """返回上一页。WebView2 的 CoreWebView2 是异步初始化的,
        未就绪时 GoBack 会抛异常;历史为空(CanGoBack=False)时 GoBack 无效果。
        两种情况都静默失败会让"返回按钮"看起来失效 —— 这里做显式检查+日志。"""
        try:
            core = getattr(self, "_webview", None)
            core = getattr(core, "CoreWebView2", None) if core is not None else None
            if core is None:
                self._log.warning("返回被忽略:WebView2 内核尚未初始化完成")
                return
            if not core.CanGoBack:
                self._log.info("返回被忽略:没有上一页可返回")
                return
            core.GoBack()
        except Exception:
            self._log.exception("返回上一页失败")

    def forward(self):
        """前进到下一页(与 back 同样的防呆处理)。"""
        try:
            core = getattr(self, "_webview", None)
            core = getattr(core, "CoreWebView2", None) if core is not None else None
            if core is None:
                self._log.warning("前进被忽略:WebView2 内核尚未初始化完成")
                return
            if not core.CanGoForward:
                self._log.info("前进被忽略:没有下一页可前进")
                return
            core.GoForward()
        except Exception:
            self._log.exception("前进到下一页失败")

    # ---------------- 视频控制 ----------------
    def run_js(self, script):
        self.evaluate_js(script, self._on_js_result)

    def _on_js_result(self, result_dict):
        """evaluate_js 回调:dict {'success': bool, 'result': ..., 'error': ...}"""
        if result_dict and result_dict.get("success"):
            r = result_dict.get("result")
            if r is not None:
                self.js_result.emit(str(r))
        else:
            err = (result_dict or {}).get("error")
            if err:
                self._log.warning("JS 执行失败: %s", err)

    def toggle_play(self):
        self.run_js(_JS_TOGGLE_PLAY)

    def pause(self):
        """无条件暂停(按 9 隐藏窗口时调用)。"""
        self.run_js(_JS_PAUSE)

    def seek(self, delta_sec):
        self.run_js(_JS_SEEK % delta_sec)

    def change_rate(self, delta):
        self.run_js(_JS_CHANGE_RATE % delta)

    def change_volume(self, delta):
        self.run_js(_JS_CHANGE_VOLUME % delta)

    # ---------------- 长按倍速 ----------------
    def hold_speed(self, rate):
        """按住:把视频倍速提到 rate(例如 3.0),并记住原速。"""
        rate = float(rate)
        # 模板里有 2 个占位符:①判定"是否已被站内先手改成目标倍速" ②设置目标倍速
        self.run_js(_JS_HOLD_SPEED % (rate, rate))

    def release_speed(self):
        """松开:把倍速还原到按住之前的值。"""
        self.run_js(_JS_RELEASE_SPEED)
