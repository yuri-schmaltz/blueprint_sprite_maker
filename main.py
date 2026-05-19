#!/usr/bin/env python3
"""
Sprite Extractor - Aplicação para extrair sprites individuais de sprite sheets
Autor: Antigravity
Data: 2026-01-29
"""
import sys
import argparse


def main():
    """Função principal"""
    parser = argparse.ArgumentParser(
        description="Blueprint Maker - Extrator de Sprites para Projetos 3D"
    )
    parser.add_argument("path", nargs="?", help="Caminho para o sprite sheet")
    parser.add_argument(
        "--version",
        action="version",
        version="Blueprint Maker 1.1.1",
    )
    args = parser.parse_args()

    from PyQt6.QtWidgets import QApplication
    from gui.main_window import MainWindow

    app = QApplication(sys.argv)

    # Aplicar Tema Escuro Moderno
    app.setStyleSheet("""
        QMainWindow, QWidget {
            background-color: #1e1e2e;
            color: #cdd6f4;
            font-family: 'Segoe UI', 'Roboto', 'Arial';
        }
        QGroupBox {
            border: 2px solid #313244;
            border-radius: 8px;
            margin-top: 1ex;
            font-weight: bold;
            padding: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            padding: 0 5px;
            color: #89b4fa;
        }
        QPushButton {
            background-color: #313244;
            border: none;
            padding: 8px 15px;
            border-radius: 5px;
            color: #cdd6f4;
        }
        QPushButton:hover {
            background-color: #45475a;
        }
        QPushButton:pressed {
            background-color: #585b70;
        }
        QLineEdit, QSpinBox, QComboBox {
            background-color: #181825;
            border: 1px solid #313244;
            border-radius: 4px;
            padding: 5px;
            color: #cdd6f4;
        }
        QListWidget {
            background-color: #181825;
            border: 1px solid #313244;
            border-radius: 8px;
        }
        QListWidget::item:selected {
            background-color: #89b4fa;
            color: #1e1e2e;
            border-radius: 4px;
        }
        QTabWidget::pane {
            border: 1px solid #313244;
            background-color: #1e1e2e;
        }
        QTabBar::tab {
            background-color: #181825;
            padding: 10px 20px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #313244;
            color: #89b4fa;
            border-bottom: 2px solid #89b4fa;
        }
        QSlider::groove:horizontal {
            border: 1px solid #313244;
            height: 8px;
            background: #181825;
            margin: 2px 0;
            border-radius: 4px;
        }
        QSlider::handle:horizontal {
            background: #89b4fa;
            border: 1px solid #89b4fa;
            width: 18px;
            margin: -5px 0;
            border-radius: 9px;
        }
        QProgressBar {
            border: 1px solid #313244;
            border-radius: 5px;
            text-align: center;
        }
        QProgressBar::chunk {
            background-color: #89b4fa;
            width: 20px;
        }
    """)

    app.setStyle("Fusion")

    # Criar e exibir janela principal
    window = MainWindow(initial_path=args.path)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
