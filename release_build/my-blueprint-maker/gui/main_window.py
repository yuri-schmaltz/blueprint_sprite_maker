"""
Main Window - Interface gráfica principal do My Blueprint Maker.

Thread Safety:
    A MainWindow cria AIDetectionWorker threads para processamento de IA.
    O SpriteExtractor é compartilhado entre a main thread e o worker.
    A UI é desabilitada durante o processamento para prevenir mutações
    concorrentes no estado do extractor.
"""
import logging
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QMessageBox, QFileDialog, QTabWidget, QComboBox,
    QPushButton, QCheckBox, QProgressDialog
)
from PyQt6.QtCore import Qt, QFileSystemWatcher, QSettings, QThread, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut, QIcon
from core.i18n import tr
from pathlib import Path
import cv2

logger = logging.getLogger(__name__)

from core.sprite_extractor import SpriteExtractor, ImageLoadError
from components.image_viewer import ImageViewer
from components.detection_controls import DetectionControls
from components.sprite_list import SpriteList
from components.batch_processor import BatchProcessor

class AIDetectionWorker(QThread):
    """Worker thread para detecção de sprites com IA.

    Thread Safety (Isolation by Copy):
        O worker recebe uma CÓPIA da imagem original e cria seu próprio
        SpriteExtractor isolado. Nenhum estado mutável é compartilhado
        com a main thread. Os resultados (sprites, processed_image,
        binary_mask) são enviados de volta via signal e aplicados ao
        extractor principal apenas na main thread.
    """
    finished = pyqtSignal(object)  # dict com sprites + state
    error = pyqtSignal(str)
    status_update = pyqtSignal(str)

    def __init__(self, image_copy, params):
        super().__init__()
        self.image_copy = image_copy  # Deep copy — sem referência compartilhada
        self.params = params

    def run(self):
        try:
            # Criar extractor isolado na worker thread
            worker_extractor = SpriteExtractor()
            worker_extractor.original_image = self.image_copy
            worker_extractor.processed_image = self.image_copy.copy()

            layout_hint = None
            if "3x2" in self.params["layout_hint"]: layout_hint = "3x2"
            elif "2x3" in self.params["layout_hint"]: layout_hint = "2x3"
            elif "2x2" in self.params["layout_hint"]: layout_hint = "2x2"
            
            sprites = worker_extractor.detect_sprites(
                threshold=self.params["threshold"], 
                min_area=self.params["min_area"], 
                layout_hint=layout_hint,
                remove_bg=self.params.get("remove_bg", False),
                upscale=self.params.get("upscale", "none"),
                progress_callback=lambda msg: self.status_update.emit(msg)
            )

            # Emitir resultados completos para a main thread sincronizar
            self.finished.emit({
                "sprites": sprites,
                "processed_image": worker_extractor.processed_image,
                "binary_mask": worker_extractor.get_binary_mask_preview(),
            })
        except (cv2.error, ValueError, RuntimeError, OSError) as e:
            logger.error("Falha na detecção de sprites: %s", e, exc_info=True)
            self.error.emit(str(e))

