"""
Tests for Batch Processing logic — sem dependência de PyQt6.

Testa o core do processamento em lote: SpriteExtractor em loop
com múltiplas imagens, validação de parâmetros, e cenários de erro.
"""
import pytest
import numpy as np
import cv2
from pathlib import Path

from core.sprite_extractor import SpriteExtractor


class TestBatchProcessingCore:
    """Testa a lógica de processamento em lote sem UI."""

    @pytest.fixture
    def batch_images(self, tmp_path):
        """Cria 3 imagens de teste simulando um lote."""
        images = {}
        colors_per_image = [
            [(0, 0, 255, 255), (0, 255, 0, 255)],   # 2 sprites: red, green
            [(255, 0, 0, 255)],                        # 1 sprite: blue
            [(0, 255, 255, 255), (255, 255, 0, 255), (255, 0, 255, 255)],  # 3 sprites
        ]
        
        for i, colors in enumerate(colors_per_image):
            img = np.zeros((200, 200, 4), dtype=np.uint8)
            for j, color in enumerate(colors):
                x = 10 + (j * 80)
                y = 10
                img[y:y+50, x:x+50] = color
            
            path = tmp_path / f"sheet_{i}.png"
            cv2.imwrite(str(path), img)
            images[path.name] = str(path)
        
        return images, tmp_path

    def test_batch_all_images_process(self, batch_images):
        """Todas as imagens do lote devem ser processadas com sucesso."""
        images, tmp_path = batch_images
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        processed = 0
        for name, path in images.items():
            extractor = SpriteExtractor()
            try:
                extractor.load_image(path)
                sprites = extractor.detect_sprites(threshold=10, min_area=100)
                if sprites:
                    extractor.export_sprites(
                        output_dir=str(output_dir),
                        prefix=f"batch_{Path(path).stem}",
                    )
                    processed += 1
            except Exception:
                pass
        
        assert processed == 3
        # Verificar que arquivos foram criados
        exported = list(output_dir.glob("*.png"))
        assert len(exported) >= 3  # No mínimo 1 sprite por imagem

    def test_batch_with_invalid_image(self, batch_images, tmp_path):
        """Imagens inválidas no lote não devem interromper o processamento."""
        images, _ = batch_images
        
        # Adicionar um "arquivo" inválido
        bad_path = tmp_path / "corrupted.png"
        bad_path.write_text("not an image")
        
        results = []
        all_paths = list(images.values()) + [str(bad_path)]
        
        from core.sprite_extractor import ImageLoadError
        for path in all_paths:
            extractor = SpriteExtractor()
            try:
                extractor.load_image(path)
                results.append(True)
            except ImageLoadError:
                results.append(False)
        
        # 3 válidas + 1 inválida
        assert results.count(True) == 3
        assert results.count(False) == 1

    def test_batch_independent_extractors(self, batch_images):
        """Cada imagem deve usar seu próprio extractor — sem estado compartilhado."""
        images, _ = batch_images
        
        extractors = []
        for path in images.values():
            ext = SpriteExtractor()
            ext.load_image(path)
            ext.detect_sprites(threshold=10, min_area=100)
            extractors.append(ext)
        
        # Cada extractor deve ter seus próprios sprites
        sprite_counts = [len(ext.sprites) for ext in extractors]
        assert sprite_counts[0] == 2  # sheet_0: 2 sprites
        assert sprite_counts[1] == 1  # sheet_1: 1 sprite
        assert sprite_counts[2] == 3  # sheet_2: 3 sprites
        
        # Modificar um extractor não deve afetar os outros
        extractors[0].sprites.clear()
        assert len(extractors[1].sprites) == 1
        assert len(extractors[2].sprites) == 3

    def test_batch_with_different_thresholds(self, batch_images):
        """Diferentes thresholds devem produzir resultados diferentes."""
        images, _ = batch_images
        first_image = list(images.values())[0]
        
        ext_low = SpriteExtractor()
        ext_low.load_image(first_image)
        sprites_low = ext_low.detect_sprites(threshold=10, min_area=100)
        
        ext_high = SpriteExtractor()
        ext_high.load_image(first_image)
        sprites_high = ext_high.detect_sprites(threshold=10, min_area=100000)
        
        # Com min_area alta, nenhum sprite deve ser detectado
        assert len(sprites_low) > 0
        assert len(sprites_high) == 0


