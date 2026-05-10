import pytest
pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from gui.main_window import MainWindow
from components.detection_controls import DetectionControls
from components.batch_processor import BatchProcessor
import os
from pathlib import Path

def test_main_window_init(qtbot):
    """Test if main window can be instantiated without errors."""
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "My Blueprint Maker"
    assert window.extractor is not None

def test_detection_controls_values(qtbot):
    """Test getting values from detection controls."""
    controls = DetectionControls()
    qtbot.addWidget(controls)
    
    # Check default values
    vals = controls.get_values()
    assert vals["threshold"] == 10
    assert vals["min_area"] == 100
    assert vals["layout_hint"] == "Auto"
    assert vals["show_mask"] is False
    assert vals["remove_bg"] is False
    assert vals["upscale"] == "none"

def test_batch_processor_init(qtbot):
    """Test batch processor initialization."""
    processor = BatchProcessor()
    qtbot.addWidget(processor)
    
    # Check initial UI states
    assert processor.start_batch_btn.isEnabled() is True
    assert processor.progress_bar.isVisible() is False
