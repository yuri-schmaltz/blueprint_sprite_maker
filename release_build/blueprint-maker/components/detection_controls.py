from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout, QSlider, QComboBox, QHBoxLayout, QCheckBox, QPushButton, QSpinBox
from core.i18n import tr
from PyQt6.QtCore import Qt, pyqtSignal

class DetectionControls(QGroupBox):
    """Componente para os controles de detecção de sprites"""
    params_changed = pyqtSignal()
    threshold_changed = pyqtSignal(int)
    detect_requested = pyqtSignal()
    
    def __init__(self, title="Parâmetros de Detecção", parent=None):
        super().__init__(title, parent)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        form_layout = QFormLayout()
        
        # Threshold slider
        threshold_container = QHBoxLayout()
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setMinimum(1)
        self.threshold_slider.setMaximum(255)
        self.threshold_slider.setValue(10)
        self.threshold_slider.valueChanged.connect(self._on_threshold_changed)
        
        self.threshold_value_label = QLabel("10")
        threshold_container.addWidget(self.threshold_slider)
        threshold_container.addWidget(self.threshold_value_label)
        form_layout.addRow(tr("detection_threshold"), threshold_container)
        
        # Área mínima
        self.min_area_spinbox = QSpinBox()
        self.min_area_spinbox.setMinimum(10)
        self.min_area_spinbox.setMaximum(1000000)
        self.min_area_spinbox.setValue(100)
        self.min_area_spinbox.setSuffix(" px²")
        self.min_area_spinbox.valueChanged.connect(lambda: self.params_changed.emit())
        form_layout.addRow(tr("detection_min_area"), self.min_area_spinbox)
        
        # Layout Preset
        self.layout_combo = QComboBox()
        self.layout_combo.addItems([
            tr("layout_auto"), 
            tr("layout_3x2"), 
            tr("layout_2x3"), 
            tr("layout_2x2")
        ])
        self.layout_combo.currentIndexChanged.connect(lambda: self.params_changed.emit())
        form_layout.addRow(tr("detection_layout"), self.layout_combo)
        
        layout.addLayout(form_layout)
        
        # Checkbox para mostrar máscara
        self.show_mask = QCheckBox(tr("detection_show_mask"))
        self.show_mask.toggled.connect(lambda: self.params_changed.emit())
        layout.addWidget(self.show_mask)
        
        # Advanced options group
        adv_group = QGroupBox(tr("detection_advanced_options"))
        adv_layout = QFormLayout()
        adv_group.setLayout(adv_layout)
        layout.addWidget(adv_group)

        # Checkbox para remover fundo
        self.remove_bg = QCheckBox(tr("detection_remove_bg"))
        self.remove_bg.stateChanged.connect(self.params_changed.emit)
        adv_layout.addRow("", self.remove_bg)
        
        self.upscale = QComboBox()
        self.upscale.addItem(tr("upscale_none"), "none")
        self.upscale.addItem(tr("upscale_fsrcnn"), "fsrcnn")
        self.upscale.addItem(tr("upscale_edsr"), "edsr")
        self.upscale.currentIndexChanged.connect(self.params_changed.emit)
        adv_layout.addRow(tr("upscale_label"), self.upscale)
        
        # Botão detectar
        self.detect_btn = QPushButton(tr("btn_detect_sprites"))
        self.detect_btn.setEnabled(False)
        self.detect_btn.setStyleSheet("""
            QPushButton {
                padding: 10px;
                font-size: 14px;
                background-color: #2196F3;
                color: white;
                border-radius: 5px;
            }
            QPushButton:hover:enabled {
                background-color: #0b7dda;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self.detect_btn.clicked.connect(lambda: self.detect_requested.emit())
        layout.addWidget(self.detect_btn)

    def _on_threshold_changed(self, value):
        self.threshold_value_label.setText(str(value))
        self.threshold_changed.emit(value)
        self.params_changed.emit()

    def get_values(self):
        return {
            "threshold": self.threshold_slider.value(),
            "min_area": self.min_area_spinbox.value(),
            "layout_hint": self.layout_combo.currentText(),
            "show_mask": self.show_mask.isChecked(),
            "remove_bg": self.remove_bg.isChecked(),
            "upscale": self.upscale.currentData()
        }
