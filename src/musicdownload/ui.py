import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
    QTextEdit,
    QFileDialog,
    QCheckBox,
    QComboBox,
)
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl

from musicdownload.config import DEFAULT_CONFIG_PATH, load_config, save_config
from musicdownload.downloader import (
    MODE_AUDIO_ONLY,
    MODE_BUTTON_LABELS,
    MODE_LABELS,
    MODE_VIDEO_AND_AUDIO,
    MODE_VIDEO_ONLY,
    DownloadWorker,
)
from musicdownload.trim_dialog import TrimDialog
from musicdownload.updater import UpdateCheckWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube 下载并提取 AAC")
        self.resize(760, 420)
        self.config = load_config()
        self._init_ui()
        self.worker = None
        self.update_worker = None
        self.last_audio_path = None
        self.latest_version = None
        self.apply_mode_ui()
        if self.config.get("check_updates_on_startup", True):
            self.check_for_updates()

    def _init_ui(self) -> None:
        container = QWidget()
        self.setCentralWidget(container)

        layout = QVBoxLayout(container)

        url_layout = QHBoxLayout()
        url_label = QLabel("视频链接:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "粘贴 YouTube 视频链接，例如 https://www.youtube.com/watch?v=xxxx"
        )
        self.url_input.setText(
            "https://www.youtube.com/watch?v=ArzmLLtBwMU&list=RDArzmLLtBwMU&start_radio=1"
        )
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)

        folder_layout = QHBoxLayout()
        folder_label = QLabel("下载目录:")
        self.folder_input = QLineEdit()
        self.folder_input.setText(self.config.get("download_root", ""))
        self.folder_input.setPlaceholderText("选择或输入下载目录")
        self.folder_button = QPushButton("选择目录")
        self.folder_button.clicked.connect(self.select_download_folder)
        self.open_folder_button = QPushButton("打开下载目录")
        self.open_folder_button.clicked.connect(self.open_download_folder)
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_input)
        folder_layout.addWidget(self.folder_button)
        folder_layout.addWidget(self.open_folder_button)

        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("下载内容:"))
        self.mode_combo = QComboBox()
        for value in (MODE_VIDEO_AND_AUDIO, MODE_VIDEO_ONLY, MODE_AUDIO_ONLY):
            self.mode_combo.addItem(MODE_LABELS[value], value)
        saved_mode = self.config.get("download_mode", MODE_VIDEO_AND_AUDIO)
        saved_index = self.mode_combo.findData(saved_mode)
        if saved_index >= 0:
            self.mode_combo.setCurrentIndex(saved_index)
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        self.mode_hint_label = QLabel("")
        self.mode_hint_label.setStyleSheet("color: #6b7280;")
        mode_layout.addWidget(self.mode_hint_label)
        mode_layout.addStretch(1)

        self.download_button = QPushButton("下载并提取 AAC")
        self.download_button.clicked.connect(self.start_download)

        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setFormat("下载: %p%")

        self.convert_progress = QProgressBar()
        self.convert_progress.setRange(0, 100)
        self.convert_progress.setFormat("转换: %p%")

        self.status_label = QLabel("准备就绪")

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText(
            "日志输出会显示下载和转换过程中的信息"
        )

        update_layout = QHBoxLayout()
        self.update_checkbox = QCheckBox("启动时自动检查 yt-dlp 更新")
        self.update_checkbox.setChecked(
            bool(self.config.get("check_updates_on_startup", True))
        )
        self.update_checkbox.toggled.connect(self.on_update_checkbox_toggled)
        self.update_button = QPushButton("立即检查更新")
        self.update_button.clicked.connect(lambda: self.check_for_updates(force=True))
        self.update_label = QLabel("")
        self.update_help_button = QPushButton("查看更新方法")
        self.update_help_button.setVisible(False)
        self.update_help_button.clicked.connect(self.show_update_help)
        update_layout.addWidget(self.update_checkbox)
        update_layout.addWidget(self.update_button)
        update_layout.addWidget(self.update_label)
        update_layout.addWidget(self.update_help_button)
        update_layout.addStretch(1)

        config_label = QLabel(f"配置文件: {DEFAULT_CONFIG_PATH}")

        trim_layout = QHBoxLayout()
        self.trim_button = QPushButton("剪辑音频")
        self.trim_button.setEnabled(False)
        self.trim_button.clicked.connect(self.open_trim_dialog)
        self.auto_trim_checkbox = QCheckBox("下载完成后自动打开剪辑")
        self.auto_trim_checkbox.setChecked(bool(self.config.get("auto_open_trim", True)))
        self.auto_trim_checkbox.toggled.connect(self.on_auto_trim_toggled)
        trim_layout.addWidget(self.trim_button)
        trim_layout.addWidget(self.auto_trim_checkbox)
        trim_layout.addStretch(1)

        layout.addLayout(url_layout)
        layout.addLayout(folder_layout)
        layout.addLayout(update_layout)
        layout.addLayout(mode_layout)
        layout.addWidget(self.download_button)
        layout.addWidget(self.download_progress)
        layout.addWidget(self.convert_progress)
        layout.addLayout(trim_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.log_output)
        layout.addWidget(config_label)

    def select_download_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择下载目录",
            self.folder_input.text() or str(Path.home()),
            QFileDialog.Option.ShowDirsOnly,
        )
        if selected:
            self.folder_input.setText(selected)
            self.config["download_root"] = selected
            save_config(self.config)
            self.log_output.append(f"已保存默认下载目录: {selected}")

    def open_download_folder(self) -> None:
        path = self.folder_input.text().strip() or self.config.get("download_root", "")
        if not path:
            QMessageBox.warning(self, "提示", "未配置下载目录")
            return
        p = Path(path)
        if not p.exists():
            QMessageBox.warning(self, "提示", "下载目录不存在: " + str(p))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def on_update_checkbox_toggled(self, checked: bool) -> None:
        self.config["check_updates_on_startup"] = bool(checked)
        save_config(self.config)

    def check_for_updates(self, force: bool = False) -> None:
        """在后台线程检查 yt-dlp 更新，不阻塞界面。

        force=True 时忽略 24 小时缓存（用户手动点击）。
        """
        if self.update_worker is not None and self.update_worker.isRunning():
            return

        self.update_button.setEnabled(False)
        self.update_help_button.setVisible(False)
        self.update_label.setStyleSheet("color: #6b7280;")
        self.update_label.setText("正在检查 yt-dlp 更新...")

        self.update_worker = UpdateCheckWorker(force=force)
        self.update_worker.check_finished.connect(self.on_update_check_finished)
        self.update_worker.check_failed.connect(self.on_update_check_failed)
        self.update_worker.start()

    def on_update_check_finished(
        self, installed: str, latest: str, has_update: bool, from_cache: bool
    ) -> None:
        self.update_button.setEnabled(True)
        suffix = "（缓存）" if from_cache else ""

        if has_update:
            self.latest_version = latest
            self.update_label.setStyleSheet("color: #d97706; font-weight: bold;")
            self.update_label.setText(f"发现新版本 {latest}（当前 {installed}）")
            self.update_help_button.setVisible(True)
            self.append_log(f"yt-dlp 有新版本可用: {latest}（当前 {installed}）{suffix}")
            # 缓存命中时不重复弹窗，避免每次启动都打扰
            if not from_cache:
                QMessageBox.information(
                    self,
                    "发现 yt-dlp 新版本",
                    f"当前版本: {installed}\n最新版本: {latest}\n\n"
                    "建议先升级再下载，否则部分站点可能返回 HTTP 412 等错误。",
                )
        else:
            self.latest_version = None
            self.update_label.setStyleSheet("color: #16a34a;")
            self.update_label.setText(f"yt-dlp 已是最新版本（{installed}）")
            self.append_log(f"yt-dlp 已是最新版本: {installed}{suffix}")

    def on_update_check_failed(self, message: str) -> None:
        self.update_button.setEnabled(True)
        self.update_label.setStyleSheet("color: #6b7280;")
        self.update_label.setText("检查更新失败（不影响下载）")
        self.append_log(f"检查 yt-dlp 更新失败: {message}")

    def show_update_help(self) -> None:
        command = f"{sys.executable} -m pip install -U yt-dlp"
        QMessageBox.information(
            self,
            "更新 yt-dlp",
            f"在终端执行以下命令即可升级到 {self.latest_version or '最新版'}：\n\n"
            f"{command}\n\n"
            "如果访问 pypi.org 较慢，可追加国内镜像：\n"
            "-i https://pypi.tuna.tsinghua.edu.cn/simple\n\n"
            "升级完成后重启本程序。",
        )

    def start_download(self) -> None:
        url = self.url_input.text().strip()
        download_root = self.folder_input.text().strip()

        if not url:
            QMessageBox.warning(self, "提示", "请输入视频链接")
            return
        if not download_root:
            QMessageBox.warning(self, "提示", "请选择下载目录")
            return

        self.config["download_root"] = download_root
        save_config(self.config)

        self.download_button.setEnabled(False)
        self.mode_combo.setEnabled(False)
        self.download_progress.setValue(0)
        self.convert_progress.setValue(0)
        self.status_label.setText("任务已启动...")
        self.log_output.clear()

        self.worker = DownloadWorker(url, download_root, mode=self.current_mode())
        self.worker.progress_changed.connect(self.download_progress.setValue)
        self.worker.conversion_progress_changed.connect(self.convert_progress.setValue)
        self.worker.status_changed.connect(self.status_label.setText)
        self.worker.log_message.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def append_log(self, message: str) -> None:
        self.log_output.append(message)

    def on_auto_trim_toggled(self, checked: bool) -> None:
        self.config["auto_open_trim"] = bool(checked)
        save_config(self.config)

    def current_mode(self) -> str:
        return self.mode_combo.currentData() or MODE_VIDEO_AND_AUDIO

    def on_mode_changed(self) -> None:
        self.config["download_mode"] = self.current_mode()
        save_config(self.config)
        self.apply_mode_ui()

    def apply_mode_ui(self) -> None:
        """按当前下载模式刷新按钮文字、进度条与提示。"""
        mode = self.current_mode()
        self.download_button.setText(MODE_BUTTON_LABELS.get(mode, "下载并提取 AAC"))
        self.convert_progress.setEnabled(mode != MODE_VIDEO_ONLY)
        if mode == MODE_VIDEO_ONLY:
            self.convert_progress.setValue(0)
            self.mode_hint_label.setText("只保存视频到 videos/，不做音频转换")
        elif mode == MODE_AUDIO_ONLY:
            self.mode_hint_label.setText("只下载音频流，转换完成后删除源文件")
        else:
            self.mode_hint_label.setText("视频存入 videos/，音频存入 audios/")

    def open_trim_dialog(self) -> None:
        if not self.last_audio_path:
            QMessageBox.warning(self, "提示", "还没有可剪辑的音频，请先下载一个视频")
            return

        path = Path(self.last_audio_path)
        if not path.exists():
            QMessageBox.warning(self, "提示", f"音频文件不存在: {path}")
            return

        dialog = TrimDialog(path, self)
        dialog.saved.connect(self.on_trim_saved)
        dialog.exec()

    def on_trim_saved(self, path: str) -> None:
        self.last_audio_path = path
        self.append_log(f"已保存剪辑结果: {path}")
        self.status_label.setText(f"剪辑完成: {Path(path).name}")

    def on_finished(self, success: bool, message: str) -> None:
        self.mode_combo.setEnabled(True)
        self.download_button.setEnabled(True)
        if success:
            self.status_label.setText("完成: " + message)
            self.append_log(message)

            audio_path = getattr(self.worker, "audio_path", None)
            if audio_path and Path(audio_path).exists():
                self.last_audio_path = audio_path
                self.trim_button.setEnabled(True)
                self.append_log(f"可剪辑音频: {audio_path}")
                if self.auto_trim_checkbox.isChecked():
                    self.open_trim_dialog()
                    return

            QMessageBox.information(self, "完成", message)
        else:
            self.status_label.setText("失败: " + message)
            QMessageBox.critical(self, "错误", message)
