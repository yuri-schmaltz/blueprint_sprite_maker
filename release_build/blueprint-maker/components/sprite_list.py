from PyQt6.QtWidgets import QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QPixmap, QImage
from core.i18n import tr
import cv2

class SpriteList(QListWidget):
    """Componente para a lista de sprites detectados"""
    sprite_selected = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(64, 64))
        self.setGridSize(QSize(80, 100)) # Opcional: layout em grid ou lista com ícone grande
        self.setSpacing(5)
        self.setMinimumHeight(200)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.itemSelectionChanged.connect(self._on_selection_changed)
        
    def _on_selection_changed(self):
        selected_items = self.selectedItems()
        if selected_items:
            idx = selected_items[0].data(Qt.ItemDataRole.UserRole)
            self.sprite_selected.emit(idx)
        else:
            self.sprite_selected.emit(-1)
            
    def update_list(self, sprites, selected_index=-1):
        """Atualiza os itens da lista com base nos sprites fornecidos"""
        self.clear()
        selected_item = None
        
        view_map = {
            "front": tr("view_front"), "back": tr("view_back"), 
            "left": tr("view_left"), "right": tr("view_right"), 
            "top": tr("view_top"), "bottom": tr("view_bottom")
        }
        
        for sprite in sprites:
            x, y, w, h = sprite.bbox
            view_name = view_map.get(sprite.view_type, sprite.view_type.replace("_", " ").title())
            rot_label = f" ({sprite.rotation}°)" if sprite.rotation != 0 else ""
            
            item = QListWidgetItem(f"{view_name}{rot_label}\n{w}x{h}px")
            item.setData(Qt.ItemDataRole.UserRole, sprite.index)
            
            # Gerar thumbnail
            thumb = sprite.image.copy()
            if thumb.shape[2] == 3:
                thumb = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
                q_img = QImage(thumb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
            else:
                thumb = cv2.cvtColor(thumb, cv2.COLOR_BGRA2RGBA)
                q_img = QImage(thumb.data, w, h, 4 * w, QImage.Format.Format_RGBA8888)
            
            pixmap = QPixmap.fromImage(q_img)
            item.setIcon(QIcon(pixmap))
            
            self.addItem(item)
            
            if sprite.index == selected_index:
                selected_item = item
                
        if selected_item:
            self.blockSignals(True)
            self.setCurrentItem(selected_item)
            self.blockSignals(False)
