"""
瞳憩 (EyeZen)：每 30 分钟在所有显示器上显示黑屏提示，可点击按钮结束本次休息。
支持最小化到系统托盘；仅托盘右键「退出」可结束程序。
"""

from __future__ import annotations

import sys
import time
import ctypes

from PySide6.QtCore import Qt, QTimer, Signal, QSize, QRect
from PySide6.QtGui import (
    QAction, QIcon, QPainter, QColor, QPixmap, QScreen,
    QLinearGradient, QPainterPath
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QStackedWidget, QFrame,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QSystemTrayIcon, QMenu, QGridLayout, QScrollArea
)

from stats_store import StatsStore, format_duration

INTERVAL_MS = 30 * 60 * 1000
DAILY_BREAK_GOAL = 8


def _enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _create_tray_icon() -> QIcon:
    """生成高级感系统托盘及应用图标"""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 绘制带渐变的圆角背景
    gradient = QLinearGradient(0, 0, 64, 64)
    gradient.setColorAt(0.0, QColor("#1D8AF0"))
    gradient.setColorAt(1.0, QColor("#1061C1"))
    
    painter.setBrush(gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 16, 16)
    
    # 绘制高级感“眼睛”图标路径
    path = QPainterPath()
    path.moveTo(14, 32)
    path.quadTo(32, 16, 50, 32)
    path.quadTo(32, 48, 14, 32)
    
    painter.setBrush(QColor(255, 255, 255, 230))
    painter.drawPath(path)
    
    # 虹膜
    painter.setBrush(QColor("#1D8AF0"))
    painter.drawEllipse(26, 26, 12, 12)
    
    # 瞳孔反光
    painter.setBrush(Qt.GlobalColor.white)
    painter.drawEllipse(31, 28, 4, 4)
    
    painter.end()
    return QIcon(pixmap)


