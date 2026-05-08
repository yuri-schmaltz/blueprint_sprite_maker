import pytest
from core.i18n import I18nManager
from pathlib import Path

def test_i18n_singleton():
    """Test that I18nManager is a singleton."""
    i1 = I18nManager()
    i2 = I18nManager()
    assert i1 is i2

def test_i18n_load_default_locale():
    """Test loading English locale."""
    i18n = I18nManager()
    i18n.set_locale("en_US")
    assert i18n._current_locale == "en_US"
    assert i18n._translations.get("app_title") == "My Blueprint Maker"

def test_i18n_load_pt_br_locale():
    """Test loading Portuguese locale."""
    i18n = I18nManager()
    i18n.set_locale("pt_BR")
    assert i18n._current_locale == "pt_BR"
    assert i18n._translations.get("app_title") == "My Blueprint Maker"
    assert i18n._translations.get("tab_individual") == "Extrator Individual"

def test_tr_function_existing_key():
    i18n = I18nManager()
    i18n.set_locale("en_US")
    assert i18n.tr("tab_batch") == "Batch Processing"

def test_tr_function_missing_key():
    i18n = I18nManager()
    assert i18n.tr("non_existent_key") == "non_existent_key"

def test_tr_function_with_args():
    i18n = I18nManager()
    i18n.set_locale("en_US")
    # "msg_export_success": "5 sprites exported successfully to:\n/tmp/dir"
    res = i18n.tr("msg_export_success", 5, "/tmp/dir")
    assert "5 sprites exported successfully to:\n/tmp/dir" == res
