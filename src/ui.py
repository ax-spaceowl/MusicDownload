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
)

from src.config import DEFAULT_CONFIG_PATH, load_config, save_config
from src.downloader import DownloadWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube 下载并提取 AAC")
        self.resize(760, 420)
        self.config = load_config()
        self._init_ui()
        self.worker = None

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
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_input)
        folder_layout.addWidget(self.folder_button)

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

        config_label = QLabel(f"配置文件: {DEFAULT_CONFIG_PATH}")

        layout.addLayout(url_layout)
        layout.addLayout(folder_layout)
        layout.addWidget(self.download_button)
        layout.addWidget(self.download_progress)
        layout.addWidget(self.convert_progress)
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
        self.download_progress.setValue(0)
        self.convert_progress.setValue(0)
        self.status_label.setText("任务已启动...")
        self.log_output.clear()

        self.worker = DownloadWorker(url, download_root)
        self.worker.progress_changed.connect(self.download_progress.setValue)
        self.worker.conversion_progress_changed.connect(self.convert_progress.setValue)
        self.worker.status_changed.connect(self.status_label.setText)
        self.worker.log_message.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def append_log(self, message: str) -> None:
        self.log_output.append(message)

    def on_finished(self, success: bool, message: str) -> None:
        self.download_button.setEnabled(True)
        if success:
            self.status_label.setText("完成: " + message)
            QMessageBox.information(self, "完成", message)
        else:
            self.status_label.setText("失败: " + message)
            QMessageBox.critical(self, "错误", message)