class MainWindow(QMainWindow):
    """Janela principal da aplicação"""
    
    def __init__(self, initial_path=None):
        super().__init__()
        self.extractor = SpriteExtractor()
        self.selected_sprite_index = -1
        self.watcher = QFileSystemWatcher()
        self.watcher.fileChanged.connect(self.on_file_updated)
        
        self.settings = QSettings("MyBlueprintMaker", "MyBlueprintMaker")
        self.last_dir = str(Path.home()) # Default value, will be overridden by load_settings
        
        self.init_ui()
        self.load_settings()
        self.setAcceptDrops(True)
        
        if initial_path:
            self.load_image(initial_path)
        
    def init_ui(self):
        self.setWindowTitle(tr("app_title"))
        self.setMinimumSize(1200, 800)
        self.setAcceptDrops(True)
        
        icon_path = Path(__file__).parent / "resources" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Aba 1: Extrator Individual
        single_tab = QWidget()
        single_layout = QHBoxLayout(single_tab)
        
        # Viewer
        self.image_viewer = ImageViewer()
        self.image_viewer.file_dropped.connect(self.load_image)
        self.image_viewer.sprite_clicked.connect(self.on_sprite_selected)
        self.image_viewer.delete_requested.connect(self.on_delete_sprite)
        self.image_viewer.merge_requested.connect(self.on_merge_sprites)
        single_layout.addWidget(self.image_viewer, stretch=3)
        
        # Painel de Controles
        self.controls_panel = QWidget()
        controls_layout = QVBoxLayout(self.controls_panel)
        
        self.load_btn = self._create_styled_button(tr("btn_load_image"), "#4CAF50")
        self.load_btn.clicked.connect(self.load_image)
        controls_layout.addWidget(self.load_btn)
        
        self.detection_controls = DetectionControls()
        self.detection_controls.params_changed.connect(self.detect_sprites)
        self.detection_controls.detect_requested.connect(self.detect_sprites)
        controls_layout.addWidget(self.detection_controls)
        
        self.sprite_list = SpriteList()
        self.sprite_list.sprite_selected.connect(self.on_sprite_selected)
        controls_layout.addWidget(QLabel(tr("label_detected_sprites")))
        controls_layout.addWidget(self.sprite_list)
        
        self.export_btn = self._create_styled_button(tr("btn_export_sprites"), "#FF9800")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_sprites)
        controls_layout.addWidget(self.export_btn)
        
        controls_layout.addStretch()
        single_layout.addWidget(self.controls_panel, stretch=1)
        
        self.tabs.addTab(single_tab, tr("tab_individual"))
        
        # Aba 2: Lote
        self.batch_processor = BatchProcessor()
        self.tabs.addTab(self.batch_processor, tr("tab_batch"))
        
        # Aba 3: 3D
        self.preview_3d_container = QWidget()
        self.preview_3d_layout = QVBoxLayout(self.preview_3d_container)
        
        # Controles 3D
        controls_3d = QVBoxLayout()
        shapes_layout = QHBoxLayout()
        self.body_combo = QComboBox()
        self.body_combo.addItems([tr("view_cube"), tr("view_cylinder"), tr("view_plane")])
        self.body_combo.currentIndexChanged.connect(self.on_body_type_changed)
        shapes_layout.addWidget(QLabel(tr("label_shape")))
        shapes_layout.addWidget(self.body_combo)
        
        self.auto_rotate_check = QCheckBox(tr("label_auto_rotate"))
        self.auto_rotate_check.toggled.connect(self.on_auto_rotate_toggled)
        shapes_layout.addWidget(self.auto_rotate_check)
        shapes_layout.addStretch()
        controls_3d.addLayout(shapes_layout)
        
        # Botões de Vista (Presets)
        views_layout = QHBoxLayout()
        views_layout.addWidget(QLabel(tr("label_view")))
        
        view_presets = [
            (tr("view_front"), "front"), (tr("view_back"), "back"), 
            (tr("view_left"), "left"), (tr("view_right"), "right"), 
            (tr("view_top"), "top"), (tr("view_bottom"), "bottom")
        ]
        
        for label, view_id in view_presets:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, v=view_id: self.on_view_preset_clicked(v))
            views_layout.addWidget(btn)
        
        views_layout.addStretch()
        controls_3d.addLayout(views_layout)
        
        self.preview_3d_layout.addLayout(controls_3d)
        
        self.preview_3d_tab = None
        self.tabs.addTab(self.preview_3d_container, tr("tab_3d"))
        
        # Atalhos
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(self.detect_sprites)
        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(self.export_sprites)
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self.load_image)
        
        self.tabs.currentChanged.connect(self.on_tab_changed)

    def _create_styled_button(self, text, color):
        btn = QPushButton(text)
        style = """
            QPushButton {
                background-color: %COLOR%; 
                color: white; 
                padding: 12px; 
                font-weight: bold; 
                border-radius: 6px;
                border: 1px solid rgba(0,0,0,0.1);
            }
            QPushButton:hover { background-color: %HOVER_COLOR%; }
            QPushButton:pressed { background-color: %PRESSED_COLOR%; }
            QPushButton:disabled { background-color: #313244; color: #585b70; }
        """
        
        # Cores para tema escuro
        hover_color = self._get_hover_color(color)
        pressed_color = self._get_pressed_color(color)
        
        btn.setStyleSheet(style.replace("%COLOR%", color).replace("%HOVER_COLOR%", hover_color).replace("%PRESSED_COLOR%", pressed_color))
        return btn

    def _get_hover_color(self, hex_color):
        # Ajuste simples para hover (mais escuro no tema escuro)
        if hex_color == "#4CAF50": return "#388E3C" # Green
        if hex_color == "#FF9800": return "#F57C00" # Orange
        return hex_color

    def _get_pressed_color(self, hex_color):
        if hex_color == "#4CAF50": return "#2E7D32" 
        if hex_color == "#FF9800": return "#EF6C00"
        return hex_color

    def load_settings(self):
        self.last_dir = self.settings.value("last_dir", str(Path.home()))
        state = self.settings.value("window_state")
        if state:
            self.restoreState(state)
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def save_settings(self):
        self.settings.setValue("last_dir", self.last_dir)
        self.settings.setValue("window_state", self.saveState())
        self.settings.setValue("window_geometry", self.saveGeometry())

    def closeEvent(self, event):
        self.save_settings()
        super().closeEvent(event)

    def load_image(self, file_path=None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(self, tr("select_image_title"), self.last_dir, tr("image_filters"))
        
        if file_path:
            try:
                self.last_dir = str(Path(file_path).parent)
                self.settings.setValue("last_dir", self.last_dir)
                self.extractor.load_image(file_path)
                self.watcher.addPath(str(file_path))
                self.detect_sprites()
                self.detection_controls.detect_btn.setEnabled(True)
            except ImageLoadError as e:
                QMessageBox.critical(self, "Erro", str(e))

    def detect_sprites(self):
        if self.extractor.original_image is None:
            return
            
        params = self.detection_controls.get_values()
        
        # Desabilitar UI durante processamento — barreira de thread safety
        self.detection_controls.setEnabled(False)
        self.load_btn.setEnabled(False)
        self.detection_controls.detect_btn.setText("Processando...")
        self.sprite_list.clear()
        
        # Deep copy da imagem para o worker — isolamento completo de estado
        image_copy = self.extractor.original_image.copy()
        
        # Iniciar Thread de Processamento com dados isolados
        self.worker = AIDetectionWorker(image_copy, params)
        self.worker.finished.connect(self.on_detection_finished)
        self.worker.error.connect(self.on_detection_error)
        self.worker.status_update.connect(lambda msg: self.detection_controls.detect_btn.setText(msg))
        self.worker.start()

    def on_detection_finished(self, result):
        """Sincroniza os resultados do worker de volta ao extractor principal.
        
        Este método roda na main thread — é seguro acessar o extractor aqui.
        """
        # Restaurar UI
        self.detection_controls.detect_btn.setText(tr("btn_detect_sprites"))
        self.detection_controls.setEnabled(True)
        self.load_btn.setEnabled(True)
        
        # Sincronizar estado do worker para o extractor principal (main thread only)
        sprites = result["sprites"]
        self.extractor.sprites = sprites
        self.extractor.processed_image = result["processed_image"]
        self.extractor._last_binary_mask = result["binary_mask"]
        
        self.sprite_list.update_list(sprites, self.selected_sprite_index)
        self.update_display()
        self.export_btn.setEnabled(len(sprites) > 0)

    def on_detection_error(self, err_msg):
        self.detection_controls.detect_btn.setText(tr("btn_detect_sprites"))
        self.detection_controls.setEnabled(True)
        self.load_btn.setEnabled(True)
        QMessageBox.critical(self, tr("msg_error"), f"Erro no processamento: {err_msg}")

    def update_display(self):
        """Atualiza a imagem exibida com os bounding boxes"""
        if self.extractor.original_image is not None:
            if self.detection_controls.get_values()["show_mask"]:
                mask = self.extractor.get_binary_mask_preview()
                self.image_viewer.display_image(mask)
            else:
                preview = self.extractor.get_preview_image(
                    selected_index=self.selected_sprite_index,
                    multi_selected=self.image_viewer.multi_selected_indices
                )
                self.image_viewer.display_image(preview, self.extractor.sprites, self.selected_sprite_index)

    def on_sprite_selected(self, index, is_multi=False):
        if is_multi and index != -1:
            if index in self.image_viewer.multi_selected_indices:
                self.image_viewer.multi_selected_indices.remove(index)
            else:
                self.image_viewer.multi_selected_indices.append(index)
            self.selected_sprite_index = -1
        else:
            self.selected_sprite_index = index
            self.image_viewer.multi_selected_indices = [index] if index != -1 else []
            
        self.update_display()
        
    def on_delete_sprite(self, index):
        if self.extractor.delete_sprite(index):
            self.selected_sprite_index = -1
            self.image_viewer.multi_selected_indices = []
            self.sprite_list.update_list(self.extractor.sprites, -1)
            self.update_display()
            self.export_btn.setEnabled(len(self.extractor.sprites) > 0)
            
    def on_merge_sprites(self, indices):
        if self.extractor.merge_sprites(indices):
            self.selected_sprite_index = -1
            self.image_viewer.multi_selected_indices = []
            self.sprite_list.update_list(self.extractor.sprites, -1)
            self.update_display()

    def on_file_updated(self, path):
        try:
            self.extractor.load_image(path)
            self.detect_sprites()
            if self.tabs.currentIndex() == 2:
                self.sync_3d_preview()
        except ImageLoadError as e:
            logger.warning("Falha silenciosa ao recarregar %s: %s", path, e)

    def on_tab_changed(self, index):
        if index == 2: # 3D
            if self.preview_3d_tab is None:
                from core.preview_3d import SpritePreview3D
                self.preview_3d_tab = SpritePreview3D()
                self.preview_3d_layout.insertWidget(0, self.preview_3d_tab)
                # Aplicar estados iniciais
                self.on_body_type_changed(self.body_combo.currentIndex())
                self.on_auto_rotate_toggled(self.auto_rotate_check.isChecked())
            self.sync_3d_preview()

    def on_body_type_changed(self, index):
        if self.preview_3d_tab:
            types = ["cube", "cylinder", "plane"]
            self.preview_3d_tab.body_type = types[index]
            self.preview_3d_tab.update()

    def on_auto_rotate_toggled(self, checked):
        if self.preview_3d_tab:
            self.preview_3d_tab.auto_rotate = checked

    def on_view_preset_clicked(self, view_id):
        if self.preview_3d_tab:
            self.preview_3d_tab.set_camera_preset(view_id)
            self.auto_rotate_check.setChecked(False)

    def sync_3d_preview(self):
        if self.preview_3d_tab and self.extractor.sprites:
            self.preview_3d_tab.set_sprites(self.extractor.sprites)

    def export_sprites(self):
        """Exporta os sprites detectados para a pasta de origem da imagem"""
        if not self.extractor.sprites or not self.extractor.image_path:
            QMessageBox.warning(self, tr("msg_warning"), tr("msg_no_sprites"))
            return
            
        try:
            # Exportar automaticamente para a pasta de origem como solicitado pelo usuário
            output_dir = Path(self.extractor.image_path).parent
            self.extractor.export_sprites(
                output_dir=str(output_dir), 
                prefix="sprite", 
                format="png"
            )
            
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle(tr("msg_success"))
            box.setText(f"{len(self.extractor.sprites)} sprites exportados para:\n{output_dir}")
            
            open_folder_btn = box.addButton("📂 Abrir Pasta", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Ok)
            
            box.exec()
            
            if box.clickedButton() == open_folder_btn:
                import os
                import platform
                if platform.system() == "Windows":
                    os.startfile(output_dir)
                elif platform.system() == "Darwin":
                    os.system(f'open "{output_dir}"')
                else:
                    os.system(f'xdg-open "{output_dir}"')

        except Exception as e:
            QMessageBox.critical(self, tr("msg_error"), tr("msg_export_fail", str(e)))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path:
                    p = Path(file_path)
                    if p.is_file():
                        self.tabs.setCurrentIndex(0)
                        self.load_image(file_path)
                    elif p.is_dir():
                        self.tabs.setCurrentIndex(1)
                        self.batch_processor.batch_input_path = file_path
                        self.batch_processor.batch_input_btn.setText(f"📁 {p.name}")
                    break
            event.acceptProposedAction()
        else:
            event.ignore()
