"""业务路由汇总：复核包交接专用路由在前，通用资源路由兜底，避免动态路径抢先匹配。"""
from __future__ import annotations

from app.routers import resource, review_pack

ROUTERS = [review_pack, resource]
