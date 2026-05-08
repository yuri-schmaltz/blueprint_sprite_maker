"""
Unit tests for SpriteExtractor core functionality
"""
import pytest
import numpy as np
from pathlib import Path


class TestSpriteExtractor:
    """Tests for core sprite detection and extraction"""
    
    def test_load_image_success(self, extractor, sample_sprite_sheet_path):
        """Test loading a valid image"""
        result = extractor.load_image(sample_sprite_sheet_path)
        assert result is True
        assert extractor.original_image is not None
    
    def test_load_image_invalid_path(self, extractor):
        """Test loading a non-existent file"""
        result = extractor.load_image("/nonexistent/path.png")
        assert result is False
    
    def test_detect_sprites_finds_all(self, extractor, sample_sprite_sheet_path):
        """Test that detection finds all 4 sprites in a 2x2 grid"""
        extractor.load_image(sample_sprite_sheet_path)
        sprites = extractor.detect_sprites(threshold=10, min_area=100)
        
        assert len(sprites) == 4
    
    def test_detect_sprites_correct_size(self, extractor, sample_sprite_sheet_path):
        """Test that detected sprites have reasonable dimensions"""
        extractor.load_image(sample_sprite_sheet_path)
        sprites = extractor.detect_sprites(threshold=10, min_area=100)
        
        for sprite in sprites:
            _, _, w, h = sprite.bbox
            # OpenCV contour detection may shrink bounding boxes slightly
            assert 30 <= w <= 60, f"Width {w} not in expected range"
            assert 30 <= h <= 60, f"Height {h} not in expected range"
    
    def test_get_sprite_by_index(self, extractor, sample_sprite_sheet_path):
        """Test retrieving a specific sprite by index"""
        extractor.load_image(sample_sprite_sheet_path)
        extractor.detect_sprites(threshold=10, min_area=100)
        
        sprite = extractor.get_sprite(0)
        assert sprite is not None
        assert sprite.index == 0
    
    def test_get_sprite_invalid_index(self, extractor, sample_sprite_sheet_path):
        """Test that invalid index returns None"""
        extractor.load_image(sample_sprite_sheet_path)
        extractor.detect_sprites()
        
        assert extractor.get_sprite(999) is None
        assert extractor.get_sprite(-10) is None
    
    def test_export_sprites(self, extractor, sample_sprite_sheet_path, output_dir):
        """Test exporting sprites to files"""
        extractor.load_image(sample_sprite_sheet_path)
        extractor.detect_sprites(threshold=10, min_area=100)
        
        files = extractor.export_sprites(
            output_dir=str(output_dir),
            prefix="test",
            format="png"
        )
        
        assert len(files) == 4
        for f in files:
            assert f.exists()
            assert f.suffix == ".png"
    
    def test_min_area_filter(self, extractor, sample_sprite_sheet_path):
        """Test that min_area correctly filters small regions"""
        extractor.load_image(sample_sprite_sheet_path)
        
        # With high min_area, should find nothing
        sprites = extractor.detect_sprites(threshold=10, min_area=100000)
        assert len(sprites) == 0
    
    def test_preview_image_without_boxes(self, extractor, sample_sprite_sheet_path):
        """Test generating preview without bounding boxes"""
        extractor.load_image(sample_sprite_sheet_path)
        extractor.detect_sprites()
        
        preview = extractor.get_preview_image(draw_boxes=False)
        assert preview is not None
        assert preview.shape[:2] == (200, 200)
    
    def test_preview_image_with_boxes(self, extractor, sample_sprite_sheet_path):
        """Test generating preview with bounding boxes"""
        extractor.load_image(sample_sprite_sheet_path)
        extractor.detect_sprites()
        
        preview = extractor.get_preview_image(draw_boxes=True)
        assert preview is not None

    def test_delete_sprite(self, extractor, sample_sprite_sheet_path):
        """Test manual sprite deletion"""
        extractor.load_image(sample_sprite_sheet_path)
        extractor.detect_sprites()
        initial_len = len(extractor.sprites)
        
        # Delete first sprite
        res = extractor.delete_sprite(0)
        assert res is True
        assert len(extractor.sprites) == initial_len - 1
        # Check reindexing
        for i, s in enumerate(extractor.sprites):
            assert s.index == i
            
    def test_merge_sprites(self, extractor, sample_sprite_sheet_path):
        """Test manual sprite merging"""
        extractor.load_image(sample_sprite_sheet_path)
        extractor.detect_sprites()
        initial_len = len(extractor.sprites)
        
        if initial_len >= 2:
            res = extractor.merge_sprites([0, 1])
            assert res is True
            assert len(extractor.sprites) == initial_len - 1 # Merged 2 into 1
            # Check reindexing
            for i, s in enumerate(extractor.sprites):
                assert s.index == i

class TestSpriteDataclass:
    """Tests for Sprite dataclass"""
    
    def test_sprite_default_values(self, extractor, sample_sprite_sheet_path):
        """Test that sprites have correct default values"""
        extractor.load_image(sample_sprite_sheet_path)
        sprites = extractor.detect_sprites()
        
        for sprite in sprites:
            assert sprite.rotation == 0
            assert hasattr(sprite, 'view_type')
            assert hasattr(sprite, 'bbox')
            assert hasattr(sprite, 'image')
