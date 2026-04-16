"""Qt table model backed by a pandas DataFrame (editable, sortable)."""

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt


NUMERIC_COLS = {"Payload [Kg]", "Weight [Kg]", "Cost", "Max Length [mm]"}


class PandasModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        # NOTE: reset_index returns a new DataFrame -- edits land in this copy.
        # Use `.dataframe()` to read the edited frame back.
        self._df = df.reset_index(drop=True)

    # ----- required overrides ------------------------------------------
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

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """Write back to the DataFrame. Emits dataChanged on success."""
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        col_name = self._df.columns[index.column()]
        # Coerce numeric columns; reject non-numeric input for them.
        if col_name in NUMERIC_COLS:
            if value in ("", None):
                coerced = 0.0
            else:
                try:
                    coerced = float(value)
                except (ValueError, TypeError):
                    return False
            self._df.iat[index.row(), index.column()] = coerced
        else:
            self._df.iat[index.row(), index.column()] = str(value)
        self.dataChanged.emit(index, index, [role])
        return True

    def flags(self, index):
        """Make every cell editable + selectable + enabled."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (Qt.ItemFlag.ItemIsEditable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)

    # ----- sorting support ---------------------------------------------
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

    # ----- public API --------------------------------------------------
    def dataframe(self) -> pd.DataFrame:
        """Return a reference to the (possibly edited) underlying DataFrame."""
        return self._df