MAIN_QSS = """
QMainWindow {
    background-color: #FFFFFF;
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
}
QFrame#Sidebar {
    background-color: #F8F9FA;
    border-right: 1px solid #E6E8EB;
}
QStackedWidget {
    background-color: #FFFFFF;
}
QListWidget {
    background-color: transparent;
    border: none;
    outline: none;
    font-size: 15px;
}
QListWidget::item {
    height: 48px;
    padding-left: 16px;
    border-radius: 8px;
    color: #555555;
    margin-bottom: 6px;
}
QListWidget::item:selected {
    background-color: #E6F0F9;
    color: #0078D4;
    font-weight: bold;
}
QListWidget::item:hover:!selected {
    background-color: #EFEFEF;
}
QFrame#Card {
    background-color: #FFFFFF;
    border-radius: 12px;
    border: 1px solid #EAEAEA;
}
QLabel {
    color: #222222;
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
}
QPushButton {
    background-color: #0078D4;
    color: white;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
    border: none;
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
}
QPushButton:hover {
    background-color: #006CBE;
}
QPushButton:pressed {
    background-color: #005A9E;
}
QPushButton#SecondaryBtn {
    background-color: #F0F2F5;
    color: #333333;
}
QPushButton#SecondaryBtn:hover {
    background-color: #E4E6E9;
}
QTableWidget {
    border: 1px solid #EAEAEA;
    border-radius: 8px;
    background-color: #FFFFFF;
    gridline-color: #F2F2F2;
}
QHeaderView::section {
    background-color: #FAFAFA;
    padding: 10px;
    border: none;
    border-bottom: 1px solid #EAEAEA;
    font-weight: bold;
    color: #666666;
}
QProgressBar {
    background-color: #EAEAEA;
    border-radius: 4px;
    height: 8px;
    border: none;
}
QProgressBar::chunk {
    background-color: #0078D4;
    border-radius: 4px;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollBar:vertical {
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px 0px 0px 0px;
}
QScrollBar::handle:vertical {
    background: #CCCCCC;
    min-height: 20px;
    border-radius: 3px;
}
QScrollBar::handle:vertical:hover {
    background: #AAAAAA;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""

class TrendChartWidget(QWidget):
    """自定义图表：绘制最近7周的休息次数柱状图"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []
        self.setMinimumHeight(150)

    def set_data(self, data):
        self.data = data
        self.update()

    def paintEvent(self, event):
        if not self.data:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin_bottom = 24
        margin_top = 24
        chart_h = h - margin_bottom - margin_top

        counts = [d.get("count", 0) for d in self.data]
        max_c = max(max(counts) if counts else 0, 5)

        num_bars = len(self.data)
        bar_width = min(36, w // (num_bars * 2))
        spacing = (w - (bar_width * num_bars)) // (num_bars + 1)

        painter.setPen(Qt.PenStyle.NoPen)
        for i, d in enumerate(self.data):
            c = d.get("count", 0)
            bar_h = (c / max_c) * chart_h
            
            x = spacing + i * (bar_width + spacing)
            y = int(margin_top + chart_h - bar_h)

            # 柱子渐变色
            bar_gradient = QLinearGradient(x, y, x, y + bar_h)
            bar_gradient.setColorAt(0.0, QColor("#3AA2F5"))
            bar_gradient.setColorAt(1.0, QColor("#1061C1"))

            painter.setBrush(bar_gradient)
            painter.drawRoundedRect(x, y, bar_width, int(bar_h), 4, 4)

            # 数值标签
            if c > 0:
                painter.setPen(QColor("#555555"))
                val_font = painter.font()
                val_font.setBold(True)
                painter.setFont(val_font)
                painter.drawText(QRect(x - 10, y - 20, bar_width + 20, 20), Qt.AlignmentFlag.AlignCenter, str(c))

            # X轴日期标签
            painter.setPen(QColor("#888888"))
            date_font = painter.font()
            date_font.setBold(False)
            date_font.setPointSize(9)
            painter.setFont(date_font)
            painter.drawText(QRect(x - 20, h - margin_bottom + 4, bar_width + 40, 20), Qt.AlignmentFlag.AlignCenter, d.get("date", ""))
            painter.setPen(Qt.PenStyle.NoPen)
            
        painter.end()


class ToggleSwitch(QPushButton):
    """仿 iOS 风格的开关组件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(50, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if self.isChecked():
            painter.setBrush(QColor("#34C759"))
        else:
            painter.setBrush(QColor("#D1D1D6"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 14, 14)
        
        painter.setBrush(QColor("#FFFFFF"))
        if self.isChecked():
            painter.drawEllipse(self.width() - 25, 3, 22, 22)
        else:
            painter.drawEllipse(3, 3, 22, 22)


class CardWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        # 增加一点阴影特效可以进一步增强层级感，但考虑到 QSS，先利用边框


class OverlayWindow(QWidget):
    """全屏遮罩及休息提示界面"""
    end_break_signal = Signal()
    
    def __init__(self, screen_index, is_primary):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.Tool
        )
        self.setStyleSheet("background-color: black;")
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        if is_primary:
            msg = QLabel("请起身走动，看看远处，让眼睛休息一会儿。")
            msg.setStyleSheet("color: #EEEEEE; font-size: 28px; font-weight: bold; background: transparent;")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(msg)
            
            layout.addSpacing(60)
            
            btn = QPushButton("结束本次休息")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(220, 56)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #1A1A1A;
                    color: #E0E0E0;
                    border: 2px solid #444444;
                    border-radius: 28px;
                    font-size: 18px;
                    font-weight: bold;
                    letter-spacing: 2px;
                }
                QPushButton:hover {
                    background-color: #2A2A2A; 
                    border-color: #666666;
                    color: #FFFFFF;
                }
                QPushButton:pressed {
                    background-color: #0A0A0A;
                }
            """)
            btn.clicked.connect(self.end_break_signal.emit)
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)


