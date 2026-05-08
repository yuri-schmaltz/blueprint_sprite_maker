import json
import os
from pathlib import Path

class I18nManager:
    _instance = None
    _translations = {}
    _current_locale = "pt_BR"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(I18nManager, cls).__new__(cls)
            cls._instance._load_translations()
        return cls._instance

    def _load_translations(self):
        locales_dir = Path(__file__).parent.parent / "locales"
        locale_path = locales_dir / f"{self._current_locale}.json"
        
        if not locale_path.exists():
            # Fallback to en_US if pt_BR is missing, or vice versa
            self._current_locale = "en_US"
            locale_path = locales_dir / "en_US.json"

        if locale_path.exists():
            with open(locale_path, "r", encoding="utf-8") as f:
                self._translations = json.load(f)
        else:
            self._translations = {}

    def set_locale(self, locale):
        if self._current_locale != locale:
            self._current_locale = locale
            self._load_translations()

    def tr(self, key, *args):
        text = self._translations.get(key, key)
        if args:
            try:
                return text.format(*args)
            except (IndexError, KeyError):
                return text
        return text

# Global instance
_i18n = I18nManager()

def tr(key, *args):
    return _i18n.tr(key, *args)
