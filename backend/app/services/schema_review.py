"""结构复核（回填交接）领域服务的命名别名模块，与 schema_review_pack 共享同一张复核包交接数据集。"""
from __future__ import annotations

from app.services.schema_review_pack import _SharedTableAliasService


class SchemaReviewService(_SharedTableAliasService):
    """结构复核服务：类名/模块名的常见命名入口，行为与 SchemaReviewPackService 完全一致。"""

    MODULE = "schema_review"
