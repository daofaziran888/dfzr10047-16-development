"""复核包交接领域服务的 review_pack 命名别名模块，与 schema_review_pack 共享同一张结构复核包数据集。"""
from __future__ import annotations

from app.services.schema_review_pack import ReviewPackAliasService


class ReviewPackService(ReviewPackAliasService):
    """复核包服务：常见短命名入口，导出、回填、核验、解析消费与反查行为保持一致。"""

    MODULE = "review_pack"
