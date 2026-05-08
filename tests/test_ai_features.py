import pytest
import numpy as np
from core.sprite_extractor import SpriteExtractor, DNNUpscaler

class TestAIFeatures:
    def test_dnn_upscaler_init(self):
        upscaler = DNNUpscaler()
        assert upscaler.models_dir.exists()
        assert "fsrcnn" in upscaler.models
        assert "edsr" in upscaler.models

    def test_dnn_upscaler_none(self):
        upscaler = DNNUpscaler()
        dummy_img = np.zeros((10, 10, 3), dtype=np.uint8)
        res = upscaler.upscale(dummy_img, "none")
        assert res.shape == (10, 10, 3)

    def test_apply_ai_features_no_action(self, mocker):
        extractor = SpriteExtractor()
        extractor.original_image = np.zeros((20, 20, 3), dtype=np.uint8)
        
        mock_upscale = mocker.patch.object(extractor.upscaler, 'upscale')
        extractor.apply_ai_features(remove_bg=False, upscale="none")
        
        mock_upscale.assert_not_called()
        assert extractor.processed_image.shape == (20, 20, 3)

    def test_apply_ai_features_upscale_called(self, mocker):
        extractor = SpriteExtractor()
        extractor.original_image = np.zeros((20, 20, 3), dtype=np.uint8)
        
        mock_upscale = mocker.patch.object(extractor.upscaler, 'upscale', return_value=np.zeros((40, 40, 3), dtype=np.uint8))
        extractor.apply_ai_features(remove_bg=False, upscale="fsrcnn")
        
        mock_upscale.assert_called_once()
        assert extractor.processed_image.shape == (40, 40, 3)

    def test_apply_ai_features_remove_bg_called(self, mocker):
        extractor = SpriteExtractor()
        extractor.original_image = np.zeros((20, 20, 3), dtype=np.uint8)
        
        # Mock rembg
        mock_remove = mocker.patch('rembg.remove', return_value=np.zeros((20, 20, 4), dtype=np.uint8))
        
        extractor.apply_ai_features(remove_bg=True, upscale="none")
        
        mock_remove.assert_called_once()
        assert extractor.processed_image.shape == (20, 20, 4)
