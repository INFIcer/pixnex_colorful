"""Shared headless renderer used by UI refactors and the layout checks.

Windows are rendered with ``Qt.WA_DontShowOnScreen``: the widget gets a real
native layout pass (so geometry, wrapping and scroll positions are final) but
is never displayed to the user.  The default Windows platform is used, which
means real system fonts – do **not** force ``QT_QPA_PLATFORM=offscreen``, the
offscreen plugin has no font database and renders tofu boxes.

Usage (from another script)::

    from tools.render_widget import UIHarness

    with UIHarness() as ui:
        window = build_my_window()
        ui.render(window, "my-window", sizes=[(360, 900), (520, 700)])
        problems = ui.bounds_problems(window)

Run directly to render a demo dialog:

    .venv\\Scripts\\python.exe tools/render_widget.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect, QSize, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractScrollArea, QApplication, QWidget,
)

from colorPickerPro.ui import apply_theme, configure_application  # noqa: E402

DEFAULT_SIZES: tuple[tuple[int, int], ...] = (
    (360, 640),
    (480, 760),
    (720, 900),
)


class UIHarness:
    """Owns the (single) QApplication used for hidden rendering."""

    def __init__(self, output_dir: str | Path = ROOT / "build" / "ui-preview"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._owns_app = QApplication.instance() is None
        if self._owns_app:
            configure_application()
            self.app = QApplication([])
            apply_theme(self.app)
        else:
            self.app = QApplication.instance()
        self._prepared: set[int] = set()

    # -- lifecycle -----------------------------------------------------
    def close(self) -> None:
        self.app.processEvents()

    def __enter__(self) -> "UIHarness":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- layout forcing ------------------------------------------------
    def prepare(self, widget: QWidget) -> None:
        """Give a (never shown) window a real layout pass without displaying it."""
        key = id(widget)
        if key in self._prepared:
            return
        widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        widget.ensurePolished()
        widget.show()
        self.app.processEvents()
        self.app.processEvents()
        self._prepared.add(key)

    def settle(self, widget: QWidget) -> None:
        widget.ensurePolished()
        if widget.layout() is not None:
            widget.layout().activate()
        self.app.processEvents()
        self.app.processEvents()

    # -- rendering -----------------------------------------------------
    def render(self, widget: QWidget, name: str,
               sizes: Sequence[tuple[int, int]] | None = None) -> list[Path]:
        """Grab *widget* at several sizes; returns the written PNG paths."""
        self.prepare(widget)
        paths: list[Path] = []
        for width, height in (sizes or DEFAULT_SIZES):
            widget.resize(width, height)
            self.settle(widget)
            target = self.output_dir / f"{name}_{width}x{height}.png"
            widget.grab().save(str(target))
            paths.append(target)
        return paths

    def render_sized(self, widget: QWidget, name: str,
                     sizes: Sequence[tuple[int, int]] | None = None) -> list[Path]:
        """Like :meth:`render` but names the file after the *actual* size.

        Frameless windows and dialogs may refuse to shrink below their layout
        minimum; naming by actual size keeps the evidence honest.
        """
        self.prepare(widget)
        paths: list[Path] = []
        for width, height in (sizes or DEFAULT_SIZES):
            widget.resize(width, height)
            self.settle(widget)
            actual = widget.size()
            target = self.output_dir / f"{name}_{actual.width()}x{actual.height()}.png"
            widget.grab().save(str(target))
            paths.append(target)
        return paths

    def render_minimum(self, widget: QWidget, name: str) -> Path:
        self.prepare(widget)
        widget.resize(widget.minimumSize())
        self.settle(widget)
        actual = widget.size()
        target = self.output_dir / f"{name}_min_{actual.width()}x{actual.height()}.png"
        widget.grab().save(str(target))
        return target

    # -- layout diagnostics -------------------------------------------
    def bounds_problems(self, widget: QWidget, *, tolerance: int = 1) -> list[str]:
        """Return geometry problems inside *widget*'s window.

        Checks every rendered (visible, non-hidden) descendant:
        - geometry must stay inside its parent;
        - a widget with a layout must not be smaller than its minimum size hint.

        Children of a scroll area viewport are allowed to be larger than the
        viewport (that is what scrolling means).
        """
        problems: list[str] = []
        top = widget.window()
        self.settle(top)
        for child in top.findChildren(QWidget):
            if child.isHidden() or child.isWindow():
                continue
            parent = child.parentWidget()
            if parent is None:
                continue
            if self._inside_scroll_viewport(child):
                continue
            geometry = child.geometry()
            parent_rect = parent.rect()
            if (geometry.left() < -tolerance
                    or geometry.top() < -tolerance
                    or geometry.right() > parent_rect.width() + tolerance
                    or geometry.bottom() > parent_rect.height() + tolerance):
                problems.append(
                    f"{child.objectName() or type(child).__name__} "
                    f"geometry={geometry.getRect()} outside parent "
                    f"{parent.objectName() or type(parent).__name__} "
                    f"{parent_rect.width()}x{parent_rect.height()}")
            hint = child.minimumSizeHint()
            if (child.layout() is not None and hint.isValid()
                    and (child.width() + tolerance < hint.width()
                         or child.height() + tolerance < hint.height())):
                problems.append(
                    f"{child.objectName() or type(child).__name__} "
                    f"size={child.width()}x{child.height()} below "
                    f"minimumSizeHint={hint.width()}x{hint.height()}")
        return problems

    @staticmethod
    def _inside_scroll_viewport(child: QWidget) -> bool:
        """True when *child* is (grand)child of a QAbstractScrollArea viewport."""
        parent = child.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                return False
            if parent.parentWidget() is not None and isinstance(
                    parent.parentWidget(), QAbstractScrollArea):
                return True  # child sits inside the scrollable content widget
            parent = parent.parentWidget()
        return False


def _demo() -> None:
    from colorPickerPro.ui.components import (
        Card, PrimaryButton, SubtitleLabel, ThemedDialog, TitleLabel, hbox,
    )

    class DemoDialog(ThemedDialog):
        def __init__(self):
            super().__init__("渲染工具自检", "多尺寸截图与布局体检")
            card = Card("示例卡片")
            card.add(TitleLabel("标题"))
            card.add(SubtitleLabel("一段可以换行的说明文字。" * 4))
            card.add_layout(hbox(PrimaryButton("确定"), None))
            self.add_content(card)
            self.add_reject_button()
            self.add_accept_button()
            self.resize(520, 420)

    harness = UIHarness()
    dialog = DemoDialog()
    paths = harness.render(dialog, "render-tool-demo",
                           sizes=[(360, 320), (520, 420), (760, 560)])
    problems = harness.bounds_problems(dialog)
    for path in paths:
        print("wrote", path)
    print("bounds problems:", problems or "none")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="render the demo dialog")
    parser.parse_args(list(argv) if argv is not None else None)
    _demo()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
