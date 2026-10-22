"""Frameless file picker built on an embedded QFileDialog.

The native QFileDialog lives in its own OS window and would break the uniform
custom chrome.  Embedding it as a plain widget inside :class:`ThemedDialog`
keeps Qt's complete file-browsing behaviour while all visible chrome (title bar,
close button, border) stays ours.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QPushButton, QWidget,
)

from ..theme import repolish
from ..tokens import Variant
from .dialogs import ThemedDialog, confirm


def _split_filters(filters: str) -> list[str]:
    return [part.strip() for part in (filters or "").split(";;") if part.strip()]


class FileDialog(ThemedDialog):
    """Themed, frameless wrapper around an embedded QFileDialog."""

    def __init__(self, parent: QWidget | None, title: str, *,
                 directory: str = "", filters: str = "",
                 save: bool = False, default_suffix: str = ""):
        super().__init__(title, parent=parent)
        self._save = save
        self._inner = QFileDialog(self)
        self._inner.setWindowFlags(Qt.WindowType.Widget)
        self._inner.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self._inner.setAcceptMode(
            QFileDialog.AcceptMode.AcceptSave if save
            else QFileDialog.AcceptMode.AcceptOpen)
        self._inner.setFileMode(
            QFileDialog.FileMode.AnyFile if save
            else QFileDialog.FileMode.ExistingFile)
        if filters:
            self._inner.setNameFilters(_split_filters(filters))
        if directory:
            self._inner.setDirectory(directory)
        if default_suffix:
            self._inner.setDefaultSuffix(default_suffix)
        if save:
            # 覆盖确认由我们自己做，避免 QFileDialog 内部再弹系统样式消息框。
            self._inner.setOption(
                QFileDialog.Option.DontConfirmOverwrite, True)
        self._set_labels(save)
        self._inner.accepted.connect(self.accept)
        self._inner.rejected.connect(self.reject)
        self.add_content(self._inner, 1)
        self._primary_style()
        self.resize(840, 620)

    # ------------------------------------------------------------------
    def _set_labels(self, save: bool) -> None:
        labels = {
            QFileDialog.DialogLabel.LookIn: "位置",
            QFileDialog.DialogLabel.FileName: "文件名",
            QFileDialog.DialogLabel.FileType: "文件类型",
            QFileDialog.DialogLabel.Accept: "保存" if save else "打开",
            QFileDialog.DialogLabel.Reject: "取消",
        }
        for label, text in labels.items():
            self._inner.setLabelText(label, text)

    def _primary_style(self) -> None:
        box = self._inner.findChild(QDialogButtonBox)
        if box is None:
            return
        ok = box.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setProperty("variant", Variant.PRIMARY)
            repolish(ok)
        cancel = box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel is not None:
            cancel.setProperty("variant", Variant.DEFAULT)
            repolish(cancel)

    # ------------------------------------------------------------------
    def selected_files(self) -> list[str]:
        return [path for path in self._inner.selectedFiles() if path]

    def selected_filter(self) -> str:
        return self._inner.selectedNameFilter()


def _run(dialog: FileDialog) -> list[str]:
    """Execute the picker, handling save-overwrite confirmation ourselves."""
    while True:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return []
        files = dialog.selected_files()
        if not files or not dialog._save:
            return files
        target = Path(files[0])
        if not target.exists():
            return files
        if confirm(dialog, "覆盖文件", f"文件已存在：\n{target.name}\n\n是否覆盖？",
                   ok_text="覆盖"):
            return files


def get_open_file_name(parent: QWidget | None, title: str,
                       directory: str = "", filters: str = "") -> tuple[str, str]:
    """Frameless replacement for ``QFileDialog.getOpenFileName``."""
    dialog = FileDialog(parent, title, directory=directory, filters=filters)
    files = _run(dialog)
    return (files[0] if files else ""), dialog.selected_filter()


def get_save_file_name(parent: QWidget | None, title: str,
                       directory: str = "", filters: str = "",
                       default_suffix: str = "") -> tuple[str, str]:
    """Frameless replacement for ``QFileDialog.getSaveFileName``."""
    dialog = FileDialog(parent, title, directory=directory, filters=filters,
                        save=True, default_suffix=default_suffix)
    files = _run(dialog)
    return (files[0] if files else ""), dialog.selected_filter()


__all__ = ["FileDialog", "get_open_file_name", "get_save_file_name"]
