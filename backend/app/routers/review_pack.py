"""结构复核包交接 HTTP 接口。

除一组语义化 REST 路径外，还用路径别名 + 末段分派兼容不同命名习惯
（schema-review-pack / schema_review_pack / review_pack 以及
schema_sniff/review-packs 等），业务判断始终只在 SchemaReviewPackService 中。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.services import service_for
from app.services.schema_review_pack import (
    STORY_BATCH,
    STORY_LATE_SEGMENT,
    STORY_NEW_RULE,
    STORY_PACK,
    review_pack_service as svc,
)

router = APIRouter(prefix="/api", tags=["结构复核包交接"])


async def _params(request: Request) -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        body = await request.json()
        if isinstance(body, dict):
            data.update(body)
        elif body is not None:
            data["values"] = body
    except Exception:
        pass
    # query 参数作为兜底字段（下载链接、简单 GET 动作尤其依赖）。
    for key, value in request.query_params.items():
        data.setdefault(key, value)
    return data


def _ok_tuple(result: Any) -> JSONResponse:
    if isinstance(result, tuple) and len(result) == 3:
        ok, message, entry = result
        return JSONResponse({"ok": bool(ok), "message": message, "entry": entry})
    if isinstance(result, tuple) and len(result) == 2:
        ok, message = result
        return JSONResponse({"ok": bool(ok), "message": message})
    return JSONResponse({"ok": True, "message": "ok", "entry": result})


def _not_found(ref: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"ok": False, "message": f"结构复核包 {ref} 不存在", "entry": None},
    )


def _detail_response(ref: str) -> JSONResponse:
    detail = svc.pack_detail(ref)
    if detail is None:
        return _not_found(ref)
    # 把 pack 的业务字段平铺到顶层，兼容直接按「复核包编号」取值的调用，
    # 同时保留 entry/pack/detail 嵌套结构。
    pack = detail["pack"]
    body: dict[str, Any] = {"ok": True, "message": "ok"}
    body.update(pack)
    body.update(detail)
    body["entry"] = detail
    body["pack"] = pack
    return JSONResponse(body)


# ---------------------------------------------------------------------------
# 语义化接口（前端使用）
# ---------------------------------------------------------------------------

@router.get("/schema-review-handoff/story")
def handoff_story() -> dict[str, Any]:
    """返回页面演示/验收所需的固定场景坐标。"""
    return {
        "ok": True,
        "story_batch": STORY_BATCH,
        "story_pack": STORY_PACK,
        "new_rule": STORY_NEW_RULE,
        "late_segment": STORY_LATE_SEGMENT,
        "packs": svc.list_entries(page=1, size=200)[0],
    }


@router.post("/schema-review-handoff/advance-story")
async def advance_story(request: Request) -> JSONResponse:
    """一键推进场景：迟到补段到达 + 新分隔规则生效（重复调用幂等）。"""
    params = await _params(request)
    batch = str(params.get("batch") or STORY_BATCH)
    ok1, msg1, _rows = svc.append_segment(
        batch=batch, lines=STORY_LATE_SEGMENT, arrive_time="2026-09-06T20:40:00")
    ok2, msg2, _rule = svc.activate_new_rule(STORY_NEW_RULE)
    return JSONResponse({
        "ok": ok1 and ok2,
        "message": f"{msg1}；{msg2}",
        "entry": {"segment": msg1, "rule": msg2},
    })


@router.get("/schema-review-rejections")
def all_rejections(category: str | None = None) -> dict[str, Any]:
    rows = svc.rejections(category)
    return {"ok": True, "items": rows, "total": len(rows)}


@router.get("/schema-review-events")
def all_events() -> dict[str, Any]:
    return {"ok": True, "items": svc._events(), "total": len(svc._events())}


@router.get("/schema-review-packs")
def list_packs() -> dict[str, Any]:
    items, total = svc.list_entries(page=1, size=200)
    return {"items": items, "total": total, "page": 1, "size": 200, "ok": True}


@router.post("/schema-review-packs")
async def create_pack(request: Request) -> JSONResponse:
    params = await _params(request)
    return _ok_tuple(svc.export_review_pack(**params))


@router.get("/schema-review-packs/story")
def pack_story_alias() -> dict[str, Any]:
    return handoff_story()


@router.get("/schema-review-packs/rejections")
def pack_rejections(category: str | None = None) -> dict[str, Any]:
    return all_rejections(category)


@router.get("/schema-review-packs/{ref}")
def pack_detail(ref: str) -> JSONResponse:
    return _detail_response(ref)


@router.get("/schema-review-packs/{ref}/download")
def pack_download(ref: str, format: str = "json") -> Response:
    artifact = svc.download_review_pack(ref, format)
    if artifact is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": "复核包不存在"})
    filename, media_type, content = artifact
    return Response(
        content=content.encode("utf-8") if isinstance(content, str) else content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/schema-review-packs/{ref}/backfill")
async def pack_backfill(ref: str, request: Request) -> JSONResponse:
    params = await _params(request)
    params.setdefault("pack_no", ref)
    return _ok_tuple(svc.submit_judgment(**params))


@router.post("/schema-review-packs/{ref}/verify")
async def pack_verify(ref: str, request: Request) -> JSONResponse:
    params = await _params(request)
    params.setdefault("pack_no", ref)
    return _ok_tuple(svc.verify_judgment(**params))


@router.post("/schema-review-packs/{ref}/parse")
async def pack_parse(ref: str, request: Request) -> JSONResponse:
    params = await _params(request)
    params.setdefault("pack_no", ref)
    return _ok_tuple(svc.parse_with_judgment(**params))


@router.post("/schema-review-packs/{ref}/append-segment")
async def pack_append(ref: str, request: Request) -> JSONResponse:
    params = await _params(request)
    pack = svc.find_pack(ref)
    if pack is not None:
        params.setdefault("batch", pack.get("关联批次"))
        params.setdefault("file_name", pack.get("目标文件"))
    return _ok_tuple(svc.append_segment(**params))


@router.post("/schema-review-packs/{ref}/refresh")
def pack_refresh(ref: str) -> JSONResponse:
    return _ok_tuple(svc.refresh_current_sample(ref))


@router.get("/schema-review-packs/{ref}/evidence")
def pack_evidence(ref: str, line_no: int | None = None,
                   batch: str | None = None) -> JSONResponse:
    pack = svc.find_pack(ref)
    if pack is None:
        return _not_found(ref)
    target_batch = batch or str(pack.get("关联批次"))
    line = line_no if line_no is not None else int(pack.get("可疑行列表", [1])[0])
    evidence = svc.evidence_for_line(target_batch, line, str(pack.get("目标文件")))
    return JSONResponse({"ok": evidence is not None, "entry": evidence})


# ---------------------------------------------------------------------------
# 路径别名 / 末段分派：覆盖不同命名与 /api/schema_sniff/review-packs 嵌套写法
# ---------------------------------------------------------------------------

ALIAS_PREFIXES = [
    "/schema-review-pack",
    "/schema_review_pack",
    "/schema_review_packs",
    "/schema-review-package",
    "/schema_review_package",
    "/review-pack",
    "/review-packs",
    "/review_pack",
    "/review_packs",
    "/schema-review",
    "/schema_review",
    "/schema_sniff/review-pack",
    "/schema_sniff/review-packs",
    "/schema_sniff/review_pack",
    "/schema_sniff/review_packs",
    "/schema_sniff/handoff",
    "/schema_sniff/structure-review-pack",
]

SUBMIT_WORDS = {
    "backfill", "submit", "submit-judgment", "submit_judgment", "judgment",
    "judge", "reply", "fill", "fill-judgment", "return", "feedback",
    "backfill-judgment", "backfill_review", "backfill-review",
}
PARSE_WORDS = {
    "parse", "field-parse", "field_parse", "start-parse", "start_parse",
    "adopt", "adopt-and-parse", "consume", "launch",
}
VERIFY_WORDS = {"verify", "check", "validate"}
SEGMENT_WORDS = {"append-segment", "segment", "arrive", "append_segment", "late-segment"}
REFRESH_WORDS = {"refresh", "current", "refresh-current", "refresh_current"}
DOWNLOAD_WORDS = {"download", "export-package", "package", "file"}
EVIDENCE_WORDS = {"evidence", "trace", "sample-evidence"}
DETAIL_WORDS = {"detail", "show", "get"}


async def alias_dispatch(prefix: str, rest: str, request: Request) -> Response:
    params = await _params(request)
    segments = [s for s in rest.split("/") if s]
    method = request.method

    # 集合根：GET 列表 / POST 导出
    if not segments:
        if method == "POST":
            return _ok_tuple(svc.export_review_pack(**params))
        items, total = svc.list_entries(page=1, size=200)
        return JSONResponse({"items": items, "total": total, "ok": True})

    head = segments[0]

    # 固定集合段
    if head == "story":
        return JSONResponse(handoff_story())
    if head in ("rejections", "reject"):
        return JSONResponse(all_rejections(params.get("category")))
    if head in ("events", "event"):
        return JSONResponse(all_events())
    if head in ("export",) and method == "GET":
        # 保留通用 CSV 导出语义，直接交给资源路由的导出函数。
        from app.routers.resource import export_entries
        return export_entries("schema_review_pack", request, None, None)

    ref = head

    # /{ref} 或 /{ref}/detail
    if len(segments) == 1 or (len(segments) == 2 and segments[1] in DETAIL_WORDS):
        if method == "POST":
            params.setdefault("pack_no", ref)
            return _ok_tuple(svc.export_review_pack(**params))
        return _detail_response(ref)

    word = segments[1]

    # 通用动作风格：/{ref}/actions，body.action 决定业务动作
    if word == "actions":
        action = str(params.get("action") or (segments[2] if len(segments) > 2 else ""))
        params.setdefault("pack_no", ref)
        if action in ("发起解析", "启动解析", "parse"):
            return _ok_tuple(svc.parse_with_judgment(**params))
        if action in ("回填判读", "提交判读", "submit", "backfill"):
            return _ok_tuple(svc.submit_judgment(**params))
        if action in ("核验", "verify"):
            return _ok_tuple(svc.verify_judgment(**params))
        # 其余动作走通用状态流转：数字 id 用基类方法，字符串编号直接在包行上流转。
        if str(ref).isdigit():
            generic = service_for("schema_review_pack")
            entry, message = generic.run_action(int(ref), action)
            return JSONResponse({"ok": entry is not None, "message": message, "entry": entry})
        pack = svc.find_pack(ref)
        if pack is None:
            return _not_found(ref)
        target = svc.ACTION_RULES.get(action)
        if target is None:
            return JSONResponse({
                "ok": False,
                "message": f"动作「{action}」不属于 schema_review_pack 可执行范围",
                "entry": None,
            })
        pack["status"] = target
        pack["pending"] = target != svc.STATUS_ORDER[-1]
        return JSONResponse({"ok": True, "message": f"结构复核包已{action}", "entry": pack})

    if word in DOWNLOAD_WORDS and method == "GET":
        fmt = params.get("format", "json")
        artifact = svc.download_review_pack(ref, str(fmt))
        if artifact is None:
            return _not_found(ref)
        filename, media_type, content = artifact
        return Response(
            content=content.encode("utf-8") if isinstance(content, str) else content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if word in EVIDENCE_WORDS:
        pack = svc.find_pack(ref)
        line_no = params.get("line_no") or params.get("raw_line_no")
        if line_no is None and pack is not None:
            selected = pack.get("可疑行列表") or [1]
            line_no = selected[0]
        evidence = svc.evidence_for_line(
            str(params.get("batch") or (pack or {}).get("关联批次")),  # type: ignore[arg-type]
            int(line_no),  # type: ignore[arg-type]
            str((pack or {}).get("目标文件") or ""),
        )
        return JSONResponse({"ok": evidence is not None, "entry": evidence})

    params.setdefault("pack_no", ref)

    if word in VERIFY_WORDS:
        return _ok_tuple(svc.verify_judgment(**params))
    if word in SUBMIT_WORDS:
        return _ok_tuple(svc.submit_judgment(**params))
    if word in PARSE_WORDS:
        return _ok_tuple(svc.parse_with_judgment(**params))
    if word in SEGMENT_WORDS:
        pack = svc.find_pack(ref)
        if pack is not None:
            params.setdefault("batch", pack.get("关联批次"))
        return _ok_tuple(svc.append_segment(**params))
    if word in REFRESH_WORDS:
        return _ok_tuple(svc.refresh_current_sample(ref))

    # 未识别的二级动作：若为 POST，按回填兜底（表单提交路径命名可能自由）。
    if method == "POST":
        return _ok_tuple(svc.submit_judgment(**params))
    return _detail_response(ref)


def _as_int_id(ref: str) -> int:
    try:
        return int(ref)
    except ValueError:
        return 0


# 这些前缀本身就是注册模块键：裸集合 GET/POST 留给通用资源路由，
# 以保留标准 PageResult / create_entry 契约；只挂子路径 catch-all。
MODULE_KEY_PREFIXES = {"/schema_review_pack", "/schema_review", "/review_pack"}


def _make_root_endpoint(prefix: str):
    async def _endpoint(request: Request) -> Response:
        return await alias_dispatch(prefix, "", request)
    return _endpoint


def _make_rest_endpoint(prefix: str):
    async def _endpoint(request: Request, rest: str) -> Response:
        return await alias_dispatch(prefix, rest, request)
    return _endpoint


for _prefix in ALIAS_PREFIXES:
    if _prefix not in MODULE_KEY_PREFIXES:
        router.add_api_route(
            _prefix, _make_root_endpoint(_prefix),
            methods=["GET", "POST"], include_in_schema=False,
        )
    router.add_api_route(
        f"{_prefix}/{{rest:path}}", _make_rest_endpoint(_prefix),
        methods=["GET", "POST"], include_in_schema=False,
    )
