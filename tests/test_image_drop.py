"""Tests for ``ImageDropWidget``'s ``show_dropped_image`` switch.

The main window only needs the image that was dropped (it opens the compare
window); it must keep showing its placeholder instead of the dropped image.
The switch defaults to off: dropping / pasting must still emit
``imageReceived`` but must not write the widget's own ``_pixmap``.

Run directly (no pytest required):

    .venv\\Scripts\\python.exe tests\\test_image_drop.py
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QMimeData, QUrl  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from colorPickerPro.image_drop_widget import ImageDropWidget  # noqa: E402

_APP = None


def _app() -> QApplication:
    global _APP
    if _APP is None:
        from colorPickerPro.ui import apply_theme, configure_application

        configure_application()
        _APP = QApplication.instance() or QApplication([])
        apply_theme(_APP)
    return _APP


def _image(width: int = 8, height: int = 6) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0xFF0080FF)
    return image


def _image_mime(width: int = 8, height: int = 6) -> QMimeData:
    mime = QMimeData()
    mime.setImageData(_image(width, height))
    return mime


def _temp_png(width: int = 8, height: int = 6) -> str:
    path = Path(tempfile.mkdtemp(prefix="pixnex-drop-")) / "sample.png"
    assert _image(width, height).save(str(path), "PNG"), "测试图片写入失败"
    return str(path)


def _collect(widget):
    received = []
    widget.imageReceived.connect(lambda pm, name: received.append((pm, name)))
    return received


def test_show_dropped_image_defaults_to_false():
    _app()
    widget = ImageDropWidget()
    assert widget.show_dropped_image is False
    assert widget.pixmap().isNull()


def test_default_drop_emits_but_does_not_store_image():
    _app()
    widget = ImageDropWidget()
    received = _collect(widget)
    widget._process_mime_data(_image_mime())
    assert len(received) == 1, "拖入图像后应发出 imageReceived"
    pixmap, name = received[0]
    assert not pixmap.isNull() and name == ""
    assert pixmap.width() == 8 and pixmap.height() == 6
    assert widget.pixmap().isNull(), (
        "show_dropped_image 关闭时不应把拖入的图像写入 _pixmap")


def test_default_url_drop_emits_but_does_not_store_image():
    _app()
    path = _temp_png()
    widget = ImageDropWidget()
    received = _collect(widget)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    widget._process_mime_data(mime)
    assert len(received) == 1
    pixmap, name = received[0]
    assert not pixmap.isNull()
    assert name == "sample.png", name
    assert widget.pixmap().isNull()


def test_default_text_path_drop_emits_but_does_not_store_image():
    _app()
    path = _temp_png()
    widget = ImageDropWidget()
    received = _collect(widget)
    mime = QMimeData()
    mime.setText(path)
    widget._process_mime_data(mime)
    assert len(received) == 1
    assert received[0][1] == "sample.png"
    assert widget.pixmap().isNull()


def test_enabled_drop_stores_image():
    _app()
    widget = ImageDropWidget(show_dropped_image=True)
    received = _collect(widget)
    widget._process_mime_data(_image_mime(12, 9))
    assert len(received) == 1
    assert not widget.pixmap().isNull(), (
        "show_dropped_image 打开时应显示拖入的图像")
    assert widget.pixmap().width() == 12
    assert widget.pixmap().height() == 9


def test_enabled_url_drop_stores_image():
    _app()
    path = _temp_png(10, 7)
    widget = ImageDropWidget(show_dropped_image=True)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    widget._process_mime_data(mime)
    assert not widget.pixmap().isNull()
    assert widget.pixmap().width() == 10
    assert widget.pixmap().height() == 7


def test_switch_can_be_toggled_at_runtime():
    _app()
    widget = ImageDropWidget()
    assert widget.show_dropped_image is False

    widget.show_dropped_image = True
    widget._process_mime_data(_image_mime(5, 4))
    assert not widget.pixmap().isNull(), "打开开关后拖入的图像应显示"
    assert widget.pixmap().width() == 5

    widget.show_dropped_image = False
    received = _collect(widget)
    widget._process_mime_data(_image_mime(9, 6))
    assert len(received) == 1, "关闭开关后仍应发出 imageReceived"
    assert widget.pixmap().width() == 5, (
        "关闭开关后拖入的新图像不应覆盖已有 _pixmap")


def test_explicit_set_pixmap_still_works_when_switch_is_off():
    _app()
    widget = ImageDropWidget()
    assert widget.show_dropped_image is False
    from PySide6.QtGui import QPixmap

    widget.set_pixmap(QPixmap.fromImage(_image(4, 3)))
    assert not widget.pixmap().isNull(), "set_pixmap 是显式接口，不受开关影响"
    assert widget.pixmap().width() == 4


def test_drop_event_keeps_placeholder_when_switch_off():
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QDropEvent

    _app()
    widget = ImageDropWidget()
    received = _collect(widget)
    mime = _image_mime()   # 保持引用：QDropEvent 不接管 QMimeData 的所有权
    event = QDropEvent(
        QPointF(10, 10), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    widget.dropEvent(event)
    assert len(received) == 1, "dropEvent 仍应把图像交给调用方"
    assert widget.pixmap().isNull(), "dropEvent 不应写入 _pixmap"
    assert widget.property("dragActive") is False


def test_clipboard_paste_keeps_placeholder_when_switch_off():
    _app()
    _app().clipboard().setImage(_image(6, 5))
    widget = ImageDropWidget()
    received = _collect(widget)
    widget._paste_from_clipboard()
    assert len(received) == 1, "Ctrl+V 粘贴仍应把图像交给调用方"
    assert widget.pixmap().isNull(), "粘贴不应写入 _pixmap"


# ---------------------------------------------------------------------------
# runner (stdlib only)
# ---------------------------------------------------------------------------

def _main() -> int:
    tests = [
        test_show_dropped_image_defaults_to_false,
        test_default_drop_emits_but_does_not_store_image,
        test_default_url_drop_emits_but_does_not_store_image,
        test_default_text_path_drop_emits_but_does_not_store_image,
        test_enabled_drop_stores_image,
        test_enabled_url_drop_stores_image,
        test_switch_can_be_toggled_at_runtime,
        test_explicit_set_pixmap_still_works_when_switch_is_off,
        test_drop_event_keeps_placeholder_when_switch_off,
        test_clipboard_paste_keeps_placeholder_when_switch_off,
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS  {test.__name__}")
    print(f"\n共 {len(tests)} 项检查，失败 {failed} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
