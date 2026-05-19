"""
Sprite Extractor - Core processing module
Detecta e extrai sprites individuais de uma sprite sheet.

Este modulo e o coracao do Blueprint Maker. Ele e agnostico de UI
e pode ser usado tanto pelo standalone Qt quanto pelo plugin GIMP.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import urllib.request
from urllib.error import HTTPError, URLError

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class DNNUpscaler:
    def __init__(self):
        self.models_dir = Path.home() / ".blueprint-maker" / "models"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.models = {
            "fsrcnn": {
                "url": (
                    "https://github.com/Saafke/FSRCNN_Tensorflow/raw/"
                    "master/models/FSRCNN_x2.pb"
                ),
                "filename": "FSRCNN_x2.pb",
                "scale": 2,
            },
            "edsr": {
                "url": (
                    "https://github.com/Saafke/EDSR_Tensorflow/raw/"
                    "master/models/EDSR_x2.pb"
                ),
                "filename": "EDSR_x2.pb",
                "scale": 2,
            },
        }
        self.sr_instances = {}

    def get_model(self, model_type: str, progress_callback=None):
        if model_type not in self.models:
            return None

        if model_type in self.sr_instances:
            return self.sr_instances[model_type]

        model_info = self.models[model_type]
        model_path = self.models_dir / model_info["filename"]

        if not model_path.exists():
            msg = f"Baixando modelo {model_type.upper()}..."
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)
            try:
                urllib.request.urlretrieve(model_info["url"], str(model_path))
            except (urllib.error.URLError, OSError) as e:
                logger.error(
                    "Falha ao baixar modelo %s: %s",
                    model_type,
                    e,
                    exc_info=True,
                )
                return None

        try:
            if progress_callback:
                progress_callback(
                    f"Carregando modelo {model_type.upper()}..."
                )
            sr = cv2.dnn_superres.DnnSuperResImpl_create()
            sr.readModel(str(model_path))
            sr.setModel(model_type, model_info["scale"])
            self.sr_instances[model_type] = sr
            return sr
        except (cv2.error, OSError) as e:
            logger.error(
                "Falha ao carregar modelo %s: %s",
                model_type,
                e,
                exc_info=True,
            )
            return None

    def upscale(
        self,
        image: np.ndarray,
        model_type: str,
        progress_callback=None,
    ) -> np.ndarray:
        """Aplica upscale DNN na imagem, com fallback para Lanczos4.

        Args:
            image: Imagem BGR ou BGRA.
            model_type: Tipo do modelo ("none", "fsrcnn", "edsr").
            progress_callback: Callable para reportar progresso.

        Returns:
            Imagem com resolução aumentada (2x).
        """
        if model_type == "none":
            return image

        sr = self.get_model(model_type, progress_callback)
        if sr is None:
            logger.warning(
                "Fallback para Lanczos4 (modelo %s indisponivel)",
                model_type,
            )
            h, w = image.shape[:2]
            return cv2.resize(
                image,
                (w * 2, h * 2),
                interpolation=cv2.INTER_LANCZOS4,
            )

        has_alpha = image.shape[2] == 4 if len(image.shape) == 3 else False

        if has_alpha:
            bgr = image[:, :, :3]
            alpha = image[:, :, 3]
            res_bgr = sr.upsample(bgr)
            h, w = res_bgr.shape[:2]
            res_alpha = cv2.resize(
                alpha,
                (w, h),
                interpolation=cv2.INTER_LANCZOS4,
            )
            return cv2.merge(
                (
                    res_bgr[:, :, 0],
                    res_bgr[:, :, 1],
                    res_bgr[:, :, 2],
                    res_alpha,
                )
            )
        elif len(image.shape) == 2:
            img_bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            res_bgr = sr.upsample(img_bgr)
            return cv2.cvtColor(res_bgr, cv2.COLOR_BGR2GRAY)
        else:
            return sr.upsample(image)


# --- Constantes de Detecção ---
# Margem em pixels para limpar bordas da máscara binária.
# Valor alto (20px) para ignorar molduras/sombras comuns em sprite sheets JPEG.
BORDER_CLEANUP_MARGIN_PX = 20

# Tolerância em pixels para agrupar posições de sprites em linhas/colunas.
# Sprites com centros a menos de GRID_CLUSTER_TOLERANCE px são considerados
# na mesma linha/coluna durante a detecção de grid.
GRID_CLUSTER_TOLERANCE_PX = 100

# Quantização de Y para ordenação de sprites por linha.
# Sprites são agrupados em "linhas" de SORT_ROW_QUANTIZE_PX pixels.
SORT_ROW_QUANTIZE_PX = 50

# Tamanho da amostra nos cantos para detectar se o fundo é claro ou escuro.
CORNER_SAMPLE_SIZE = 10


class ImageLoadError(Exception):
    """Excecao levantada quando ha falha no carregamento de imagem."""

    pass


@dataclass
class Sprite:
    """Representa um sprite detectado na imagem.

    Attributes:
        bbox: Bounding box (x, y, largura, altura) em pixels.
        image: Array numpy com os pixels do sprite (BGR ou BGRA).
        index: Índice sequencial após ordenação por posição.
        view_type: Classificacao da vista (front, back, left, right,
            top, bottom)
            ou "unknown" se não classificada.
        rotation: Rotação aplicada ao sprite em graus (0, 90, 180, 270),
            sentido horário.
    """
    bbox: Tuple[int, int, int, int]
    image: np.ndarray
    index: int
    view_type: str = "unknown"
    rotation: int = 0


class SpriteExtractor:
    """Motor de detecção e extração de sprites de sprite sheets.

    Fluxo principal:
        1. load_image() → carrega a imagem fonte
        2. detect_sprites() → detecta e classifica sprites
        3. export_sprites() → exporta sprites individuais

    Thread Safety:
        Esta classe NÃO é thread-safe. Se usada em threads paralelas,
        o chamador deve garantir que não há acesso concorrente ao estado
        (original_image, processed_image, sprites).
    """

    def __init__(self):
        self.original_image: Optional[np.ndarray] = None
        self.sprites: List[Sprite] = []
        self.image_path: Optional[Path] = None
        self._last_binary_mask: Optional[np.ndarray] = None
        self.upscaler = DNNUpscaler()

    def load_image(self, path: str) -> None:
        """Carrega uma imagem e limpa estados anteriores.

        Args:
            path: Caminho absoluto ou relativo para o arquivo de imagem.

        Raises:
            ImageLoadError: Se o arquivo nao existir ou nao puder ser
                decodificado,
                ou ocorrer um erro de IO/OpenCV durante o carregamento.
        """
        try:
            self.image_path = Path(path)
            if not self.image_path.exists():
                logger.warning("Arquivo não encontrado: %s", path)
                raise ImageLoadError(f"Arquivo não encontrado: {path}")

            self.original_image = cv2.imread(
                str(self.image_path),
                cv2.IMREAD_UNCHANGED,
            )
            if self.original_image is None:
                logger.warning("OpenCV não conseguiu decodificar: %s", path)
                raise ImageLoadError(
                    "Formato de imagem nao suportado ou arquivo corrompido: "
                    f"{path}"
                )

            # Garantir 4 canais (BGRA) para consistência interna
            if len(self.original_image.shape) == 2:
                # Grayscale → BGRA
                self.original_image = cv2.cvtColor(
                    self.original_image,
                    cv2.COLOR_GRAY2BGRA,
                )
            elif self.original_image.shape[2] == 3:
                self.original_image = cv2.cvtColor(
                    self.original_image,
                    cv2.COLOR_BGR2BGRA,
                )

            self.processed_image = self.original_image.copy()
            self.sprites = []
            logger.info(
                "Imagem carregada: %s (%dx%d)",
                path,
                self.original_image.shape[1],
                self.original_image.shape[0],
            )
        except (cv2.error, OSError) as e:
            logger.error(
                "Falha ao carregar imagem %s: %s",
                path,
                e,
                exc_info=True,
            )
            raise ImageLoadError(
                f"Falha de sistema ao carregar imagem: {e}"
            ) from e

    def apply_ai_features(
        self,
        remove_bg=False,
        upscale="none",
        progress_callback=None,
    ):
        """Aplica processamento de IA (rembg e/ou upscale).

        Sempre reseta para a imagem original antes de aplicar,
        garantindo idempotência em chamadas repetidas.

        Args:
            remove_bg: Se True, usa rembg para remover o fundo.
            upscale: Modelo de upscale ("none", "fsrcnn", "edsr").
            progress_callback: Callable(str) para reportar progresso.
        """
        self.processed_image = self.original_image.copy()

        if remove_bg:
            if progress_callback:
                progress_callback(
                    "Removendo fundo (pode baixar modelo U2NET na 1a vez)..."
                )
            try:
                from rembg import remove

                self.processed_image = remove(self.processed_image)
            except ImportError:
                logger.warning(
                    "rembg nao instalado - remocao de fundo ignorada"
                )
            except (
                ConnectionError,
                TimeoutError,
                HTTPError,
                URLError,
                OSError,
            ) as e:
                logger.warning(
                    "Remocao de fundo indisponivel por falha de rede/IO: %s",
                    e,
                    exc_info=True,
                )
            except (RuntimeError, ValueError) as e:
                logger.error("Falha ao remover fundo: %s", e, exc_info=True)

        # Suporte a legado (se upscale vir como bool de versões anteriores)
        if upscale is True:
            upscale = "fsrcnn"
        if upscale is False:
            upscale = "none"

        if upscale != "none":
            if progress_callback:
                progress_callback(
                    f"Aplicando Upscale {upscale.upper()}..."
                )
            try:
                self.processed_image = self.upscaler.upscale(
                    self.processed_image,
                    upscale,
                    progress_callback,
                )
            except (cv2.error, RuntimeError) as e:
                logger.error(
                    "Falha no upscale %s: %s",
                    upscale,
                    e,
                    exc_info=True,
                )

    def detect_sprites(
        self,
        threshold: int = 10,
        min_area: int = 100,
        layout_hint: str = None,
        remove_bg: bool = False,
        upscale: str = "none",
        progress_callback=None,
    ) -> List[Sprite]:
        """
        Detecta sprites individuais na imagem
        """
        if self.original_image is None:
            return []

        # Aplicar IA se solicitado
        self.apply_ai_features(
            remove_bg=remove_bg,
            upscale=upscale,
            progress_callback=progress_callback,
        )

        # Usar a imagem processada (IA) para detecção
        image = self.processed_image

        self.sprites = []

        # Converter para tons de cinza para detecção
        if image.shape[2] == 4:
            # Usar o canal alpha como base para a mascara se houver
            # transparencia.
            # Caso contrário, converter RGB para Gray
            alpha = image[:, :, 3]
            if cv2.countNonZero(alpha) < (alpha.shape[0] * alpha.shape[1]):
                # Tem transparencia real.
                gray = 255 - alpha
            else:
                gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
        else:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)

        # Se a imagem tiver canal alpha, verificar se e util
        # (nao totalmente solido).
        has_useful_alpha = False
        if self.original_image.shape[2] == 4:  # BGRA
            alpha_channel = self.original_image[:, :, 3]
            # Se houver qualquer pixel transparente (alpha < 255),
            # consideramos o alpha util.
            if not np.all(alpha_channel == 255):
                has_useful_alpha = True
                # Pixels com alguma opacidade sao parte do sprite.
                _, binary = cv2.threshold(
                    alpha_channel,
                    0,
                    255,
                    cv2.THRESH_BINARY,
                )

        if not has_useful_alpha:
            # Caso contrário, usar thresholding na imagem em escala de cinza
            # Detectar se o fundo é claro ou escuro baseando-se nos cantos
            # Amostrar pequenas areas nos cantos, com uma margem para
            # ignorar molduras.
            h, w = gray.shape
            margin_h = min(BORDER_CLEANUP_MARGIN_PX, h // 50)
            margin_w = min(BORDER_CLEANUP_MARGIN_PX, w // 50)
            corner_size = CORNER_SAMPLE_SIZE

            # Amostras nos 4 cantos, levemente para dentro
            samples = [
                gray[
                    margin_h:margin_h + corner_size,
                    margin_w:margin_w + corner_size,
                ],
                gray[
                    margin_h:margin_h + corner_size,
                    -margin_w - corner_size:-margin_w,
                ],
                gray[
                    -margin_h - corner_size:-margin_h,
                    margin_w:margin_w + corner_size,
                ],
                gray[
                    -margin_h - corner_size:-margin_h,
                    -margin_w - corner_size:-margin_w,
                ],
            ]
            avg_corner_val = np.mean([np.mean(s) for s in samples])
            is_light_bg = avg_corner_val > 127

            if is_light_bg:
                # Fundo claro: inverter threshold para que sprites fiquem
                # brancos.
                # O threshold atua como margem de diferenca para o fundo.
                # Se o fundo é 255 e threshold é 10, pegamos tudo < 245
                _, binary = cv2.threshold(
                    gray,
                    255 - threshold,
                    255,
                    cv2.THRESH_BINARY_INV,
                )
            else:
                # Fundo escuro: threshold normal
                _, binary = cv2.threshold(
                    gray,
                    threshold,
                    255,
                    cv2.THRESH_BINARY,
                )

        self._last_binary_mask = binary.copy()

        # Limpar ruído e separar sprites próximos
        # 1. Opening para remover ruído pequeno
        kernel_small = np.ones((3, 3), np.uint8)
        binary = cv2.morphologyEx(
            binary,
            cv2.MORPH_OPEN,
            kernel_small,
            iterations=1,
        )

        # 2. Erode para quebrar pontes finas entre sprites
        binary = cv2.erode(binary, kernel_small, iterations=2)

        # 3. Dilate para restaurar o corpo do sprite sem perder a separacao.
        binary = cv2.dilate(binary, kernel_small, iterations=1)

        # Limpar bordas para ignorar molduras/sombras de borda comuns em JPEGs
        binary[0:BORDER_CLEANUP_MARGIN_PX, :] = 0
        binary[-BORDER_CLEANUP_MARGIN_PX:, :] = 0
        binary[:, 0:BORDER_CLEANUP_MARGIN_PX] = 0
        binary[:, -BORDER_CLEANUP_MARGIN_PX:] = 0

        # Encontrar contornos
        contours, _ = cv2.findContours(
            binary,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        # Pré-processar contornos para criar filtro adaptativo
        valid_contours = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area >= min_area:
                valid_contours.append((contour, area))

        bboxes = []
        if valid_contours:
            # Heuristica: encontrar o maior objeto para detectar ruido.
            max_area = max(area for _, area in valid_contours)

            # Objetos de blueprint tendem a ser muito maiores que textos.
            # O threshold dinamico evita exigir ajuste manual para esse caso.
            adaptive_min_area = max(min_area, max_area * 0.02)

            for contour, area in valid_contours:
                if area >= adaptive_min_area:
                    x, y, w, h = cv2.boundingRect(contour)
                    bboxes.append((x, y, w, h))

        # Ordenar por linha quantizada e depois por coluna.
        bboxes.sort(
            key=lambda bbox: (
                round(bbox[1] / SORT_ROW_QUANTIZE_PX)
                * SORT_ROW_QUANTIZE_PX,
                bbox[0],
            )
        )

        # Criar objetos Sprite
        for idx, (x, y, w, h) in enumerate(bboxes):
            # Extrair o sprite
            sprite_img = self.processed_image[y:y+h, x:x+w].copy()
            sprite = Sprite(bbox=(x, y, w, h), image=sprite_img, index=idx)
            self.sprites.append(sprite)

        # Classificar vistas
        if len(self.sprites) > 0:
            self._classify_views(layout_hint)

        return self.sprites

    def _classify_views(self, layout_hint: str = None):
        """
        Classifica o tipo de vista pela posicao no grid ou hint de layout.
        """
        num_sprites = len(self.sprites)
        if num_sprites == 0:
            return

        # Usar hint se fornecido
        if layout_hint == "3x2" and num_sprites >= 6:
            views = ["front", "top", "left", "bottom", "right", "back"]
            for i, sprite in enumerate(self.sprites[:6]):
                sprite.view_type = views[i]
            return
        elif layout_hint == "2x3" and num_sprites >= 6:
            views = ["front", "top", "back", "left", "right", "bottom"]
            for i, sprite in enumerate(self.sprites[:6]):
                sprite.view_type = views[i]
            return
        elif layout_hint == "2x2" and num_sprites >= 4:
            views = ["front", "back", "left", "right"]
            for i, sprite in enumerate(self.sprites[:4]):
                sprite.view_type = views[i]
            return

        # Fallback para detecção automática
        rows, cols = self._detect_grid_structure()

        # Padrões de nomenclatura baseados no número total de sprites e grid
        if num_sprites == 1:
            self.sprites[0].view_type = "front"

        elif num_sprites == 2:
            if rows == 1:
                self.sprites[0].view_type = "left"
                self.sprites[1].view_type = "right"
            else:
                self.sprites[0].view_type = "front"
                self.sprites[1].view_type = "back"

        elif num_sprites == 4:
            if rows == 2 and cols == 2:
                # Comum em 2x2
                self.sprites[0].view_type = "front"
                self.sprites[1].view_type = "back"
                self.sprites[2].view_type = "left"
                self.sprites[3].view_type = "right"
            else:
                views = ["front", "back", "left", "right"]
                for i, sprite in enumerate(self.sprites):
                    if i < 4:
                        sprite.view_type = views[i]

        elif num_sprites == 6:
            # Layout 3x2 comum para 6 vistas.
            if rows == 3 and cols == 2:
                views = ["front", "top", "left", "bottom", "right", "back"]
            # Layout 2x3
            elif rows == 2 and cols == 3:
                views = ["front", "top", "back", "left", "right", "bottom"]
            else:
                views = ["front", "back", "left", "right", "top", "bottom"]

            for i, sprite in enumerate(self.sprites):
                if i < len(views):
                    sprite.view_type = views[i]

        else:
            # Para outros casos, usar row/col
            for sprite in self.sprites:
                r, c = self._get_sprite_grid_position(sprite, rows, cols)
                sprite.view_type = f"row{r+1}_col{c+1}"

    def _detect_grid_structure(self) -> Tuple[int, int]:
        """
        Detecta a estrutura do grid baseado nas posições centrais dos sprites
        """
        if not self.sprites:
            return (0, 0)

        # Usar o centro do sprite para agrupar, pois as alturas variam.
        y_centers = sorted([s.bbox[1] + s.bbox[3] // 2 for s in self.sprites])
        x_centers = sorted([s.bbox[0] + s.bbox[2] // 2 for s in self.sprites])

        # Agrupar posições por proximidade
        def count_clusters(positions, tolerance=GRID_CLUSTER_TOLERANCE_PX):
            if not positions:
                return 0
            clusters = 1
            for i in range(1, len(positions)):
                if positions[i] - positions[i - 1] > tolerance:
                    clusters += 1
            return clusters

        num_rows = count_clusters(y_centers)
        num_cols = count_clusters(x_centers)

        return (num_rows, num_cols)

    def _get_sprite_grid_position(
        self,
        sprite: Sprite,
        rows: int,
        cols: int,
    ) -> Tuple[int, int]:
        """
        Retorna a posicao no grid usando o centro do sprite.
        """
        y_centers = sorted([s.bbox[1] + s.bbox[3] // 2 for s in self.sprites])
        x_centers = sorted([s.bbox[0] + s.bbox[2] // 2 for s in self.sprites])

        def get_cluster_index(
            val,
            positions,
            tolerance=GRID_CLUSTER_TOLERANCE_PX,
        ):
            unique_clusters = []
            for p in positions:
                if not any(abs(p - c) < tolerance for c in unique_clusters):
                    unique_clusters.append(p)
            unique_clusters.sort()
            center = val
            for i, c in enumerate(unique_clusters):
                if abs(center - c) < tolerance:
                    return i
            return 0

        sprite_y_center = sprite.bbox[1] + sprite.bbox[3] // 2
        sprite_x_center = sprite.bbox[0] + sprite.bbox[2] // 2

        r = get_cluster_index(sprite_y_center, y_centers)
        c = get_cluster_index(sprite_x_center, x_centers)
        return (r, c)

    def get_sprite(self, index: int) -> Optional[Sprite]:
        """
        Retorna um sprite específico pelo índice

        Args:
            index: Índice do sprite

        Returns:
            Sprite ou None se índice inválido
        """
        if 0 <= index < len(self.sprites):
            return self.sprites[index]
        return None

    def export_sprites(
        self,
        output_dir: str,
        prefix: str = "sprite",
        format: str = "png",
        use_view_names: bool = True,
        padding: int = 0,
        uniform_size: bool = False,
    ) -> List[Path]:
        """
        Exporta todos os sprites detectados

        Args:
            output_dir: Diretório de saída
            prefix: Prefixo para nomes dos arquivos
            format: Formato da imagem (png, jpg, etc)
            use_view_names: Se True, usa o tipo de vista no nome do arquivo
            padding: Margem extra em pixels ao redor do sprite
            uniform_size: Se True, todas as imagens terao o mesmo tamanho.

        Returns:
            Lista de caminhos dos arquivos exportados
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        exported_files = []

        # Calcular tamanho uniforme se necessário
        target_w, target_h = 0, 0
        if uniform_size and self.sprites:
            max_w = max(s.bbox[2] for s in self.sprites)
            max_h = max(s.bbox[3] for s in self.sprites)
            target_w = max_w + (2 * padding)
            target_h = max_h + (2 * padding)

        for sprite in self.sprites:
            # Gerar nome do arquivo
            if use_view_names and sprite.view_type != "unknown":
                filename = f"{prefix}_{sprite.view_type}.{format}"
            else:
                filename = f"{prefix}_{sprite.index + 1:02d}.{format}"

            filepath = output_path / filename

            # Processar imagem do sprite com rotacao, padding e tamanho final.
            sprite_img = sprite.image.copy()

            # Aplicar rotação se houver
            if sprite.rotation != 0:
                if sprite.rotation == 90:
                    sprite_img = cv2.rotate(
                        sprite_img,
                        cv2.ROTATE_90_CLOCKWISE,
                    )
                elif sprite.rotation == 180:
                    sprite_img = cv2.rotate(sprite_img, cv2.ROTATE_180)
                elif sprite.rotation == 270:
                    sprite_img = cv2.rotate(
                        sprite_img,
                        cv2.ROTATE_90_COUNTERCLOCKWISE,
                    )

            if padding > 0 or uniform_size:
                h, w = sprite_img.shape[:2]

                # Se não for uniforme, o tamanho é apenas o sprite + padding
                if not uniform_size:
                    curr_target_w = w + (2 * padding)
                    curr_target_h = h + (2 * padding)
                else:
                    curr_target_w = target_w
                    curr_target_h = target_h

                # Determinar cor de preenchimento baseada nas bordas do sprite
                # Amostrar as bordas para pegar a cor predominante
                top_edge = sprite_img[0, :]
                bottom_edge = sprite_img[-1, :]
                left_edge = sprite_img[:, 0]
                right_edge = sprite_img[:, -1]
                all_edges = np.concatenate(
                    [top_edge, bottom_edge, left_edge, right_edge]
                )

                # Usar mediana para ser robusto a ruídos na borda
                fill_color = np.median(all_edges, axis=0).astype(np.uint8)

                # Criar novo canvas preenchido com a cor detectada
                if sprite_img.shape[2] == 4:
                    new_img = np.full(
                        (curr_target_h, curr_target_w, 4),
                        fill_color,
                        dtype=np.uint8,
                    )
                else:
                    new_img = np.full(
                        (curr_target_h, curr_target_w, 3),
                        fill_color,
                        dtype=np.uint8,
                    )

                # Calcular posição central
                x_offset = (curr_target_w - w) // 2
                y_offset = (curr_target_h - h) // 2

                # Colar sprite no centro
                new_img[
                    y_offset:y_offset + h,
                    x_offset:x_offset + w,
                ] = sprite_img
                sprite_img = new_img

            # Salvar imagem
            cv2.imwrite(str(filepath), sprite_img)
            exported_files.append(filepath)

        return exported_files

    def delete_sprite(self, index: int) -> bool:
        """Remove a sprite manually by its index."""
        target_sprite = next(
            (sprite for sprite in self.sprites if sprite.index == index),
            None,
        )
        if target_sprite:
            self.sprites.remove(target_sprite)
            # Reindex
            for i, s in enumerate(self.sprites):
                s.index = i
            return True
        return False

    def merge_sprites(self, indices: List[int]) -> bool:
        """Merges multiple sprites into a single bounding box."""
        if len(indices) < 2:
            return False

        sprites_to_merge = [s for s in self.sprites if s.index in indices]
        if len(sprites_to_merge) != len(indices):
            return False

        # Find the bounding box that encompasses all
        min_x = min(s.bbox[0] for s in sprites_to_merge)
        min_y = min(s.bbox[1] for s in sprites_to_merge)
        max_x = max(s.bbox[0] + s.bbox[2] for s in sprites_to_merge)
        max_y = max(s.bbox[1] + s.bbox[3] for s in sprites_to_merge)

        new_w = max_x - min_x
        new_h = max_y - min_y

        new_bbox = (min_x, min_y, new_w, new_h)
        new_img = self.processed_image[
            min_y:min_y + new_h,
            min_x:min_x + new_w,
        ].copy()

        # Remove old sprites
        for s in sprites_to_merge:
            self.sprites.remove(s)

        # Add new merged sprite
        new_sprite = Sprite(bbox=new_bbox, image=new_img, index=0)
        self.sprites.append(new_sprite)

        # Sort and reindex all sprites based on position (Y quantized, then X)
        self.sprites.sort(
            key=lambda sprite: (
                round(sprite.bbox[1] / SORT_ROW_QUANTIZE_PX)
                * SORT_ROW_QUANTIZE_PX,
                sprite.bbox[0],
            )
        )
        for i, s in enumerate(self.sprites):
            s.index = i

        return True

    def get_preview_image(
        self,
        draw_boxes: bool = True,
        selected_index: int = -1,
        multi_selected: List[int] = None,
    ) -> Optional[np.ndarray]:
        """Retorna uma imagem para exibição com os boxes desenhados"""
        if self.processed_image is None:
            return None

        preview = self.processed_image.copy()
        if preview.shape[2] == 4:
            preview = cv2.cvtColor(preview, cv2.COLOR_BGRA2BGR)

        if draw_boxes:
            for sprite in self.sprites:
                x, y, w, h = sprite.bbox
                # Cor padrão verde
                color = (0, 255, 0)
                thickness = 2

                # Destacar se selecionado ou multi-selecionado
                if sprite.index == selected_index or (
                    multi_selected and sprite.index in multi_selected
                ):
                    color = (0, 0, 255)
                    thickness = 4

                # Desenhar retângulo
                cv2.rectangle(
                    preview,
                    (x, y),
                    (x + w, y + h),
                    color,
                    thickness,
                )
                # Desenhar número do sprite
                cv2.putText(
                    preview,
                    str(sprite.index + 1),
                    (x, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    2,
                )

        return preview

    def get_binary_mask_preview(self) -> Optional[np.ndarray]:
        """Retorna a última máscara binária gerada"""
        return self._last_binary_mask
