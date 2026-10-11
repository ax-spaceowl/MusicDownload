import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from musicdownload.config import ICON_PATH
from musicdownload.ui import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
