from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QRubberBand, QMenu
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QRectF, QPointF
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QAction
import cv2

class ClickableGraphicsView(QGraphicsView):
    """QGraphicsView customizado que detecta cliques na imagem"""
    clicked = pyqtSignal(int, int) # Sinal que emite x, y

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Obter coordenadas na cena
            scene_pos = self.mapToScene(event.pos())
            self.clicked.emit(int(scene_pos.x()), int(scene_pos.y()))
        super().mousePressEvent(event)

class ImageViewer(QGraphicsView):
    """Componente para visualização e interação com o sprite sheet"""
    sprite_clicked = pyqtSignal(int, bool) # Índice, is_multi_select
    delete_requested = pyqtSignal(int)
    merge_requested = pyqtSignal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setMinimumSize(600, 500)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QColor("#181825"))
        
        self.pixmap_item = None
        self.zoom_factor = 1.15
        self.current_zoom = 1.0
        self.is_panning = False
        self.last_mouse_pos = QPoint()
        
        self.sprites = []
        self.selected_index = -1
        self.multi_selected_indices = []
        
        # Context Menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    file_dropped = pyqtSignal(str)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path:
                    self.file_dropped.emit(file_path)
                    event.accept()
                    return
        super().dropEvent(event)
    
    def display_image(self, image, sprites=None, selected_index=-1):
        """Exibe imagem numpy e bounding boxes interativos"""
        if image is None: return
        
        self.sprites = sprites or []
        self.selected_index = selected_index
        
        # Converter numpy para QImage
        if len(image.shape) == 2:
            h, w = image.shape
            q_img = QImage(image.data, w, h, w, QImage.Format.Format_Grayscale8)
        elif image.shape[2] == 3:
            h, w, c = image.shape
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            q_img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        else: # RGBA
            h, w, c = image.shape
            rgba = cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
            q_img = QImage(rgba.data, w, h, 4 * w, QImage.Format.Format_RGBA8888)
            
        pixmap = QPixmap.fromImage(q_img)
        
        self.scene.clear()
        self.pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.pixmap_item)
        self.scene.setSceneRect(QRectF(pixmap.rect()))
        
        # Desenhar bounding boxes como itens da cena (opcionalmente)
        # Mas para simplificar e manter performance, vamos apenas tratar o clique
        # e deixar o SpriteExtractor desenhar a imagem de preview para visualização.
        # SE quisermos interatividade real de arrastar, precisaríamos de QGraphicsRectItem.
        
        # Ajustar vista inicial se for a primeira carga
        if self.current_zoom == 1.0:
            self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        """Zoom com scroll do mouse"""
        if event.angleDelta().y() > 0:
            self.scale(self.zoom_factor, self.zoom_factor)
            self.current_zoom *= self.zoom_factor
        else:
            self.scale(1/self.zoom_factor, 1/self.zoom_factor)
            self.current_zoom /= self.zoom_factor

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.is_panning = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.LeftButton:
            # Seleção de sprite
            pos = self.mapToScene(event.pos())
            is_multi = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._handle_click(pos, is_multi)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_panning:
            delta = event.pos() - self.last_mouse_pos
            self.last_mouse_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton or event.button() == Qt.MouseButton.LeftButton:
            self.is_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def _handle_click(self, scene_pos, is_multi=False):
        """Verifica se o clique bateu em algum sprite"""
        for sprite in self.sprites:
            x, y, w, h = sprite.bbox
            if QRectF(x, y, w, h).contains(scene_pos):
                self.sprite_clicked.emit(sprite.index, is_multi)
                return
        self.sprite_clicked.emit(-1, False)

    def show_context_menu(self, pos):
        if self.selected_index == -1 and not self.multi_selected_indices:
            return
            
        menu = QMenu(self)
        
        from core.i18n import tr
        
        if len(self.multi_selected_indices) > 1:
            merge_action = QAction(tr("menu_merge_sprites"), self)
            merge_action.triggered.connect(lambda: self.merge_requested.emit(self.multi_selected_indices))
            menu.addAction(merge_action)
            
        if self.selected_index != -1 or len(self.multi_selected_indices) == 1:
            idx = self.selected_index if self.selected_index != -1 else self.multi_selected_indices[0]
            del_action = QAction(tr("menu_delete_sprite"), self)
            del_action.triggered.connect(lambda: self.delete_requested.emit(idx))
            menu.addAction(del_action)
            
        if not menu.isEmpty():
            menu.exec(self.mapToGlobal(pos))
