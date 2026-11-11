"""主窗口与 GUI 启动入口。

主窗口结构：中央是一层背景（渐变 + 柔光斑，可整体替换为图片），其上
「自绘标题栏（图标 + 标题 + 导航条 + 窗口三键）+ 页面堆叠区」。

标题栏接管系统标题栏的方式见 :mod:`gui.view.window_chrome`：保留窗口样式，
只在消息层把客户区扩到整窗、把顶部条分配给 ``HTCAPTION``，因此拖动、双击最大
化、贴边、四角缩放仍由系统完成。若平台不支持或被环境变量关闭，自动退回
「系统标题栏 + 玻璃导航条」的旧布局。

页面自身用卡片分区；主题切换时同时更新「调色板 + QSS + 令牌」，背景、标题栏
与卡片随之重建模糊缓存。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QEvent, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from common.exceptions import ConfigError, SystemInfoError
from config.schema import StatusBarConfig
from gui.components.nav_bar import NavBar
from gui.components.status_bar import StatusBar
from gui.components.title_bar import TITLE_HEIGHT, TitleBar
from gui.theme.appearance import apply_appearance
from gui.theme.background import BackgroundWidget
from gui.theme.tokens import DesignTokens
from gui.view.sample_page import SamplePage
from gui.view.settings_tab import SettingsTab
from gui.view.window_chrome import NativeFrame, native_frame_enabled
from service.sysinfo import SystemCollector

if TYPE_CHECKING:
    from config.manager import ConfigManager

logger = logging.getLogger(__name__)

__all__ = ["MainWindow", "run_gui"]

#: 导航条图标键：设置齿轮状滑块 / 示例页叠层。
_NAV_SETTINGS_ICON = "settings"
_NAV_SAMPLE_ICON = "sample"


class MainWindow(QMainWindow):
    """应用主窗口：背景层 + 自绘标题栏（含导航）+ 页面堆叠。

    Args:
        parent: 父控件。
        config_manager: 通用配置中心；提供时语言/主题切换会持久化到
            ``app.ui_language`` / ``app.theme``，缺失时仅即时切换。
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        config_manager: ConfigManager | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_manager: ConfigManager | None = config_manager
        theme = self._current_ui_theme()
        self._tokens: DesignTokens = apply_appearance(theme)
        metrics = self._tokens.metrics
        status_config = self._current_status_config()

        self._settings = SettingsTab(
            ui_language=self._current_ui_language(),
            theme=theme,
            status_bar=status_config,
            tokens=self._tokens,
        )
        self._sample = SamplePage(tokens=self._tokens)
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._settings)
        self._stack.addWidget(self._sample)

        self._nav = NavBar(self._tokens)
        self._nav.add_item(_NAV_SETTINGS_ICON, "Settings")
        self._nav.add_item(_NAV_SAMPLE_ICON, "Sample")

        self._frameless = native_frame_enabled()
        self._title_bar: TitleBar | None = None
        self._chrome = NativeFrame(
            title_height=TITLE_HEIGHT,
            is_drag_region=self._is_drag_region,
            on_size_move=self._on_size_move,
        )

        if self._frameless:
            # 让 Qt 认为这是无边框窗口：最大化按工作区算，mapToGlobal 也不会
            # 被系统标题栏的高度带偏；真实的窗口样式在 NativeFrame 里补回
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            # 导航条嵌进标题栏：标题栏已有底色与分隔线，不再叠一层玻璃条
            self._nav.set_bare(True)
            self._title_bar = TitleBar(
                self._tokens, self._nav, self.tr("Sheep Box"), self
            )
            self._title_bar.minimize_requested.connect(self.showMinimized)
            self._title_bar.maximize_toggle_requested.connect(self._toggle_maximized)
            self._title_bar.close_requested.connect(self.close)
            header: QWidget = self._title_bar
        else:
            nav_row = QWidget(self)
            nav_layout = QHBoxLayout(nav_row)
            nav_layout.setContentsMargins(
                metrics.space_xl, metrics.space_lg, metrics.space_xl, 0
            )
            nav_layout.setSpacing(0)
            nav_layout.addWidget(self._nav)
            header = nav_row

        self._background = BackgroundWidget(self._tokens, self)
        self._status_bar = StatusBar(
            tokens=self._tokens,
            stops=[(stop.at, stop.color) for stop in status_config.gradient_stops],
            parent=self._background,
        )
        layout = QVBoxLayout(self._background)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header, 0)
        layout.addWidget(self._stack, 1)
        layout.addWidget(self._status_bar, 0)
        self.setCentralWidget(self._background)

        self.resize(600, 480)
        self.setMinimumSize(520, 400)

        self._collector: SystemCollector | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(status_config.refresh_interval_ms)
        self._timer.timeout.connect(self._refresh_status)
        self._sample_failed = False

        self._nav.currentChanged.connect(self._on_page_changed)
        self._settings.language_selected.connect(self._on_language_selected)
        self._settings.theme_selected.connect(self._on_theme_selected)
        self._settings.refresh_interval_selected.connect(
            self._on_refresh_interval_selected
        )
        self._settings.gradient_stops_changed.connect(self._on_gradient_stops_changed)
        self.retranslate_ui()

    # -------------------------------------------------------- 窗口框架

    def nativeEvent(
        self, event_type: QByteArray | bytes | bytearray | memoryview, message: int
    ) -> object:
        """把原生消息交给 :class:`NativeFrame`，未处理的继续走 Qt 默认实现。"""
        if self._chrome.enabled:
            handled, result = self._chrome.handle(message)
            if handled:
                return True, result
        return super().nativeEvent(event_type, message)

    def showEvent(self, event: QShowEvent) -> None:
        """首次显示时接入原生框架、启动状态栏采样，并把焦点交给背景层。

        焦点交给背景层是为了避免第一个下拉框一打开就带着高亮（观感上像误触）。
        """
        super().showEvent(event)
        self._install_native_frame()
        self._background.setFocus()
        self._start_monitoring()

    def closeEvent(self, event: QCloseEvent) -> None:
        """关闭窗口时停止采样并释放 PDH 句柄。"""
        self._timer.stop()
        if self._collector is not None:
            self._collector.close()
            self._collector = None
        super().closeEvent(event)

    def _start_monitoring(self) -> None:
        """创建采集器并启动刷新定时器（重复调用无副作用）。

        采集器构造时已建立 CPU 时间与 GPU 计数器的基线，因此第一次定时触发
        读到的就是真实区间值，不需要额外丢弃首帧。
        """
        if not self._timer.isActive():
            self._timer.start()
        if self._collector is not None:
            return
        try:
            self._collector = SystemCollector()
        except Exception:
            logger.warning("系统信息采集器初始化失败，状态栏将保持空值", exc_info=True)
            self._collector = None

    def _refresh_status(self) -> None:
        """定时采样并刷新状态栏；连续失败只记一次日志。"""
        collector = self._collector
        if collector is None:
            return
        try:
            snapshot = collector.sample()
        except SystemInfoError as exc:
            if not self._sample_failed:
                logger.warning("状态栏采样失败: %s", exc)
                self._sample_failed = True
            return
        self._sample_failed = False
        self._status_bar.apply_snapshot(snapshot)

    def _install_native_frame(self) -> None:
        """首次显示后把自绘标题栏接到原生窗口消息上（仅 Windows 真实窗口）。"""
        if not self._frameless or self._chrome.enabled:
            return
        if QApplication.platformName() != "windows":
            return
        if not self._chrome.install(int(self.winId())):
            return
        if self._title_bar is not None:
            self._title_bar.set_maximized(self.isMaximized())

    def changeEvent(self, event: QEvent) -> None:
        """最大化/还原时同步标题栏按钮图标。"""
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self._title_bar:
            self._title_bar.set_maximized(self.isMaximized())

    def _toggle_maximized(self) -> None:
        """最大化 / 还原切换（由标题栏最大化按钮触发）。"""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _is_drag_region(self, x: int, y: int) -> bool:
        """标题栏上的点是否可拖动（导航项与按钮区不可拖）。"""
        if self._title_bar is None:
            return False
        return self._title_bar.is_drag_region(x, y)

    def _on_size_move(self, moving: bool) -> None:
        """拖动/缩放期间冻结毛玻璃重算，结束后恢复。"""
        self._background.set_blur_paused(moving)
        if not moving:
            self._background.update()

    # -------------------------------------------------------- 页面与主题

    def _on_page_changed(self, index: int) -> None:
        """导航切换后同步页面堆叠。"""
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)

    def _current_ui_language(self) -> str | None:
        """读取当前程序偏好的界面语言；config 不可用时返回 None（回退默认）。"""
        if self._config_manager is None:
            return None
        try:
            return self._config_manager.app().ui_language
        except ConfigError:
            logger.warning("读取界面语言失败，回退默认 zh_CN", exc_info=True)
            return None

    def _current_ui_theme(self) -> str | None:
        """读取当前程序偏好的界面主题；config 不可用时返回 None（回退浅色）。"""
        if self._config_manager is None:
            return None
        try:
            return self._config_manager.app().theme
        except ConfigError:
            logger.warning("读取界面主题失败，回退默认浅色", exc_info=True)
            return None

    def _current_status_config(self) -> StatusBarConfig:
        """读取状态栏配置；config 不可用或字段缺失时回退 schema 默认值。"""
        if self._config_manager is None:
            return StatusBarConfig()
        try:
            return self._config_manager.app().status_bar
        except ConfigError:
            logger.warning("读取状态栏配置失败，回退默认值", exc_info=True)
            return StatusBarConfig()

    def _save_status_bar(self, update: dict[str, object]) -> None:
        """把状态栏子字段写回 ``app.status_bar``；失败回滚控件并提示。"""
        if self._config_manager is None:
            return
        try:
            self._config_manager.save_app({"status_bar": update})
        except ConfigError:
            logger.warning("状态栏配置写回失败: %s", update, exc_info=True)
            self._apply_status_config(self._current_status_config())
            self._rollback_notice()

    def _apply_status_config(self, config: StatusBarConfig) -> None:
        """把状态栏配置应用到定时器与着色条（写盘失败回滚用）。"""
        self._timer.setInterval(config.refresh_interval_ms)
        stops = [(stop.at, stop.color) for stop in config.gradient_stops]
        self._status_bar.set_gradient_stops(stops)
        self._settings.show_values(interval=config.refresh_interval_ms, stops=stops)

    def _rollback_notice(self) -> None:
        """写盘失败后的统一提示：界面已恢复到磁盘上的旧设置。"""
        self._settings.show_notice(self.tr("Failed to save settings, reverted"))

    def _on_refresh_interval_selected(self, milliseconds: int) -> None:
        """用户切换刷新间隔：立即改定时器周期并持久化。"""
        self._timer.setInterval(milliseconds)
        self._save_status_bar({"refresh_interval_ms": milliseconds})

    def _on_gradient_stops_changed(self, stops: object) -> None:
        """用户编辑压力着色锚点：状态栏立即换色并持久化。

        信号用 ``list`` 承载，跨进程边界后元素类型不确定，这里逐个校验再转换，
        非法条目直接跳过（不阻断其余锚点生效）。

        Args:
            stops: ``[(位置百分比, #rrggbb), ...]``。
        """
        parsed: list[tuple[float, str]] = []
        if isinstance(stops, list):
            for entry in stops:
                if not isinstance(entry, tuple) or len(entry) != 2:
                    continue
                at, color = entry
                try:
                    parsed.append((float(at), str(color)))
                except (TypeError, ValueError):
                    continue
        if len(parsed) < 2:
            return
        self._status_bar.set_gradient_stops(parsed)
        self._save_status_bar(
            {"gradient_stops": [{"at": at, "color": color} for at, color in parsed]}
        )

    def _on_language_selected(self, language: str) -> None:
        """用户切换界面语言：切翻译 → 持久化 → 刷新界面文本。"""
        from app.i18n import resolve_ui_language, switch_ui_language

        previous = self._current_ui_language()
        switch_ui_language(language)
        self.retranslate_ui()
        if self._config_manager is None:
            return
        try:
            self._config_manager.save_app({"ui_language": language})
        except ConfigError:
            logger.warning("界面语言写回失败: %s", language, exc_info=True)
            switch_ui_language(resolve_ui_language(previous))
            self.retranslate_ui()
            self._settings.show_values(language=previous or "")
            self._rollback_notice()

    def _apply_theme_appearance(self, theme: str | None) -> None:
        """把主题应用为当前外观（切换与回滚共用）。"""
        self._tokens = apply_appearance(theme)
        self._background.set_tokens(self._tokens)
        self._nav.apply_tokens(self._tokens)
        self._settings.apply_tokens(self._tokens)
        self._sample.apply_tokens(self._tokens)
        self._status_bar.apply_tokens(self._tokens)
        if self._title_bar is not None:
            self._title_bar.apply_tokens(self._tokens)
        self._background.update()

    def _on_theme_selected(self, theme: str) -> None:
        """用户切换界面主题：应用调色板与 QSS → 更新令牌 → 持久化。"""
        previous = self._current_ui_theme()
        self._apply_theme_appearance(theme)
        if self._config_manager is None:
            return
        try:
            self._config_manager.save_app({"theme": theme})
        except ConfigError:
            logger.warning("界面主题写回失败: %s", theme, exc_info=True)
            self._apply_theme_appearance(previous)
            self._settings.show_values(theme=previous or "")
            self._rollback_notice()

    def retranslate_ui(self) -> None:
        """重设主窗口界面文本（语言切换后刷新）。"""
        # 窗口标题 = 程序名，任务栏与 Alt+Tab 缩略图取的就是这个字符串
        self.setWindowTitle(self.tr("Sheep Box"))
        # 导航项与标题写字面量 tr()，供 lupdate 静态提取
        self._nav.set_titles([self.tr("Settings"), self.tr("Sample")])
        if self._title_bar is not None:
            self._title_bar.set_title(self.tr("Sheep Box"))
        self._settings.retranslate_ui()
        self._sample.retranslate_ui()
        self._status_bar.retranslate_ui()


def run_gui(
    language: str | None = None, config_manager: ConfigManager | None = None
) -> int:
    """启动 GUI 应用（阻塞运行，返回退出码）。

    Args:
        language: 界面语言（如 ``zh_CN``）；缺省按程序偏好解析。
        config_manager: 通用配置中心；提供时语言切换可持久化。
    """
    from app.i18n import install_ui_translator
    from app.theme import apply_ui_style

    app = QApplication.instance() or QApplication([])
    # 先固定 Fusion 样式：调色板驱动的黑白主题需样式逐角色遵循 QPalette，
    # 否则 Windows 原生样式会忽略应用调色板、深色主题不生效。
    apply_ui_style()
    install_ui_translator(language)
    window = MainWindow(config_manager=config_manager)
    window.show()
    return app.exec()
