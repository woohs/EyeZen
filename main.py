"""
瞳憩 (EyeZen)：每 30 分钟在所有显示器上显示黑屏提示，可点击按钮结束本次休息。
支持最小化到系统托盘；仅托盘右键「退出」可结束程序。
"""

from __future__ import annotations

import sys
import time
import ctypes

from PySide6.QtCore import Qt, QTimer, Signal, QSize, QRect, QRectF, QPointF
from PySide6.QtGui import (
    QAction, QIcon, QPainter, QColor, QPixmap, QScreen,
    QLinearGradient, QPainterPath, QPen
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QStackedWidget, QFrame,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QSystemTrayIcon, QMenu, QGridLayout, QScrollArea, QSizePolicy
)

from stats_store import StatsStore, format_duration

INTERVAL_MS = 30 * 60 * 1000
DAILY_BREAK_GOAL = 8


def format_percent(value: float) -> str:
    percent = max(0.0, min(1.0, float(value))) * 100
    return f"{percent:.0f}%"


def format_duration_compact(sec: int) -> str:
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec} 秒"
    minutes = sec // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, remain_minutes = divmod(minutes, 60)
    return f"{hours}时{remain_minutes}分"


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

class GoalRingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress = 0.0
        self.current_value = 0
        self.goal_value = DAILY_BREAK_GOAL
        self.setMinimumSize(180, 180)

    def set_progress(self, progress: float, current_value: int, goal_value: int):
        self.progress = max(0.0, min(1.0, float(progress)))
        self.current_value = max(0, int(current_value))
        self.goal_value = max(0, int(goal_value))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height()) - 20
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

        track_pen = QPen(QColor("#E9EEF5"), 14)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(rect, 0, 360 * 16)

        progress_pen = QPen(QColor("#0078D4"), 14)
        progress_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(progress_pen)
        painter.drawArc(rect, 90 * 16, int(-360 * 16 * self.progress))

        painter.setPen(QColor("#111111"))
        value_font = painter.font()
        value_font.setPointSize(26)
        value_font.setBold(True)
        painter.setFont(value_font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, format_percent(self.progress))

        sub_rect = self.rect().adjusted(0, 44, 0, 0)
        painter.setPen(QColor("#6B7280"))
        sub_font = painter.font()
        sub_font.setPointSize(10)
        painter.setFont(sub_font)
        painter.drawText(sub_rect, Qt.AlignmentFlag.AlignCenter, f"{self.current_value} / {self.goal_value} 次")


class RateTrendChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []
        self.setMinimumHeight(210)

    def set_data(self, data):
        self.data = data or []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.data:
            painter.setPen(QColor("#9CA3AF"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无达成率数据")
            return

        w = self.width()
        h = self.height()
        left = 36
        right = 18
        top = 20
        bottom = 34
        chart_w = max(1, w - left - right)
        chart_h = max(1, h - top - bottom)

        painter.setPen(QPen(QColor("#E5E7EB"), 1))
        for step in range(5):
            y = top + chart_h * step / 4
            painter.drawLine(left, int(y), left + chart_w, int(y))

        points = []
        count = len(self.data)
        for index, item in enumerate(self.data):
            x = left if count == 1 else left + chart_w * index / (count - 1)
            rate = max(0.0, min(1.0, float(item.get("rate", 0.0))))
            y = top + chart_h * (1 - rate)
            points.append(QPointF(x, y))

        area_path = QPainterPath()
        area_path.moveTo(points[0].x(), top + chart_h)
        for point in points:
            area_path.lineTo(point)
        area_path.lineTo(points[-1].x(), top + chart_h)
        area_path.closeSubpath()
        area_gradient = QLinearGradient(0, top, 0, top + chart_h)
        area_gradient.setColorAt(0.0, QColor(0, 120, 212, 70))
        area_gradient.setColorAt(1.0, QColor(0, 120, 212, 10))
        painter.fillPath(area_path, area_gradient)

        line_pen = QPen(QColor("#0078D4"), 3)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(line_pen)
        for idx in range(len(points) - 1):
            painter.drawLine(points[idx], points[idx + 1])

        for idx, point in enumerate(points):
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(QPen(QColor("#0078D4"), 2))
            painter.drawEllipse(point, 4, 4)
            painter.setPen(QColor("#6B7280"))
            painter.drawText(QRectF(point.x() - 22, point.y() - 28, 44, 18), Qt.AlignmentFlag.AlignCenter, format_percent(self.data[idx].get("rate", 0.0)))
            painter.drawText(QRectF(point.x() - 28, top + chart_h + 8, 56, 18), Qt.AlignmentFlag.AlignCenter, str(self.data[idx].get("date", "")))


class DurationDistributionWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []
        self.setMinimumHeight(190)

    def set_data(self, data):
        self.data = data or []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.data:
            painter.setPen(QColor("#9CA3AF"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无休息时长分布")
            return

        total = sum(max(0, int(item.get("duration_sec", 0))) for item in self.data)
        colors = {
            "上午": QColor("#0EA5E9"),
            "下午": QColor("#10B981"),
            "晚上": QColor("#F59E0B"),
        }
        labels_rect = QRect(0, self.height() - 62, self.width(), 56)
        bar_rect = QRectF(12, 30, max(40, self.width() - 24), 44)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#EEF2F7"))
        painter.drawRoundedRect(bar_rect, 14, 14)

        start_x = bar_rect.x()
        for item in self.data:
            duration_sec = max(0, int(item.get("duration_sec", 0)))
            if total == 0:
                width = bar_rect.width() / max(1, len(self.data))
            else:
                width = bar_rect.width() * duration_sec / total
            rect = QRectF(start_x, bar_rect.y(), width, bar_rect.height())
            painter.setBrush(colors.get(str(item.get("period", "")), QColor("#94A3B8")))
            painter.drawRoundedRect(rect, 14, 14)
            start_x += width

        item_width = self.width() / max(1, len(self.data))
        for index, item in enumerate(self.data):
            period = str(item.get("period", ""))
            duration_sec = max(0, int(item.get("duration_sec", 0)))
            text_rect = QRectF(index * item_width, labels_rect.top(), item_width, labels_rect.height())
            painter.setBrush(colors.get(period, QColor("#94A3B8")))
            painter.drawEllipse(QRectF(text_rect.x() + 12, text_rect.y() + 12, 10, 10))
            painter.setPen(QColor("#374151"))
            title_rect = QRectF(text_rect.x() + 28, text_rect.y() + 4, item_width - 30, 20)
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, period)
            painter.setPen(QColor("#6B7280"))
            painter.drawText(QRectF(text_rect.x() + 28, text_rect.y() + 24, item_width - 30, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, format_duration_compact(duration_sec))


class HeatmapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []
        self.setMinimumHeight(260)

    def set_data(self, data):
        self.data = data or []
        self.update()

    def _cell_color(self, count: int) -> QColor:
        if count <= 0:
            return QColor("#F3F4F6")
        if count == 1:
            return QColor("#D7ECFF")
        if count == 2:
            return QColor("#9FD4FF")
        return QColor("#3AA2F5")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.data:
            painter.setPen(QColor("#9CA3AF"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无热力图数据")
            return

        periods = ["上午", "下午", "晚上"]
        top = 34
        left = 54
        right = 16
        bottom = 18
        rows = len(self.data)
        cols = len(periods)
        cell_w = max(48, (self.width() - left - right) / max(1, cols))
        cell_h = max(24, (self.height() - top - bottom) / max(1, rows))

        painter.setPen(QColor("#6B7280"))
        for col, period in enumerate(periods):
            rect = QRectF(left + col * cell_w, 4, cell_w, 24)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, period)

        for row_index, row in enumerate(self.data):
            date_label = str(row.get("date", ""))
            painter.drawText(QRectF(0, top + row_index * cell_h, left - 8, cell_h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, date_label)
            hours = row.get("hours", [])
            hour_map = {str(item.get("period", "")): item for item in hours if isinstance(item, dict)}
            for col, period in enumerate(periods):
                item = hour_map.get(period, {})
                count = max(0, int(item.get("count", 0)))
                duration_text = format_duration_compact(int(item.get("duration_sec", 0)))
                rect = QRectF(left + col * cell_w + 4, top + row_index * cell_h + 4, cell_w - 8, cell_h - 8)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._cell_color(count))
                painter.drawRoundedRect(rect, 8, 8)
                painter.setPen(QColor("#0F172A") if count >= 2 else QColor("#475569"))
                painter.drawText(rect.adjusted(0, -8, 0, 0), Qt.AlignmentFlag.AlignCenter, f"{count} 次")
                painter.setPen(QColor("#64748B"))
                painter.drawText(rect.adjusted(0, 10, 0, 0), Qt.AlignmentFlag.AlignCenter, duration_text)


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
        self.resize(1360, 900)
        self.setMinimumSize(1180, 780)
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
        page.setMinimumWidth(1220)
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
        grid_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        grid = QGridLayout(grid_card)
        grid.setContentsMargins(24, 24, 24, 24)
        grid.setHorizontalSpacing(36)
        grid.setVerticalSpacing(28)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        
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

        health_title = QLabel("核心健康指标")
        health_title.setStyleSheet("font-size: 18px; font-weight: 800; color: #111827; margin-top: 6px;")
        layout.addWidget(health_title)

        health_layout = QHBoxLayout()
        health_layout.setSpacing(20)

        goal_card = CardWidget()
        goal_card.setMinimumHeight(330)
        gl = QVBoxLayout(goal_card)
        gl.setContentsMargins(22, 22, 22, 22)
        gl.setSpacing(14)

        goal_title = QLabel("今日护眼达成率")
        goal_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #0F172A;")
        gl.addWidget(goal_title)

        goal_subtitle = QLabel(f"以每日 {DAILY_BREAK_GOAL} 次有效休息为目标")
        goal_subtitle.setStyleSheet("font-size: 13px; color: #6B7280;")
        gl.addWidget(goal_subtitle)

        self.goal_ring = GoalRingWidget()
        gl.addWidget(self.goal_ring, 0, Qt.AlignmentFlag.AlignCenter)

        self.goal_hint_label = QLabel("—")
        self.goal_hint_label.setStyleSheet("font-size: 13px; color: #475569; font-weight: 600;")
        self.goal_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gl.addWidget(self.goal_hint_label)

        health_layout.addWidget(goal_card, 1)

        weekly_card = CardWidget()
        weekly_card.setMinimumHeight(330)
        wl = QVBoxLayout(weekly_card)
        wl.setContentsMargins(22, 22, 22, 22)
        wl.setSpacing(12)

        week_title = QLabel("本周护眼达成率")
        week_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #0F172A;")
        wl.addWidget(week_title)

        self.week_goal_value_label = QLabel("—")
        self.week_goal_value_label.setStyleSheet("font-size: 30px; font-weight: 800; color: #0078D4;")
        wl.addWidget(self.week_goal_value_label)

        self.week_goal_hint_label = QLabel("—")
        self.week_goal_hint_label.setStyleSheet("font-size: 13px; color: #6B7280;")
        wl.addWidget(self.week_goal_hint_label)

        self.week_progress_bar = QProgressBar()
        self.week_progress_bar.setMaximum(100)
        self.week_progress_bar.setValue(0)
        self.week_progress_bar.setTextVisible(False)
        wl.addWidget(self.week_progress_bar)
        wl.addStretch()

        health_layout.addWidget(weekly_card, 1)
        layout.addLayout(health_layout)

        trend_grid = QGridLayout()
        trend_grid.setHorizontalSpacing(20)
        trend_grid.setVerticalSpacing(20)
        trend_grid.setColumnStretch(0, 3)
        trend_grid.setColumnStretch(1, 2)

        trend_card = CardWidget()
        trend_card.setMinimumHeight(340)
        tl = QVBoxLayout(trend_card)
        tl.setContentsMargins(20, 18, 20, 18)
        tl.setSpacing(10)

        tl_title = QLabel("近 7 天每日达成率趋势")
        tl_title.setStyleSheet("font-weight: 700; font-size: 15px; color: #0F172A;")
        tl.addWidget(tl_title)

        tl_desc = QLabel("折线展示每天有效休息完成度变化")
        tl_desc.setStyleSheet("font-size: 12px; color: #6B7280;")
        tl.addWidget(tl_desc)

        self.rate_trend_chart = RateTrendChartWidget()
        tl.addWidget(self.rate_trend_chart)

        trend_grid.addWidget(trend_card, 0, 0)

        summary_card = CardWidget()
        summary_card.setMinimumHeight(340)
        sl = QVBoxLayout(summary_card)
        sl.setContentsMargins(20, 20, 20, 20)
        sl.setSpacing(12)

        summary_title = QLabel("本周概况")
        summary_title.setStyleSheet("font-weight: 700; font-size: 15px; color: #0F172A;")
        sl.addWidget(summary_title)

        self.week_count_summary = QLabel("—")
        self.week_count_summary.setStyleSheet("font-size: 24px; font-weight: 800; color: #111827;")
        sl.addWidget(self.week_count_summary)

        self.week_duration_summary = QLabel("—")
        self.week_duration_summary.setStyleSheet("font-size: 14px; color: #475569;")
        sl.addWidget(self.week_duration_summary)

        summary_note = QLabel("说明：少于 1 分钟的短休会保留时长记录，但不计入休息次数。")
        summary_note.setWordWrap(True)
        summary_note.setStyleSheet("font-size: 12px; color: #6B7280; line-height: 1.4;")
        sl.addWidget(summary_note)
        sl.addStretch()

        trend_grid.addWidget(summary_card, 0, 1)
        layout.addLayout(trend_grid)

        distribution_title = QLabel("休息时长分布")
        distribution_title.setStyleSheet("font-size: 18px; font-weight: 800; color: #111827; margin-top: 4px;")
        layout.addWidget(distribution_title)

        distribution_grid = QGridLayout()
        distribution_grid.setHorizontalSpacing(20)
        distribution_grid.setVerticalSpacing(20)
        distribution_grid.setColumnStretch(0, 3)
        distribution_grid.setColumnStretch(1, 4)

        dist_card = CardWidget()
        dist_card.setMinimumHeight(320)
        dl = QVBoxLayout(dist_card)
        dl.setContentsMargins(20, 18, 20, 18)
        dl.setSpacing(8)

        dist_title = QLabel("时段累积休息时长")
        dist_title.setStyleSheet("font-weight: 700; font-size: 15px; color: #0F172A;")
        dl.addWidget(dist_title)

        dist_desc = QLabel("堆叠柱状图按上午 / 下午 / 晚上统计近 7 天累积休息时长")
        dist_desc.setStyleSheet("font-size: 12px; color: #6B7280;")
        dl.addWidget(dist_desc)

        self.duration_distribution_chart = DurationDistributionWidget()
        dl.addWidget(self.duration_distribution_chart)

        distribution_grid.addWidget(dist_card, 0, 0)

        heatmap_card = CardWidget()
        heatmap_card.setMinimumHeight(320)
        hl = QVBoxLayout(heatmap_card)
        hl.setContentsMargins(20, 18, 20, 18)
        hl.setSpacing(8)

        heatmap_title = QLabel("一周时段休息热力图")
        heatmap_title.setStyleSheet("font-weight: 700; font-size: 15px; color: #0F172A;")
        hl.addWidget(heatmap_title)

        heatmap_desc = QLabel("颜色越深表示该日期时段内的有效休息越频繁")
        heatmap_desc.setStyleSheet("font-size: 12px; color: #6B7280;")
        hl.addWidget(heatmap_desc)

        self.heatmap_chart = HeatmapWidget()
        hl.addWidget(self.heatmap_chart)

        distribution_grid.addWidget(heatmap_card, 0, 1)
        layout.addLayout(distribution_grid)
        
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
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(280)
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
        s = self.stats.summary(DAILY_BREAK_GOAL)
        
        self.stat_labels["total_breaks"].setText(f"{s['total_breaks']} 次")
        self.stat_labels["total_dur"].setText(format_duration(s['total_duration_sec']))
        self.stat_labels["today_count"].setText(f"{s['today_count']} 次")
        self.stat_labels["today_dur"].setText(format_duration(s['today_duration_sec']))
        self.stat_labels["week_count"].setText(f"{s['week_count']} 次")
        self.stat_labels["week_dur"].setText(format_duration(s['week_duration_sec']))
        
        today_rate = float(s.get("today_goal_rate", 0.0))
        week_rate = float(s.get("week_goal_rate", 0.0))
        self.goal_ring.set_progress(today_rate, s['today_count'], DAILY_BREAK_GOAL)

        hint = f"今日有效休息 {s['today_count']} 次，达成率 {format_percent(today_rate)}"
        if s['today_count'] >= DAILY_BREAK_GOAL:
            hint += "，已完成今日目标"
        self.goal_hint_label.setText(hint)

        self.week_goal_value_label.setText(format_percent(week_rate))
        self.week_goal_hint_label.setText(f"近 7 天累计 {s['week_count']} 次有效休息，目标 {DAILY_BREAK_GOAL * 7} 次")
        self.week_progress_bar.setValue(int(round(week_rate * 100)))
        if week_rate >= 1.0:
            self.week_progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #34C759; border-radius: 4px; }")
        else:
            self.week_progress_bar.setStyleSheet("QProgressBar::chunk { background-color: #0078D4; border-radius: 4px; }")

        self.week_count_summary.setText(f"近 7 天共 {s['week_count']} 次有效休息")
        self.week_duration_summary.setText(f"累计休息时长 {format_duration(s['week_duration_sec'])}")

        self.rate_trend_chart.set_data(s.get("week_rate_trend", []))
        self.duration_distribution_chart.set_data(s.get("period_duration_distribution", []))
        self.heatmap_chart.set_data(s.get("week_heatmap", []))
        
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
