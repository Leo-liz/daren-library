"""Authorized data-source adapter seam for manual import and future providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Mapping

from importer import ImportResult, PLATFORM, import_xlsx


class DataAdapter(ABC):
    """Common fetch/import contract. Implementations must honor provider authorization."""

    platform: str

    @abstractmethod
    def fetch(self, request: Mapping[str, Any]) -> Any:
        """Fetch data through an explicitly authorized provider connection."""

    @abstractmethod
    def import_data(
        self, db_path: str | Path, source_type: str, source: str | Path
    ) -> ImportResult:
        """Import a provider export into the normalized local store."""


class TikTokManualImportAdapter(DataAdapter):
    """TikTok Shop VN adapter implemented only as standardized manual XLSX import."""

    platform = PLATFORM

    def fetch(self, request: Mapping[str, Any]) -> Any:
        raise NotImplementedError("本期未连接 TikTok API；只支持授权后台导出的 XLSX 人工导入")

    def import_data(
        self, db_path: str | Path, source_type: str, source: str | Path
    ) -> ImportResult:
        return import_xlsx(db_path, source, source_type, self.platform)


class ShopeeAdapter(DataAdapter):
    """Interface-only placeholder; no collection, synchronization, or scraping."""

    platform = "shopee"

    def fetch(self, request: Mapping[str, Any]) -> Any:
        raise NotImplementedError("Shopee 适配器仅占位；需开放接口权限与单独立项后实现")

    def import_data(
        self, db_path: str | Path, source_type: str, source: str | Path
    ) -> ImportResult:
        raise NotImplementedError("Shopee 标准化导入映射尚未实现")