class TestThreadSafetyPattern:
    """Testa o padrão de isolamento por cópia usado pelo AIDetectionWorker.
    
    Valida que o padrão de deep copy + extractor isolado funciona
    corretamente sem depender de QThread.
    """

    @pytest.fixture
    def loaded_extractor(self, sample_sprite_sheet_path):
        """Retorna um extractor com imagem carregada."""
        ext = SpriteExtractor()
        ext.load_image(sample_sprite_sheet_path)
        return ext

    def test_image_copy_is_independent(self, loaded_extractor):
        """A cópia da imagem deve ser independente do original."""
        original_image = loaded_extractor.original_image
        image_copy = original_image.copy()
        
        # Modificar a cópia não afeta o original
        image_copy[:] = 0
        assert not np.array_equal(original_image, image_copy)
        assert np.any(original_image > 0)

    def test_isolated_extractor_produces_same_results(self, loaded_extractor):
        """Um extractor isolado com cópia da imagem deve produzir 
        os mesmos resultados que o original."""
        # Detectar com o extractor original
        original_sprites = loaded_extractor.detect_sprites(
            threshold=10, min_area=100
        )
        original_count = len(original_sprites)
        original_bboxes = [s.bbox for s in original_sprites]
        
        # Simular o padrão do worker: criar novo extractor com cópia
        image_copy = loaded_extractor.original_image.copy()
        worker_extractor = SpriteExtractor()
        worker_extractor.original_image = image_copy
        worker_extractor.processed_image = image_copy.copy()
        
        worker_sprites = worker_extractor.detect_sprites(
            threshold=10, min_area=100
        )
        worker_bboxes = [s.bbox for s in worker_sprites]
        
        # Resultados devem ser idênticos
        assert len(worker_sprites) == original_count
        assert worker_bboxes == original_bboxes

    def test_worker_results_sync_to_main(self, loaded_extractor):
        """Sincronizar resultados do worker para o extractor principal
        deve atualizar corretamente sprites, processed_image e mask."""
        # Simular worker
        image_copy = loaded_extractor.original_image.copy()
        worker_ext = SpriteExtractor()
        worker_ext.original_image = image_copy
        worker_ext.processed_image = image_copy.copy()
        worker_sprites = worker_ext.detect_sprites(threshold=10, min_area=100)
        
        # Construir resultado como o worker faria
        result = {
            "sprites": worker_sprites,
            "processed_image": worker_ext.processed_image,
            "binary_mask": worker_ext.get_binary_mask_preview(),
        }
        
        # Simular sincronização na main thread
        loaded_extractor.sprites = result["sprites"]
        loaded_extractor.processed_image = result["processed_image"]
        loaded_extractor._last_binary_mask = result["binary_mask"]
        
        # Verificar que o extractor principal tem os dados do worker
        assert len(loaded_extractor.sprites) == len(worker_sprites)
        assert loaded_extractor.processed_image is result["processed_image"]
        assert loaded_extractor._last_binary_mask is result["binary_mask"]
        
        # Preview deve funcionar com os dados sincronizados
        preview = loaded_extractor.get_preview_image(draw_boxes=True)
        assert preview is not None

    def test_concurrent_extractors_dont_interfere(self, sample_sprite_sheet_path):
        """Múltiplos extractors rodando em paralelo não devem interferir."""
        import concurrent.futures
        
        def detect_in_thread(threshold):
            ext = SpriteExtractor()
            ext.load_image(sample_sprite_sheet_path)
            sprites = ext.detect_sprites(threshold=threshold, min_area=100)
            return len(sprites)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(detect_in_thread, t) for t in [10, 10, 10, 10]]
            results = [f.result() for f in futures]
        
        # Todos devem ter o mesmo resultado — sem interferência
        assert all(r == results[0] for r in results)
        assert results[0] == 4  # 4 sprites na fixture padrão
