"""Qt table model backed by a pandas DataFrame (read-only)."""

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt


class PandasModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self._df = df.reset_index(drop=True)

    # -- required overrides --------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            val = self._df.iat[index.row(), index.column()]
            if pd.isna(val):
                return ""
            return str(val)
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    # -- sorting support -----------------------------------------------
    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        col = self._df.columns[column]
        ascending = order == Qt.SortOrder.AscendingOrder
        self.layoutAboutToBeChanged.emit()
        try:
            self._df = self._df.sort_values(
                col, ascending=ascending, kind="mergesort",
                key=lambda s: pd.to_numeric(s, errors="ignore"),
            ).reset_index(drop=True)
        except Exception:
            self._df = self._df.sort_values(col, ascending=ascending,
                                            kind="mergesort").reset_index(drop=True)
        self.layoutChanged.emit()
