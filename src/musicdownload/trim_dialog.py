"""音频剪辑窗口：波形选区 + 试听 + 保存。"""

from pathlib import Path

from PyQt6.QtCore import QUrl, Qt, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from musicdownload.trimmer import (
    MIN_CLIP_SECONDS,
    DurationWorker,
    TrimWorker,
    WaveformWorker,
    format_time,
    parse_time,
    unique_target_path,
)
from musicdownload.waveform import WaveformView


class TrimDialog(QDialog):
    """对单个音频文件做区间裁剪。"""

    # 保存成功: (路径)  —— 供主窗口刷新日志/状态
    saved = pyqtSignal(str)

    def __init__(self, audio_path: str | Path, parent=None):
        super().__init__(parent)
        self.audio_path = Path(audio_path)
        self.duration = 0.0
        self._waveform_worker = None
        self._duration_worker = None
        self._trim_worker = None
        self._stop_at: float | None = None

        self.setWindowTitle(f"剪辑音频 — {self.audio_path.name}")
        self.resize(920, 520)
        # 先建界面再建播放器：播放器的错误信号会写 status_label，
        # 若顺序反过来，早到的错误会引用到还不存在的控件。
        self._init_ui()
        self._init_player()
        self._start_loading()

    # ---------- 播放 ----------

    def _init_player(self) -> None:
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.8)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setSource(QUrl.fromLocalFile(str(self.audio_path)))
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.errorOccurred.connect(self.on_player_error)

    def on_player_error(self, error, error_string: str = "") -> None:
        if error_string:
            self.status_label.setText(f"播放失败: {error_string}")

    def on_position_changed(self, position_ms: int) -> None:
        seconds = position_ms / 1000.0
        self.waveform.set_position(seconds)
        self.position_label.setText(f"{format_time(seconds)} / {format_time(self.duration)}")
        if self._stop_at is not None and seconds >= self._stop_at:
            self.player.pause()
            self._stop_at = None

    # ---------- 界面 ----------

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.title_label = QLabel(self.audio_path.name)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.title_label)

        hint = QLabel("在波形上拖动橙色手柄选择保留区间；单击波形可跳转播放位置。")
        hint.setStyleSheet("color: #6b7280;")
        layout.addWidget(hint)

        self.waveform = WaveformView()
        self.waveform.selection_changed.connect(self.on_selection_changed)
        self.waveform.seek_requested.connect(self.seek)
        layout.addWidget(self.waveform)

        # 播放控制
        play_row = QHBoxLayout()
        self.play_button = QPushButton("▶ 播放")
        self.play_button.clicked.connect(self.toggle_play)
        self.play_selection_button = QPushButton("▶ 试听选区")
        self.play_selection_button.clicked.connect(self.play_selection)
        self.stop_button = QPushButton("⏹ 停止")
        self.stop_button.clicked.connect(self.stop_playback)
        self.position_label = QLabel("0:00.0 / 0:00.0")
        play_row.addWidget(self.play_button)
        play_row.addWidget(self.play_selection_button)
        play_row.addWidget(self.stop_button)
        play_row.addWidget(self.position_label)
        play_row.addStretch(1)
        layout.addLayout(play_row)

        # 选区
        select_row = QHBoxLayout()
        select_row.addWidget(QLabel("起点"))
        self.start_input = QLineEdit()
        self.start_input.setFixedWidth(90)
        self.start_input.editingFinished.connect(self.on_time_edited)
        select_row.addWidget(self.start_input)

        self.mark_start_button = QPushButton("取当前位置")
        self.mark_start_button.clicked.connect(lambda: self.mark_position("start"))
        select_row.addWidget(self.mark_start_button)

        select_row.addSpacing(16)
        select_row.addWidget(QLabel("终点"))
        self.end_input = QLineEdit()
        self.end_input.setFixedWidth(90)
        self.end_input.editingFinished.connect(self.on_time_edited)
        select_row.addWidget(self.end_input)

        self.mark_end_button = QPushButton("取当前位置")
        self.mark_end_button.clicked.connect(lambda: self.mark_position("end"))
        select_row.addWidget(self.mark_end_button)

        select_row.addSpacing(16)
        self.reset_button = QPushButton("重置为全曲")
        self.reset_button.clicked.connect(self.reset_selection)
        select_row.addWidget(self.reset_button)
        select_row.addStretch(1)
        layout.addLayout(select_row)

        self.length_label = QLabel("")
        self.length_label.setStyleSheet("color: #1C7ED6; font-weight: bold;")
        layout.addWidget(self.length_label)

        layout.addStretch(1)

        # 保存
        save_row = QHBoxLayout()
        self.overwrite_checkbox = QCheckBox("覆盖原文件")
        self.overwrite_checkbox.toggled.connect(self.update_target_preview)
        save_row.addWidget(self.overwrite_checkbox)

        self.target_label = QLabel("")
        self.target_label.setStyleSheet("color: #6b7280;")
        save_row.addWidget(self.target_label)
        save_row.addStretch(1)

        self.save_button = QPushButton("保存")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        save_row.addWidget(self.cancel_button)
        save_row.addWidget(self.save_button)
        layout.addLayout(save_row)

        self.status_label = QLabel("正在读取音频信息...")
        self.status_label.setStyleSheet("color: #6b7280;")
        layout.addWidget(self.status_label)

        self.start_input.setText(format_time(0.0))
        self.end_input.setText(format_time(0.0))

    # ---------- 加载 ----------

    def _start_loading(self) -> None:
        self.duration_worker = DurationWorker(self.audio_path)
        self.duration_worker.ready.connect(self.on_duration_ready)
        self.duration_worker.failed.connect(self.on_duration_failed)
        self.duration_worker.start()

    def on_duration_ready(self, duration: float) -> None:
        self.duration = duration
        self.waveform.set_duration(duration)
        self.position_label.setText(f"0:00.0 / {format_time(duration)}")
        self.status_label.setText(f"时长 {format_time(duration)}")
        self.update_target_preview()
        self._start_waveform()

    def on_duration_failed(self, message: str) -> None:
        self.status_label.setText(f"读取失败: {message}")
        self.waveform.set_status("无法读取音频")
        self.save_button.setEnabled(False)

    def _start_waveform(self) -> None:
        self.waveform.set_status("正在生成波形...")
        self._waveform_worker = WaveformWorker(
            self.audio_path, self.waveform.width(), self.waveform.height()
        )
        self._waveform_worker.ready.connect(self.waveform.set_waveform)
        self._waveform_worker.failed.connect(self.waveform.set_status)
        self._waveform_worker.start()

    # ---------- 选区联动 ----------

    def on_selection_changed(self, start: float, end: float) -> None:
        self.start_input.setText(format_time(start))
        self.end_input.setText(format_time(end))
        length = end - start
        self.length_label.setText(
            f"保留 {format_time(length)}（{length:.1f} 秒）"
            if length >= MIN_CLIP_SECONDS
            else f"⚠ 选区过短（至少 {MIN_CLIP_SECONDS} 秒）"
        )

    def on_time_edited(self) -> None:
        start = parse_time(self.start_input.text())
        end = parse_time(self.end_input.text())
        if start is None or end is None or self.duration <= 0:
            self.on_selection_changed(*self.waveform.selection())
            return
        self.waveform.set_selection(start, end)

    def mark_position(self, which: str) -> None:
        seconds = self.player.position() / 1000.0
        start, end = self.waveform.selection()
        if which == "start":
            self.waveform.set_selection(seconds, end)
        else:
            self.waveform.set_selection(start, seconds)

    def reset_selection(self) -> None:
        self.waveform.set_selection(0.0, self.duration)

    def seek(self, seconds: float) -> None:
        self.player.setPosition(int(seconds * 1000))
        self.waveform.set_position(seconds)

    # ---------- 播放控制 ----------

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_button.setText("▶ 播放")
            return
        self._stop_at = None
        self.player.play()
        self.play_button.setText("⏸ 暂停")

    def play_selection(self) -> None:
        start, end = self.waveform.selection()
        if end - start < MIN_CLIP_SECONDS:
            QMessageBox.warning(self, "提示", "选区过短，无法试听")
            return
        self._stop_at = end
        self.player.setPosition(int(start * 1000))
        self.player.play()
        self.play_button.setText("⏸ 暂停")

    def stop_playback(self) -> None:
        self._stop_at = None
        self.player.stop()
        self.play_button.setText("▶ 播放")
        self.waveform.set_position(self.waveform.selection()[0])

    # ---------- 保存 ----------

    def current_target(self) -> Path:
        if self.overwrite_checkbox.isChecked():
            return self.audio_path
        return unique_target_path(self.audio_path)

    def update_target_preview(self) -> None:
        target = self.current_target()
        if self.overwrite_checkbox.isChecked():
            self.target_label.setText(f"⚠ 将替换原文件: {target.name}")
        else:
            self.target_label.setText(f"保存为: {target.name}")

    def save(self) -> None:
        start, end = self.waveform.selection()
        if end - start < MIN_CLIP_SECONDS:
            QMessageBox.warning(self, "提示", f"选区过短（至少要 {MIN_CLIP_SECONDS} 秒）")
            return

        target = self.current_target()
        if self.overwrite_checkbox.isChecked():
            confirmed = QMessageBox.question(
                self,
                "确认覆盖",
                f"将用剪辑结果替换原文件：\n{self.audio_path.name}\n\n"
                "原文件内容会被覆盖，此操作无法撤销。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirmed != QMessageBox.StandardButton.Yes:
                return

        self.player.stop()
        self.set_busy(True)
        self.status_label.setText("正在剪辑...")

        self._trim_worker = TrimWorker(self.audio_path, start, end, target)
        self._trim_worker.finished_signal.connect(self.on_trim_finished)
        self._trim_worker.start()

    def set_busy(self, busy: bool) -> None:
        for widget in (
            self.save_button,
            self.cancel_button,
            self.overwrite_checkbox,
            self.play_button,
            self.play_selection_button,
            self.reset_button,
        ):
            widget.setEnabled(not busy)

    def on_trim_finished(self, success: bool, message: str) -> None:
        self.set_busy(False)
        self.status_label.setText(message)
        if not success:
            QMessageBox.critical(self, "剪辑失败", message)
            return
        self.saved.emit(str(self.current_target()))
        QMessageBox.information(self, "完成", message)
        self.accept()

    # ---------- 收尾 ----------

    def closeEvent(self, event) -> None:  # noqa: N802
        self.player.stop()
        for worker in (self._waveform_worker, self._duration_worker, self._trim_worker):
            if worker is not None and worker.isRunning():
                worker.wait(3000)
        super().closeEvent(event)
