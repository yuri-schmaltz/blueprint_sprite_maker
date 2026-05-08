from pathlib import Path
from core.sprite_extractor import SpriteExtractor
from core.i18n import tr
import PyQt6.QtCore as QtCore
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout,
                             QPushButton, QLineEdit, QCheckBox, QComboBox, 
                             QProgressBar, QListWidget, QFileDialog, QMessageBox)

class AIBatchWorker(QThread):
    progress_update = pyqtSignal(int)
    log_update = pyqtSignal(str)
    finished_batch = pyqtSignal(int) # Retorna qtd de arquivos processados exitosamente
    error = pyqtSignal(str)

    def __init__(self, image_files, output_path, prefix_base, padding, uniform, threshold, min_area, remove_bg, upscale):
        super().__init__()
        self.image_files = image_files
        self.output_path = output_path
        self.prefix_base = prefix_base
        self.padding = padding
        self.uniform = uniform
        self.threshold = threshold
        self.min_area = min_area
        self.remove_bg = remove_bg
        self.upscale = upscale
        self.is_running = True

    def run(self):
        processed_count = 0
        for i, img_file in enumerate(self.image_files):
            if not self.is_running:
                break
                
            try:
                temp_extractor = SpriteExtractor()
                if temp_extractor.load_image(str(img_file)):
                    sprites = temp_extractor.detect_sprites(
                        threshold=self.threshold, 
                        min_area=self.min_area, 
                        remove_bg=self.remove_bg,
                        upscale=self.upscale,
                        progress_callback=lambda msg: self.log_update.emit(f"⏳ {img_file.name}: {msg}")
                    )
            
                    if sprites:
                        sheet_name = img_file.stem
                        final_prefix = f"{self.prefix_base}_{sheet_name}"
                        
                        temp_extractor.export_sprites(
                            output_dir=str(self.output_path),
                            prefix=final_prefix,
                            padding=self.padding,
                            uniform_size=self.uniform
                        )
                        processed_count += 1
                        self.log_update.emit(f"✅ {img_file.name} -> {len(sprites)} sprites")
                    else:
                        self.log_update.emit(f"⚠️ {img_file.name}: Nenhum sprite detectado")
                else:
                    self.log_update.emit(f"❌ Erro ao carregar: {img_file.name}")
            except Exception as e:
                self.log_update.emit(f"❌ Falha em {img_file.name}: {str(e)}")
            
            self.progress_update.emit(i + 1)
            
        self.finished_batch.emit(processed_count)

    def stop(self):
        self.is_running = False

class BatchProcessor(QWidget):
    """Componente para processamento em lote de imagens"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        title = QLabel(tr("batch_title"))
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px 0;")
        layout.addWidget(title)
        
        form_group = QGroupBox(tr("batch_config_group"))
        form_layout = QFormLayout()
        form_group.setLayout(form_layout)
        
        self.batch_input_btn = QPushButton(tr("btn_select_input"))
        self.batch_input_btn.clicked.connect(self.select_batch_input)
        form_layout.addRow(tr("batch_input_label"), self.batch_input_btn)
        
        self.batch_output_btn = QPushButton(tr("btn_select_output"))
        self.batch_output_btn.clicked.connect(self.select_batch_output)
        form_layout.addRow(tr("batch_output_label"), self.batch_output_btn)
        
        self.batch_prefix = QLineEdit("sprite_lote")
        form_layout.addRow(tr("batch_prefix_label"), self.batch_prefix)
        
        self.batch_recursive = QCheckBox(tr("batch_recursive_label"))
        self.batch_recursive.setChecked(True)
        form_layout.addRow("", self.batch_recursive)
        
        self.batch_remove_bg = QCheckBox(tr("batch_remove_bg"))
        form_layout.addRow("", self.batch_remove_bg)
        
        self.batch_upscale = QComboBox()
        self.batch_upscale.addItem(tr("upscale_none"), "none")
        self.batch_upscale.addItem(tr("upscale_fsrcnn"), "fsrcnn")
        self.batch_upscale.addItem(tr("upscale_edsr"), "edsr")
        form_layout.addRow(tr("upscale_label"), self.batch_upscale)
        
        layout.addWidget(form_group)
        
        # Log de progresso
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.batch_log = QListWidget()
        layout.addWidget(QLabel(tr("batch_progress_label")))
        layout.addWidget(self.batch_log)
        
        # Botão Iniciar
        self.start_batch_btn = QPushButton(tr("btn_start_batch"))
        self.start_batch_btn.setStyleSheet("""
            background-color: #673AB7; color: white; padding: 15px; font-weight: bold; border-radius: 5px;
        """)
        self.start_batch_btn.clicked.connect(lambda: self.run_batch_processing())
        layout.addWidget(self.start_batch_btn)
        
        self.batch_input_path = None
        self.batch_output_path = None

    def select_batch_input(self):
        path = QFileDialog.getExistingDirectory(self, tr("btn_select_input"))
        if path:
            self.batch_input_path = path
            self.batch_input_btn.setText(f"📁 {Path(path).name}")

    def select_batch_output(self):
        path = QFileDialog.getExistingDirectory(self, tr("btn_select_output"))
        if path:
            self.batch_output_path = path
            self.batch_output_btn.setText(f"📁 {Path(path).name}")

    def run_batch_processing(self, threshold=10, min_area=100, padding=10, uniform=True):
        """Executa o processamento em lote"""
        if not self.batch_input_path or not self.batch_output_path:
            QMessageBox.warning(self, tr("msg_warning"), tr("batch_msg_select_folders"))
            return

        input_path = Path(self.batch_input_path)
        output_path = Path(self.batch_output_path)
        prefix_base = self.batch_prefix.text() or "sprite"
        is_recursive = self.batch_recursive.isChecked()
        
        extensions = ['*.png', '*.jpg', '*.jpeg', '*.webp', '*.bmp']
        image_files = []
        
        glob_func = input_path.rglob if is_recursive else input_path.glob
        for ext in extensions:
            image_files.extend(list(glob_func(ext)))
        
        if not image_files:
            QMessageBox.information(self, "Info", tr("batch_msg_no_images"))
            return
            
        # Desabilitar UI
        self.start_batch_btn.setEnabled(False)
        self.start_batch_btn.setText("Processando... (Aguarde)")
        self.batch_input_btn.setEnabled(False)
        self.batch_output_btn.setEnabled(False)
            
        self.batch_log.clear()
        self.batch_log.addItem(tr("batch_msg_start", len(image_files)))
        self.progress_bar.setMaximum(len(image_files))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        
        # Iniciar Thread
        self.worker = AIBatchWorker(
            image_files=image_files,
            output_path=output_path,
            prefix_base=prefix_base,
            padding=padding,
            uniform=uniform,
            threshold=threshold,
            min_area=min_area,
            remove_bg=self.batch_remove_bg.isChecked(),
            upscale=self.batch_upscale.currentData()
        )
        
        self.worker.progress_update.connect(self.on_progress_update)
        self.worker.log_update.connect(self.on_log_update)
        self.worker.finished_batch.connect(self.on_batch_finished)
        self.worker.start()

    def on_progress_update(self, value):
        self.progress_bar.setValue(value)

    def on_log_update(self, message):
        self.batch_log.addItem(message)
        self.batch_log.scrollToBottom()

    def on_batch_finished(self, processed_count):
        # Restaurar UI
        self.start_batch_btn.setEnabled(True)
        self.start_batch_btn.setText(tr("btn_start_batch"))
        self.batch_input_btn.setEnabled(True)
        self.batch_output_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        QMessageBox.information(self, "Fim", tr("batch_msg_finished", processed_count))

