"""波形显示与选区交互控件。

只负责"画波形 + 拖选起止点"，不涉及音频播放和裁剪逻辑。
"""

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

# 颜色
BACKGROUND = QColor("#0f1720")
DIM = QColor(0, 0, 0, 150)          # 选区之外的遮罩
ACCENT = QColor("#4dabf7")
HANDLE = QColor("#f59f00")
PLAYHEAD = QColor("#ff6b6b")
TEXT = QColor("#9aa4b2")

HANDLE_GRAB_PX = 8       # 判定抓取手柄的像素范围
MIN_SELECTION = 0.2      # 最小选区长度（秒）


class WaveformView(QWidget):
    """显示波形，并支持拖动起止手柄选择区间。"""

    # 选区变化: (start_seconds, end_seconds)
    selection_changed = pyqtSignal(float, float)
    # 用户点击波形请求跳转: (seconds)
    seek_requested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.duration = 0.0
        self.sel_start = 0.0
        self.sel_end = 0.0
        self.position = 0.0
        self._pixmap: QPixmap | None = None
        self._status = "正在生成波形..."
        self._drag: str | None = None

    # ---------- 外部接口 ----------

    def set_status(self, text: str) -> None:
        self._status = text
        self._pixmap = None
        self.update()

    def set_waveform(self, png_bytes: bytes) -> None:
        pixmap = QPixmap()
        if png_bytes and pixmap.loadFromData(png_bytes, "PNG"):
            self._pixmap = pixmap
            self._status = ""
        else:
            self._pixmap = None
            self._status = "波形加载失败"
        self.update()

    def set_duration(self, duration: float) -> None:
        self.duration = max(0.0, float(duration))
        self.sel_start = 0.0
        self.sel_end = self.duration
        self.position = 0.0
        self.update()
        self.selection_changed.emit(self.sel_start, self.sel_end)

    def set_selection(self, start: float, end: float) -> None:
        if self.duration <= 0:
            return
        self.sel_start = max(0.0, min(float(start), self.duration))
        self.sel_end = max(self.sel_start, min(float(end), self.duration))
        self.update()
        self.selection_changed.emit(self.sel_start, self.sel_end)

    def set_position(self, seconds: float) -> None:
        if self.duration <= 0:
            return
        self.position = max(0.0, min(float(seconds), self.duration))
        self.update()

    def selection(self) -> tuple[float, float]:
        return self.sel_start, self.sel_end

    # ---------- 坐标换算 ----------

    def _plot_rect(self) -> QRect:
        # 留出边距，避免手柄贴在边缘不好抓
        return self.rect().adjusted(2, 2, -2, -2)

    def _time_to_x(self, seconds: float) -> float:
        rect = self._plot_rect()
        if self.duration <= 0:
            return float(rect.left())
        ratio = max(0.0, min(1.0, seconds / self.duration))
        return rect.left() + ratio * rect.width()

    def _x_to_time(self, x: float) -> float:
        rect = self._plot_rect()
        if rect.width() <= 0 or self.duration <= 0:
            return 0.0
        ratio = (x - rect.left()) / rect.width()
        return max(0.0, min(1.0, ratio)) * self.duration

    # ---------- 绘制 ----------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rect = self.rect()
        painter.fillRect(rect, BACKGROUND)

        if self._pixmap is not None:
            painter.drawPixmap(self._plot_rect(), self._pixmap)
        else:
            painter.setPen(QPen(TEXT))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._status)

        if self.duration > 0:
            start_x = self._time_to_x(self.sel_start)
            end_x = self._time_to_x(self.sel_end)

            # 选区外的遮罩
            painter.fillRect(
                QRect(int(rect.left()), rect.top(), int(start_x - rect.left()), rect.height()), DIM
            )
            painter.fillRect(
                QRect(int(end_x), rect.top(), int(rect.right() - end_x), rect.height()), DIM
            )

            # 起止手柄
            painter.setPen(QPen(HANDLE, 2))
            for x in (start_x, end_x):
                painter.drawLine(int(x), rect.top(), int(x), rect.bottom())
                painter.setBrush(HANDLE)
                painter.drawEllipse(int(x) - 4, rect.top() + 2, 8, 8)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            # 播放头
            pos_x = self._time_to_x(self.position)
            painter.setPen(QPen(PLAYHEAD, 1))
            painter.drawLine(int(pos_x), rect.top(), int(pos_x), rect.bottom())

    # ---------- 交互 ----------

    def _hit_test(self, x: float) -> str:
        start_x = self._time_to_x(self.sel_start)
        end_x = self._time_to_x(self.sel_end)
        if abs(x - start_x) <= HANDLE_GRAB_PX and start_x <= end_x:
            return "start"
        if abs(x - end_x) <= HANDLE_GRAB_PX:
            return "end"
        return "new"

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.duration <= 0 or event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        mode = self._hit_test(x)
        if mode == "new":
            # 在空白处按下：以该点为锚点重新拉选
            self._drag_anchor = self._x_to_time(x)
            self._drag = "new"
            self.set_selection(self._drag_anchor, self._drag_anchor)
        else:
            self._drag = mode

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self.duration <= 0:
            return
        x = event.position().x()

        if self._drag is None:
            self.setCursor(
                Qt.CursorShape.SizeHorCursor
                if self._hit_test(x) != "new"
                else Qt.CursorShape.ArrowCursor
            )
            return

        if self._drag == "start":
            self.set_selection(min(self._x_to_time(x), self.sel_end - MIN_SELECTION), self.sel_end)
        elif self._drag == "end":
            self.set_selection(self.sel_start, max(self._x_to_time(x), self.sel_start + MIN_SELECTION))
        else:  # new
            anchor = getattr(self, "_drag_anchor", 0.0)
            current = self._x_to_time(x)
            low, high = sorted((anchor, current))
            self.set_selection(low, high)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag is not None:
            if self._drag == "new" and self.sel_end - self.sel_start < MIN_SELECTION:
                # 只是单击：跳转播放位置，不改动选区
                self.set_selection(0.0, self.duration)
                self.seek_requested.emit(self._x_to_time(event.position().x()))
            self._drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
