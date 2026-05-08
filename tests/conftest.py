"""
Pytest Configuration - Portable fixtures for Sprite Extractor tests
"""
import pytest
import numpy as np
import cv2
from pathlib import Path
import tempfile
import shutil


@pytest.fixture
def sample_sprite_sheet():
    """Creates a simple 2x2 grid of colored squares on transparent background"""
    # 200x200 image with 4 colored squares (50x50 each) with gaps
    img = np.zeros((200, 200, 4), dtype=np.uint8)
    
    # Colors: Red, Green, Blue, Yellow (BGRA)
    colors = [
        (0, 0, 255, 255),    # Red
        (0, 255, 0, 255),    # Green
        (255, 0, 0, 255),    # Blue
        (0, 255, 255, 255),  # Yellow
    ]
    
    positions = [(10, 10), (110, 10), (10, 110), (110, 110)]
    
    for (x, y), color in zip(positions, colors):
        img[y:y+50, x:x+50] = color
    
    return img


@pytest.fixture
def sample_sprite_sheet_path(sample_sprite_sheet, tmp_path):
    """Saves the sample sprite sheet to a temp file and returns path"""
    path = tmp_path / "test_sprites.png"
    cv2.imwrite(str(path), sample_sprite_sheet)
    return str(path)


@pytest.fixture
def output_dir(tmp_path):
    """Returns a temporary output directory for exports"""
    out = tmp_path / "output"
    out.mkdir()
    return out


@pytest.fixture
def extractor():
    """Returns a fresh SpriteExtractor instance"""
    from core.sprite_extractor import SpriteExtractor
    return SpriteExtractor()
