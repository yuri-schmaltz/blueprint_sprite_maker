"""
Testes para os componentes GUI (PyQt6).
Requer as dependências 'PyQt6' e 'pytest-qt' instaladas.
Se não estiverem disponíveis, estes testes serão pulados automaticamente.
"""
import pytest
from unittest.mock import MagicMock

# Pular o arquivo inteiro se PyQt6 não estiver instalado
pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from components.detection_controls import DetectionControls
from components.batch_processor import BatchProcessor
from components.sprite_list import SpriteList
from core.sprite_extractor import Sprite


def test_detection_controls_default_values(qtbot):
    """Verifica se os controles iniciam com os valores padrão corretos."""
    controls = DetectionControls()
    qtbot.addWidget(controls)
    
    vals = controls.get_values()
    assert vals["threshold"] == 10
    assert vals["min_area"] == 100
    assert vals["layout_hint"] == "Auto"
    assert vals["show_mask"] is False
    assert vals["remove_bg"] is False
    assert vals["upscale"] == "none"

def test_detection_controls_signal_emission(qtbot):
    """Verifica se a mudança de parâmetros emite o sinal corretamente."""
    controls = DetectionControls()
    qtbot.addWidget(controls)
    
    with qtbot.waitSignal(controls.params_changed, timeout=1000):
        controls.threshold_slider.setValue(50)
        
    vals = controls.get_values()
    assert vals["threshold"] == 50

def test_batch_processor_ui_state(qtbot):
    """Verifica o estado inicial da UI do processador em lote."""
    processor = BatchProcessor()
    qtbot.addWidget(processor)
    
    assert processor.start_batch_btn.isEnabled() is True
    assert processor.progress_bar.isVisible() is False
    assert processor.stop_btn.isVisible() is False

def test_batch_processor_add_files(qtbot):
    """Verifica se a adição de arquivos atualiza a lista."""
    processor = BatchProcessor()
    qtbot.addWidget(processor)
    
    # Mock do QFileDialog para simular seleção de arquivos
    mock_paths = ["/tmp/test1.png", "/tmp/test2.png"]
    processor._get_open_file_names = MagicMock(return_value=mock_paths)
    
    # Substituir a chamada original que abre o dialog
    import sys
    processor.add_files_btn.clicked.disconnect()
    processor.add_files_btn.clicked.connect(lambda: processor._add_files_mock(mock_paths))
    
    def _add_files_mock(paths):
        for p in paths:
            if p not in processor.image_files:
                processor.image_files.append(p)
                processor.file_list.addItem(p)
                
    processor._add_files_mock = _add_files_mock
    
    processor.add_files_btn.click()
    
    assert len(processor.image_files) == 2
    assert processor.file_list.count() == 2

def test_sprite_list_update(qtbot):
    """Verifica se a lista de sprites renderiza os itens corretamente."""
    sprite_list = SpriteList()
    qtbot.addWidget(sprite_list)
    
    # Criar sprites falsos para teste (imagem vazia 10x10)
    import numpy as np
    dummy_img = np.zeros((10, 10, 4), dtype=np.uint8)
    
    sprites = [
        Sprite(bbox=(0, 0, 10, 10), image=dummy_img, index=0, view_type="front"),
        Sprite(bbox=(10, 10, 10, 10), image=dummy_img, index=1, view_type="back"),
    ]
    
    sprite_list.update_list(sprites, -1)
    
    # O QListWidget deve ter 2 itens
    assert sprite_list.count() == 2