class EyeRestApp(QMainWindow):
    def __init__(self):
        super().__init__()
        _enable_windows_dpi_awareness()
        self.stats = StatsStore.load()
        self.setWindowTitle("瞳憩")
        self.resize(860, 600)
        self.setWindowIcon(_create_tray_icon())
        self.setStyleSheet(MAIN_QSS)
        
        self.overlay_windows = []
        self._next_break_at = time.monotonic() + INTERVAL_MS / 1000.0
        self._break_started_at = None
        self._current_trigger = "timer"
        
        self.timer_enabled = True
        
        # 必须先初始化系统托盘以挂载相关 Action
        self._setup_tray()
        self._setup_ui()
        
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._on_countdown_tick)
        self.countdown_timer.start(1000)
        
        self.break_timer = QTimer(self)
        self.break_timer.timeout.connect(self._on_break_timer)
        self.break_timer.start(INTERVAL_MS)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # --- Sidebar ---
        sidebar_frame = QFrame()
        sidebar_frame.setObjectName("Sidebar")
        sidebar_frame.setFixedWidth(200)
        
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(16, 36, 16, 20)
        
        # 使用新的LOGO渲染与名称横向排列
        logo_layout = QHBoxLayout()
        logo_icon = QLabel()
        logo_icon.setPixmap(_create_tray_icon().pixmap(32, 32))
        app_title = QLabel("瞳  憩")
        app_title.setStyleSheet("font-size: 19px; font-weight: 800; color: #111; letter-spacing: 2px;")
        logo_layout.addWidget(logo_icon)
        logo_layout.addWidget(app_title)
        logo_layout.addStretch()
        
        sidebar_layout.addLayout(logo_layout)
        sidebar_layout.addSpacing(30)
        
        self.sidebar = QListWidget()
        self.sidebar.addItems(["  首 页", "  统计数据"])
        self.sidebar.setCurrentRow(0)
        self.sidebar.currentRowChanged.connect(self._on_page_changed)
        sidebar_layout.addWidget(self.sidebar)
        sidebar_layout.addStretch()
        
        # --- Stacked Content ---
        self.stack = QStackedWidget()
        
        self.page_home = self._create_home_page()
        self.stack.addWidget(self.page_home)
        
        self.page_stats = self._create_stats_page()
        self.stack.addWidget(self.page_stats)
        
        main_layout.addWidget(sidebar_frame)
        main_layout.addWidget(self.stack, 1)

    def _create_home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(24)
        
        title = QLabel("主控制台")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #111;")
        layout.addWidget(title)
        
        # Card 1: Timer setting & Massive Countdown
        card1 = CardWidget()
        cl1 = QVBoxLayout(card1)
        cl1.setContentsMargins(24, 24, 24, 30)
        cl1.setSpacing(16)
        
        # Row: Switch Configuration
        row1 = QHBoxLayout()
        desc = QLabel("启用定时提醒")
        desc.setStyleSheet("font-size: 16px; font-weight: bold;")
        sub_desc = QLabel("\n系统每 30 分钟提示一次，引导全屏黑屏休息")
        sub_desc.setStyleSheet("color: #777; font-size: 13px; font-weight: normal;")
        
        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        text_layout.addWidget(desc)
        text_layout.addWidget(sub_desc)
        
        row1.addLayout(text_layout)
        row1.addStretch()
        
        self.timer_switch = ToggleSwitch()
        self.timer_switch.setChecked(True)
        self.timer_switch.clicked.connect(self._on_timer_toggled)
        row1.addWidget(self.timer_switch)
        cl1.addLayout(row1)
        
        # Divider Line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #F0F0F0; margin-top: 10px; margin-bottom: 10px;")
        cl1.addWidget(line)
        
        # Focus: Big Countdown Display
        countdown_container = QVBoxLayout()
        countdown_container.setSpacing(4)
        
        self.countdown_label = QLabel("30:00")
        # 使用更为显眼的粗体大字号
        self.countdown_label.setStyleSheet("font-size: 72px; font-weight: 900; color: #0078D4; font-family: 'Arial', sans-serif; letter-spacing: 4px;")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.countdown_subtitle = QLabel("距离下次护眼休息")
        self.countdown_subtitle.setStyleSheet("color: #888888; font-size: 15px; font-weight: 600;")
        self.countdown_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        countdown_container.addWidget(self.countdown_label)
        countdown_container.addWidget(self.countdown_subtitle)
        countdown_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        cl1.addLayout(countdown_container)
        layout.addWidget(card1)
        
        layout.addSpacing(10)
        
        # Card 2: Manual Control
        card2 = CardWidget()
        cl2 = QHBoxLayout(card2)
        cl2.setContentsMargins(24, 24, 24, 24)
        
        manual_desc = QLabel("想要立刻给眼睛放个假？")
        manual_desc.setStyleSheet("font-size: 15px; font-weight: 600; color: #333;")
        cl2.addWidget(manual_desc)
        cl2.addStretch()
        
        start_btn = QPushButton("立即开始休息")
        start_btn.setFixedSize(130, 42)
        start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        start_btn.clicked.connect(self.start_break)
        cl2.addWidget(start_btn)
        
        layout.addWidget(card2)
        layout.addStretch()
        
        self._refresh_countdown_text()
        return page

    def _create_stats_page(self) -> QWidget:
        # Wrap the whole stats page in a scroll area in case of smaller windows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        page = QWidget()
        scroll.setWidget(page)
        
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(20)
        
        header_layout = QHBoxLayout()
        title = QLabel("详细统计看板")
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #111;")
        header_layout.addWidget(title)
        
        refresh_btn = QPushButton("刷新数据")
        refresh_btn.setObjectName("SecondaryBtn")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setFixedSize(90, 36)
        refresh_btn.clicked.connect(self._refresh_stats)
        header_layout.addWidget(refresh_btn)
        layout.addLayout(header_layout)
        
        # Grid Card: KPI Stats
        grid_card = CardWidget()
        grid = QGridLayout(grid_card)
        grid.setContentsMargins(24, 24, 24, 24)
        grid.setSpacing(30)
        
        self.stat_labels = {}
        def add_stat_box(title_text, key, row, col):
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(8)
            tl = QLabel(title_text)
            tl.setStyleSheet("color: #777; font-size: 14px; font-weight: 500;")
            vl = QLabel("—")
            vl.setStyleSheet("font-size: 22px; font-weight: bold; color: #222;")
            bl.addWidget(tl)
            bl.addWidget(vl)
            bl.setAlignment(Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(box, row, col)
            self.stat_labels[key] = vl
            
        add_stat_box("累计完成休息", "total_breaks", 0, 0)
        add_stat_box("累计休息时长", "total_dur", 0, 1)
        add_stat_box("今日休息次数", "today_count", 0, 2)
        add_stat_box("今日休息时长", "today_dur", 1, 0)
        add_stat_box("近 7 天次数", "week_count", 1, 1)
        add_stat_box("近 7 天时长", "week_dur", 1, 2)
        layout.addWidget(grid_card)

        hw_layout = QHBoxLayout()
        hw_layout.setSpacing(20)
        
        # Left half: Today's Goal
        goal_card = CardWidget()
        gl = QVBoxLayout(goal_card)
        gl.setContentsMargins(20, 24, 20, 24)
        gl.setSpacing(12)
        
        gh = QHBoxLayout()
        gl_title = QLabel(f"今日健康目标 ({DAILY_BREAK_GOAL}次)")
        gl_title.setStyleSheet("font-weight: bold; font-size: 15px;")
        gh.addWidget(gl_title)
        
        self.goal_hint_label = QLabel()
        self.goal_hint_label.setStyleSheet("color: #888; font-size: 13px;")
        gh.addStretch()
        gh.addWidget(self.goal_hint_label)
        gl.addLayout(gh)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(DAILY_BREAK_GOAL)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        gl.addWidget(self.progress_bar)
        
        hw_layout.addWidget(goal_card, 1)
        
        # Right half: Trend Chart
        trend_card = CardWidget()
        tl = QVBoxLayout(trend_card)
        tl.setContentsMargins(20, 16, 20, 16)
        
        tl_title = QLabel("近七天规律概览")
        tl_title.setStyleSheet("font-weight: bold; font-size: 14px; color: #555;")
        tl.addWidget(tl_title)
        
        self.trend_chart = TrendChartWidget()
        tl.addWidget(self.trend_chart)
        
        hw_layout.addWidget(trend_card, 2)
        layout.addLayout(hw_layout)
        
        # Table of recents
        rl = QLabel("近期记录明细")
        rl.setStyleSheet("font-weight: bold; font-size: 16px; margin-top: 10px;")
        layout.addWidget(rl)
        
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["结束时间", "休息时长", "触发方式"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setMinimumHeight(150)
        layout.addWidget(self.table)
        
        layout.addStretch()
        self._refresh_stats()
        return scroll

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(_create_tray_icon())
        self.tray_icon.setToolTip("瞳憩 - 运作中")
        
        self.tray_menu = QMenu(self)
        self.tray_menu.setStyleSheet("""
            QMenu { background-color: #FFFFFF; border: 1px solid #CCCCCC; border-radius: 6px; padding: 4px; }
            QMenu::item { padding: 8px 30px 8px 30px; color: #222; font-size: 13px; border-radius: 4px; }
            QMenu::item:selected { background-color: #0078D4; color: white; }
            QMenu::item:disabled { color: #888888; background-color: transparent; }
            QMenu::separator { height: 1px; background: #EAEAEA; margin: 4px 6px; }
        """)
        
        self.tray_countdown_action = QAction("距离下次休息: 计算中...", self)
        self.tray_countdown_action.setEnabled(False) # 作为纯状态展示
        
        show_action = QAction("打开主控制台", self)
        show_action.triggered.connect(self.showNormal)
        
        quit_action = QAction("退出程序", self)
        quit_action.triggered.connect(self._quit_app)
        
        self.tray_menu.addAction(self.tray_countdown_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(show_action)
        self.tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_page_changed(self, index: int):
        self.stack.setCurrentIndex(index)
        if index == 1:
            self._refresh_stats()

    def _on_timer_toggled(self):
        self.timer_enabled = self.timer_switch.isChecked()
        if self.timer_enabled:
            self._next_break_at = time.monotonic() + INTERVAL_MS / 1000.0
            self.break_timer.start(INTERVAL_MS)
            self.countdown_subtitle.setText("距离下次护眼休息")
            self.countdown_label.setStyleSheet("font-size: 72px; font-weight: 900; color: #0078D4; font-family: 'Arial', sans-serif; letter-spacing: 4px;")
            self._refresh_countdown_text()
        else:
            self.break_timer.stop()
            self.countdown_label.setText("未开启")
            self.countdown_subtitle.setText("定时提醒已在上方暂停")
            self.countdown_label.setStyleSheet("font-size: 72px; font-weight: 900; color: #C0C0C0; font-family: 'Arial', sans-serif; letter-spacing: 4px;")
            self.tray_countdown_action.setText("定时提醒已暂停")
            self.tray_icon.setToolTip("瞳憩 - 已暂停")

    def _on_countdown_tick(self):
        if self.overlay_windows:
            return
        if self.timer_enabled:
            self._refresh_countdown_text()

    def _refresh_countdown_text(self):
        if not self.timer_enabled:
            return
        left = int(max(0, self._next_break_at - time.monotonic()))
        m, s = divmod(left, 60)
        time_str = f"{m:02d}:{s:02d}"
        
        self.countdown_label.setText(time_str)
        self.tray_countdown_action.setText(f"下次休息还有：{time_str}")
        self.tray_icon.setToolTip(f"瞳憩 - 倒计时 {time_str}")

    def _refresh_stats(self):
        self.stats.reload()
        s = self.stats.summary()
        
        self.stat_labels["total_breaks"].setText(f"{s['total_breaks']} 次")
        self.stat_labels["total_dur"].setText(format_duration(s['total_duration_sec']))
        self.stat_labels["today_count"].setText(f"{s['today_count']} 次")
        self.stat_labels["today_dur"].setText(format_duration(s['today_duration_sec']))
        self.stat_labels["week_count"].setText(f"{s['week_count']} 次")
        self.stat_labels["week_dur"].setText(format_duration(s['week_duration_sec']))
        
        today_n = min(DAILY_BREAK_GOAL, max(0, s['today_count']))
        self.progress_bar.setValue(today_n)
        
        hint = f"进度：{s['today_count']} / {DAILY_BREAK_GOAL}"
        if s['today_count'] >= DAILY_BREAK_GOAL:
            hint += " (已达标！)"
            self.progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #34C759; border-radius: 4px; }")
        else:
            self.progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #0078D4; border-radius: 4px; }")
        self.goal_hint_label.setText(hint)
        
        # 刷新趋势图表
        week_trend = s.get("week_trend", [])
        self.trend_chart.set_data(week_trend)
        
        # 刷新表格
        recent = s.get("recent", [])[:20]
        self.table.setRowCount(len(recent))
        trigger_map = {"timer": "定时自动", "manual": "主动开始"}
        for i, row in enumerate(recent):
            if not isinstance(row, dict):
                continue
            
            at = str(row.get("at", ""))
            dur = format_duration(int(row.get("duration_sec", 0)))
            tr = trigger_map.get(str(row.get("trigger", "")), str(row.get("trigger", "")))
            
            i1 = QTableWidgetItem(at)
            i1.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 0, i1)
            
            i2 = QTableWidgetItem(dur)
            i2.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # 高亮过短过长的表现
            dur_sec = int(row.get("duration_sec", 0))
            if dur_sec < 60:
                i2.setForeground(QColor("#FF9500")) # 较短的休息，橙色警告
                
            self.table.setItem(i, 1, i2)
            
            i3 = QTableWidgetItem(tr)
            i3.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if tr == "主动开始":
                i3.setForeground(QColor("#34C759"))
            self.table.setItem(i, 2, i3)

    def start_break(self):
        if self.overlay_windows:
            return
        if self.timer_enabled:
            self.break_timer.stop()
        self._open_overlays(trigger="manual")

    def _on_break_timer(self):
        if not self.timer_enabled:
            return
        self.break_timer.stop()
        self._open_overlays(trigger="timer")

    def _open_overlays(self, trigger: str):
        if self.overlay_windows:
            return
        self._current_trigger = trigger
        self._break_started_at = time.monotonic()
        
        screens = QApplication.screens()
        primary = QApplication.primaryScreen()
        
        for idx, screen in enumerate(screens):
            is_primary = (screen == primary)
            w = OverlayWindow(idx, is_primary)
            w.end_break_signal.connect(self.end_break)
            
            geom = screen.geometry()
            w.move(geom.topLeft())
            w.resize(geom.size())
            w.showFullScreen()
            self.overlay_windows.append(w)

    def end_break(self):
        if self._break_started_at is not None:
            duration_sec = int(max(0, time.monotonic() - self._break_started_at))
            self.stats.record_break(duration_sec, self._current_trigger)
        self._break_started_at = None
        
        for w in self.overlay_windows:
            w.close()
            w.deleteLater()
        self.overlay_windows.clear()
        
        if self.stack.currentIndex() == 1:
            self._refresh_stats()
            
        if self.timer_enabled:
            self._next_break_at = time.monotonic() + INTERVAL_MS / 1000.0
            self.break_timer.start(INTERVAL_MS)
            self._refresh_countdown_text()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.showNormal()
            self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def _quit_app(self):
        for w in self.overlay_windows:
            w.close()
        self.tray_icon.hide()
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    
    # 保证只运行一个实例、提升在高分屏下的表现等
    app.setQuitOnLastWindowClosed(False)
    
    window = EyeRestApp()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
