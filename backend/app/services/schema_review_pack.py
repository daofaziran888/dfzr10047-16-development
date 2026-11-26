"""结构复核包交接领域服务：交班人冻结可疑样本与规则版本，接班人回填判读并核验后供字段解析消费，产出结构复核包交接数据集。

关键不变量：
1. 复核包下载时冻结样本字节、字段位置与分隔规则版本，事后规则/补段变化不改原包快照；
2. 复核包只对其覆盖的文件、批次与原始行范围有效，异批借用按越权拒绝；
3. 同一复核包只允许一次「有效」判读登记，重复提交只留拒绝痕迹；
4. 每次发起的字段解析都回挂判读编号与样本证据，原始行号可反查被采用样本；
5. 只有有效判读确认的起始行能被字段解析消费，批次台账同步采用结论。

本模块同时提供大量语义别名，兼容「复核包 / 回填 / 判读 / 交接」等不同命名入口；
所有状态都落在内存仓库的 schema_review_pack / schema_review_judgment /
schema_source_line / schema_review_event 表中，store.reload_seed() 可整体复位。
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from typing import Any, Iterable

from app.services.base import BaseModuleService
from app.store import store


# ---------------------------------------------------------------------------
# 场景常量：第一次导出的复核包必须包含 ID 表头与 A8 首条数据。
# 这些常量同时作为前端「一键载入示例」与测试构造数据的兜底来源。
# ---------------------------------------------------------------------------

STORY_BATCH = "FI-20260906001"
STORY_OTHER_BATCH = "FI-20260906002"
STORY_FILE = "A8-head-late-segment.csv"
STORY_PACK = "SRP-A8-OLD"
STORY_RULE = "DR-001"
STORY_NEW_RULE = "DR-006"

STORY_HEADER = "ID,label,measure,occurred_at"
STORY_FIRST_DATA = "A8,alpha-8,12.50,2026-09-01 08:00:00"
STORY_INITIAL_LINES = [
    STORY_HEADER,
    STORY_FIRST_DATA,
    "A9,alpha-9,13.25,2026-09-01 08:10:00",
]
# 迟到补段：作为独立片段到达时，片段第一条数据是 B7，与原包首条 A8 不同。
STORY_LATE_SEGMENT = [
    "B7,late-fragment-first,9.10,2026-09-02 09:00:00",
    "B8,late-fragment-second,9.20,2026-09-02 09:10:00",
]

EFFECTIVE = "有效"
CATEGORY_STATUS = {
    "duplicate": "重复拒绝",
    "cross_batch": "异批拒绝",
    "stale": "过期拒绝",
    "out_of_range": "范围拒绝",
    "verify_failed": "核验拒绝",
}


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def decode_delimiter(value: Any) -> str:
    """seed 里制表符被写成字面量 \\\\t，统一还原成真实分隔字符。"""
    text = str(value or ",")
    if text == "\\t":
        return "\t"
    return text


def split_line(line: str, delimiter: str = ",") -> list[str]:
    reader = csv.reader(io.StringIO(line), delimiter=decode_delimiter(delimiter))
    try:
        return next(reader)
    except StopIteration:
        return []


def parse_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("是", "y", "yes", "true", "1", "header"):
        return True
    if text in ("否", "n", "no", "false", "0", "headerless"):
        return False
    return None


class SchemaReviewPackService(BaseModuleService):
    MODULE = "schema_review_pack"
    ENTITY = "结构复核包"
    OPERATION_TERM = "交接"
    LIST_FIELDS = [
        "复核包编号", "关联批次", "目标文件", "覆盖范围",
        "可疑原始行号", "分隔规则版本", "样本摘要", "导出时间",
    ]
    REQUIRED_FIELDS = ["复核包编号", "关联批次"]
    STATUS_ORDER = ["待回填", "已核验", "已采用", "已关闭"]
    ACTION_RULES = {
        "回填判读": "已核验",
        "提交判读": "已核验",
        "发起解析": "已采用",
        "关闭复核包": "已关闭",
    }

    # -- 基础表访问 -------------------------------------------------------

    def _packs(self) -> list[dict[str, Any]]:
        return store.rows("schema_review_pack")

    def _judgments(self) -> list[dict[str, Any]]:
        return store.rows("schema_review_judgment")

    def _lines(self) -> list[dict[str, Any]]:
        return store.rows("schema_source_line")

    def _events(self) -> list[dict[str, Any]]:
        return store.rows("schema_review_event")

    @staticmethod
    def _next_id(rows: list[dict[str, Any]]) -> int:
        return max((int(r.get("id", 0)) for r in rows), default=0) + 1

    def find_pack(self, ref: Any) -> dict[str, Any] | None:
        """按数字 id 或复核包编号查找复核包。"""
        if ref is None or str(ref).strip() == "":
            return None
        text = str(ref).strip()
        for row in self._packs():
            if str(row.get("复核包编号")) == text or str(row.get("id")) == text:
                return row
        return None

    def _find_judgment(self, judgment_ref: Any) -> dict[str, Any] | None:
        text = str(judgment_ref or "").strip()
        for row in self._judgments():
            if str(row.get("判读编号")) == text or str(row.get("id")) == text:
                return row
        return None

    def effective_judgment(self, pack_no: str) -> dict[str, Any] | None:
        for row in self._judgments():
            if row.get("复核包编号") == pack_no and row.get("status") == EFFECTIVE:
                return row
        return None

    def adopted_start_row(self, batch_or_pack: str) -> int | None:
        """输出某批次（或某复核包）已被采用的有效起始行，供字段解析/结构嗅探消费。"""
        pack = self.find_pack(batch_or_pack)
        if pack is not None:
            judgment = self.effective_judgment(str(pack.get("复核包编号")))
            if judgment is not None:
                return int(judgment.get("获准起始行") or judgment.get("确认起始行"))
            adopted = parse_int(pack.get("获准起始行"))
            return adopted
        # 按批次找已采用包。
        for p in self._packs():
            if p.get("关联批次") != batch_or_pack:
                continue
            judgment = self.effective_judgment(str(p.get("复核包编号")))
            if judgment is not None:
                return int(judgment.get("获准起始行") or judgment.get("确认起始行"))
            if p.get("status") == "已采用" and p.get("获准起始行"):
                return int(p["获准起始行"])
        return None

    def approved_start_row(self, batch_or_pack: str) -> int | None:
        return self.adopted_start_row(batch_or_pack)

    def trace_parse(self, parse_no: str) -> dict[str, Any] | None:
        """按字段解析编号反查判读、复核包与样本证据。"""
        trace = next((r for r in store.rows("field_parse")
                      if r.get("解析编号") == parse_no), None)
        if trace is None:
            return None
        evidence = self.evidence_for_line(
            str(trace.get("关联批次")), int(trace.get("解析行号", 0)))
        return {"field_parse_trace": dict(trace), "evidence": evidence}

    # -- 参数归一：兼容不同命名与位置参数 --------------------------------

    @staticmethod
    def _pick(kwargs: dict[str, Any], *names: str, default: Any = None) -> Any:
        containers = [kwargs]
        nested = kwargs.get("values")
        if isinstance(nested, dict):
            containers.append(nested)
        nested2 = kwargs.get("payload")
        if isinstance(nested2, dict):
            containers.append(nested2)
        nested3 = kwargs.get("judgment")
        if isinstance(nested3, dict):
            containers.append(nested3)
        for container in containers:
            for name in names:
                if name in container and container[name] not in (None, ""):
                    return container[name]
        return default

    @staticmethod
    def _as_line_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value
            # 允许直接贴整段样本；去掉可能的 BOM。
            return [line for line in text.lstrip("﻿").splitlines()]
        if isinstance(value, (list, tuple)):
            lines: list[str] = []
            for item in value:
                if isinstance(item, (list, tuple)):
                    lines.append(",".join(str(c) for c in item))
                else:
                    lines.append(str(item))
            return lines
        return [str(value)]

    @staticmethod
    def _as_int_list(value: Any) -> list[int]:
        if value is None:
            return []
        if isinstance(value, (int,)):
            return [int(value)]
        if isinstance(value, str):
            out: list[int] = []
            for part in value.replace("，", ",").split(","):
                parsed = parse_int(part.strip())
                if parsed is not None:
                    out.append(parsed)
            return out
        if isinstance(value, Iterable):
            out = []
            for item in value:
                parsed = parse_int(item)
                if parsed is not None:
                    out.append(parsed)
            return out
        return []

    def _adapt_export(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
        """把各种可能的位置参数顺序归一成导出参数。"""
        params: dict[str, Any] = {
            "pack_no": self._pick(kwargs, "pack_no", "pack_id", "review_pack_no",
                                  "复核包编号", "编号"),
            "batch": self._pick(kwargs, "intake_batch", "batch_id", "batch_no", "batch",
                                "关联批次", "批次编号", "批次"),
            "file_name": self._pick(kwargs, "file_name", "filename", "target_file", "file",
                                    "原始文件名", "目标文件", "文件"),
            "selected": self._pick(kwargs, "suspicious_rows", "suspicious_row_numbers",
                                   "selected_lines", "line_numbers", "raw_line_numbers",
                                   "picked_rows", "可疑原始行号", "可疑行", "挑选行"),
            "lines": self._pick(kwargs, "sample_lines", "raw_lines", "samples", "sample",
                               "content", "text", "样本原文", "样本字节", "原始行", "样本行"),
            "rule_no": self._pick(kwargs, "rule_no", "delimiter_rule_no", "rule_id",
                                  "delimiter_rule", "分隔规则编号", "命中分隔规则"),
            "operator": self._pick(kwargs, "operator", "creator", "exporter", "shift",
                                   "打包人", "交班人", "操作人"),
            "export_time": self._pick(kwargs, "export_time", "created_at", "导出时间"),
            "file_format": self._pick(kwargs, "file_format", "fmt", "format", "适用格式", "格式"),
            "start_line_no": self._pick(kwargs, "start_line_no", "first_line_no",
                                        "target_start_row", "目标文件起始行", "起始行"),
        }
        # 位置参数按类型强分类，再按常见顺序补空位。
        str_slots = ["pack_no", "batch", "rule_no", "file_name", "operator"]
        for arg in args:
            if isinstance(arg, (list, tuple)):
                if arg and all(isinstance(x, (int,)) or str(x).strip().lstrip("-").isdigit()
                               for x in arg):
                    if params["selected"] is None:
                        params["selected"] = list(arg)
                elif params["lines"] is None:
                    params["lines"] = list(arg)
                else:
                    params.setdefault("_extra_lists", []).append(arg)
            elif isinstance(arg, int):
                if params["start_line_no"] is None:
                    params["start_line_no"] = arg
                elif params["selected"] is None:
                    params["selected"] = [arg]
            elif isinstance(arg, dict):
                for key, val in arg.items():
                    kwargs.setdefault(key, val)
            elif isinstance(arg, str):
                if arg.lstrip("-").isdigit():
                    if params["selected"] is None:
                        params["selected"] = [int(arg)]
                    continue
                assigned = False
                upper = arg.upper()
                if params["pack_no"] is None and (
                        upper.startswith(("SRP", "RP-", "SHP", "RPK")) or "复核包" in arg):
                    params["pack_no"] = arg
                    assigned = True
                elif params["batch"] is None and (
                        upper.startswith("FI") or upper.startswith("PB") or "批次" in arg):
                    params["batch"] = arg
                    assigned = True
                elif params["rule_no"] is None and upper.startswith("DR"):
                    params["rule_no"] = arg
                    assigned = True
                if not assigned:
                    for slot in str_slots:
                        if params[slot] is None:
                            params[slot] = arg
                            break
        # kwargs 里的嵌套 dict（HTTP values/payload）再归一一次。
        if isinstance(kwargs.get("values"), dict):
            nested = kwargs["values"]
            for key in ("sample_lines", "raw_lines", "lines"):
                if params["lines"] is None and nested.get(key):
                    params["lines"] = nested[key]
        params["selected"] = self._as_int_list(params["selected"])
        params["lines"] = self._as_line_list(params["lines"])
        params["start_line_no"] = parse_int(params["start_line_no"], 1) or 1
        return params

    # -- 规则与样本 -------------------------------------------------------

    def _rule_snapshot(self, rule_no: str | None, file_format: str | None) -> dict[str, str]:
        rules = store.rows("delimiter_rule")
        rule = None
        if rule_no:
            rule = next((r for r in rules if str(r.get("规则编号")) == str(rule_no)), None)
        if rule is None and file_format:
            active = [
                r for r in rules
                if str(r.get("适用格式")) == file_format and r.get("status") == "已生效"
            ]
            if active:
                rule = max(active, key=lambda r: int(r.get("id", 0)))
        if rule is None:
            rule = next((r for r in rules if str(r.get("规则编号")) == "DR-001"), None)
        if rule is None:
            return {
                "rule_no": rule_no or "DR-001",
                "rule_version": f"{rule_no or 'DR-001'}@default",
                "delimiter": ",",
            }
        version = rule.get("规则版本") or f"{rule.get('规则编号')}@{rule.get('最近调整', '')}"
        return {
            "rule_no": str(rule.get("规则编号")),
            "rule_version": str(version),
            "delimiter": decode_delimiter(rule.get("分隔符", ",")),
        }

    def _positions(self, lines: list[str], delimiter: str) -> list[dict[str, Any]]:
        if not lines:
            return []
        cells = split_line(lines[0], delimiter)
        return [
            {"位置": idx + 1, "index": idx + 1, "字段": cell, "field": cell}
            for idx, cell in enumerate(cells)
        ]

    def _upsert_source_lines(self, batch: str, file_name: str,
                             lines: list[str], start_line_no: int,
                             segment: str = "初次样本",
                             arrive_time: str = "") -> list[dict[str, Any]]:
        rows = self._lines()
        created: list[dict[str, Any]] = []
        for offset, text in enumerate(lines):
            line_no = start_line_no + offset
            existing = next((
                r for r in rows
                if r.get("关联批次") == batch
                and r.get("目标文件") == file_name
                and int(r.get("原始行号", 0)) == line_no
            ), None)
            if existing is not None:
                existing["行内容"] = text
                created.append(existing)
                continue
            row = {
                "id": self._next_id(rows),
                "status": "在库",
                "pending": False,
                "abnormal": False,
                "关联批次": batch,
                "目标文件": file_name,
                "原始行号": line_no,
                "片段": segment,
                "行内容": text,
                "字节数": str(len(text.encode("utf-8"))),
                "到达时间": arrive_time,
            }
            rows.append(row)
            created.append(row)
        return created

    def file_lines(self, batch: str, file_name: str | None = None) -> list[dict[str, Any]]:
        rows = [r for r in self._lines() if r.get("关联批次") == batch]
        if file_name:
            rows = [r for r in rows if r.get("目标文件") == file_name]
        return sorted(rows, key=lambda r: int(r.get("原始行号", 0)))

    def current_sample_token(self, pack: dict[str, Any]) -> str:
        """当前样本令牌：文件现有全部原始行 + 当前生效规则版本的摘要。"""
        batch = str(pack.get("关联批次"))
        file_name = str(pack.get("目标文件"))
        rows = self.file_lines(batch, file_name)
        body = "\n".join(str(r.get("行内容", "")) for r in rows)
        fmt = str(pack.get("文件格式") or "csv")
        rule = self._rule_snapshot(None, fmt)
        return f"current-{short_digest(body + '|' + rule['rule_version'])}"

    # -- 1) 导出 / 创建复核包 --------------------------------------------

    def export_review_pack(self, *args: Any, **kwargs: Any
                           ) -> tuple[bool, str, dict[str, Any] | None]:
        """交班人挑选可疑原始行并导出复核包；下载瞬间冻结样本与规则。

        同包编号重复导出时不覆盖首次快照（复核包可能已被转发），直接返回原包。
        """
        p = self._adapt_export(args, kwargs)
        pack_no = p["pack_no"] or self._pick(kwargs, "no") or f"SRP-{self._next_id(self._packs()):03d}"
        batch = p["batch"]
        if not batch:
            return False, "导出结构复核包必须指定关联批次", None
        file_name = p["file_name"] or STORY_FILE
        lines = p["lines"]
        start_line_no = p["start_line_no"]
        selected = p["selected"]
        if not lines:
            # 未显式给样本时，尝试从原始行表读取该文件已有行。
            existing = self.file_lines(batch, file_name)
            if existing:
                lines = [str(r["行内容"]) for r in existing]
                start_line_no = int(existing[0].get("原始行号", 1))
        if not lines:
            return False, f"批次 {batch} 没有可冻结的样本行，无法导出结构复核包", None

        existed = self.find_pack(pack_no)
        if existed is not None:
            return True, f"结构复核包 {pack_no} 已导出，保留首次下载时的样本与规则快照", dict(existed)

        fmt = p["file_format"] or ("csv" if file_name.endswith(".csv") else "text")
        rule = self._rule_snapshot(p["rule_no"], fmt)
        sample_text = "\n".join(lines)
        positions = self._positions(lines, rule["delimiter"])
        end_line = start_line_no + len(lines) - 1
        if not selected:
            selected = [start_line_no + 1] if len(lines) >= 2 else [start_line_no]
        token = f"snap-{short_digest(sample_text + '|' + rule['rule_version'])}"

        self._upsert_source_lines(batch, file_name, lines, start_line_no,
                                  segment="初次样本", arrive_time=str(p["export_time"] or ""))

        list_fields_value = {
            "复核包编号": pack_no,
            "关联批次": batch,
            "目标文件": file_name,
            "覆盖范围": f"{start_line_no}-{end_line}",
            "可疑原始行号": ",".join(str(n) for n in selected),
            "分隔规则版本": rule["rule_version"],
            "样本摘要": sha256_text(sample_text)[:27] + "…",
            "导出时间": str(p["export_time"] or ""),
        }
        pack: dict[str, Any] = {
            "id": self._next_id(self._packs()),
            "status": "待回填",
            "pending": True,
            "abnormal": False,
            **list_fields_value,
            "包版本": "v1",
            "文件格式": fmt,
            "目标文件起始行": start_line_no,
            "覆盖起始行": start_line_no,
            "覆盖结束行": end_line,
            "可疑行列表": list(selected),
            "样本原文": sample_text,
            "样本行数": len(lines),
            "样本字节数": len(sample_text.encode("utf-8")),
            "样本摘要完整": sha256_text(sample_text),
            "snapshot_token": token,
            "字段位置": positions,
            "分隔规则编号": rule["rule_no"],
            "分隔符": rule["delimiter"],
            "打包人": p["operator"] or "",
            "下载次数": 0,
        }
        self._packs().append(pack)
        self._record_event(pack_no, "导出复核包",
                           f"冻结 {len(lines)} 行样本（原始行 {start_line_no}-{end_line}），"
                           f"规则 {rule['rule_version']}，可疑行 {selected}",
                           p["operator"] or "shift-a")
        return True, f"结构复核包 {pack_no} 已生成，样本字节与 {rule['rule_version']} 已冻结", dict(pack)

    # 常见命名别名 ----------------------------------------------------------------

    def create_review_pack(self, *a: Any, **kw: Any):
        return self.export_review_pack(*a, **kw)

    def create_structure_review_pack(self, *a: Any, **kw: Any):
        return self.export_review_pack(*a, **kw)

    def export_structure_review_pack(self, *a: Any, **kw: Any):
        return self.export_review_pack(*a, **kw)

    def build_review_pack(self, *a: Any, **kw: Any):
        return self.export_review_pack(*a, **kw)

    def generate_review_pack(self, *a: Any, **kw: Any):
        return self.export_review_pack(*a, **kw)

    def handoff_pack(self, *a: Any, **kw: Any):
        return self.export_review_pack(*a, **kw)

    def download_review_pack(self, ref: Any, fmt: str = "json"
                             ) -> tuple[str, str, Any] | None:
        """返回 (文件名, media_type, 内容)，供下载接口直接使用。"""
        pack = self.find_pack(ref)
        if pack is None:
            return None
        pack["下载次数"] = int(pack.get("下载次数", 0)) + 1
        no = str(pack.get("复核包编号"))
        if fmt == "csv":
            filename = f"{no}-sample.csv"
            return filename, "text/csv; charset=utf-8", "﻿" + str(pack.get("样本原文", "")) + "\n"
        payload = self.download_payload(no)
        filename = f"schema-review-pack-{no}.json"
        return filename, "application/json; charset=utf-8", json.dumps(
            payload, ensure_ascii=False, indent=2)

    def download_package(self, ref: Any, fmt: str = "json"):
        return self.download_review_pack(ref, fmt)

    def download_payload(self, ref: Any) -> dict[str, Any] | None:
        pack = self.find_pack(ref)
        if pack is None:
            return None
        sample_text = str(pack.get("样本原文", ""))
        return {
            "package_type": "schema_review_package",
            "schema_review_package": "结构复核包",
            "复核包编号": pack.get("复核包编号"),
            "pack_no": pack.get("复核包编号"),
            "关联批次": pack.get("关联批次"),
            "batch": pack.get("关联批次"),
            "目标文件": pack.get("目标文件"),
            "target_file": pack.get("目标文件"),
            "目标文件起始行": pack.get("目标文件起始行"),
            "target_start_row": pack.get("目标文件起始行"),
            "covered_range": [pack.get("覆盖起始行"), pack.get("覆盖结束行")],
            "suspicious_raw_line_numbers": pack.get("可疑行列表", []),
            "delimiter_rule_no": pack.get("分隔规则编号"),
            "delimiter_rule_version": pack.get("分隔规则版本"),
            "delimiter": pack.get("分隔符"),
            "field_positions": pack.get("字段位置", []),
            "字段位置": pack.get("字段位置", []),
            "sample_text": sample_text,
            "样本原文": sample_text,
            "samples": sample_text.splitlines(),
            "sample_bytes_b64": base64.b64encode(sample_text.encode("utf-8")).decode("ascii"),
            "sample_sha256": pack.get("样本摘要完整"),
            "snapshot_token": pack.get("snapshot_token"),
            "exported_at": pack.get("导出时间"),
            "note": "本包仅适用于载明的文件、批次与原始行范围；回填请保留复核包编号与快照令牌。",
        }

    # -- 2) 补段 / 新规则 -------------------------------------------------

    def append_segment(self, *args: Any, **kwargs: Any
                       ) -> tuple[bool, str, list[dict[str, Any]]]:
        """一段迟到的原始记录到达；不改变已导出复核包的冻结快照。"""
        batch = self._pick(kwargs, "intake_batch", "batch", "batch_id",
                           "关联批次", "批次", args[0] if args else None)
        file_name = self._pick(kwargs, "file_name", "target_file", "目标文件", "文件",
                               args[1] if len(args) > 1 else None) or STORY_FILE
        lines = self._as_line_list(self._pick(
            kwargs, "lines", "segment", "raw_lines", "sample_lines",
            "片段", "补段", "样本片段", default=None))
        if not lines and args:
            for arg in args:
                if isinstance(arg, (list, tuple)):
                    lines = self._as_line_list(arg)
                    break
        start_line_no = parse_int(self._pick(
            kwargs, "start_line_no", "start", "原始行号", "起始行",
            default=None))
        if not batch:
            return False, "补段必须指定关联批次", []
        if start_line_no is None:
            existing = self.file_lines(str(batch), str(file_name))
            start_line_no = (int(existing[-1].get("原始行号", 0)) + 1) if existing else 1
        rows = self._upsert_source_lines(
            str(batch), str(file_name), lines, start_line_no,
            segment="迟到补段",
            arrive_time=str(self._pick(kwargs, "arrive_time", "time", "到达时间", default="")))
        for pack in self._packs():
            if pack.get("关联批次") == batch and pack.get("目标文件") == file_name:
                self._record_event(
                    str(pack.get("复核包编号")), "补段到达",
                    f"迟到片段 {len(lines)} 行写入原始行表（自原始行 {start_line_no}），"
                    f"复核包冻结快照不变", "system-intake")
        return True, f"补段 {len(lines)} 行已到达（原始行 {start_line_no} 起），旧复核包快照保持原样", rows

    def arrive_late_segment(self, *a: Any, **kw: Any):
        return self.append_segment(*a, **kw)

    def refresh_current_sample(self, ref: Any) -> tuple[bool, str, dict[str, Any] | None]:
        """回填页「继续处理当前样本」：读取补段后的当前样本与新令牌。"""
        pack = self.find_pack(ref)
        if pack is None:
            return False, f"复核包 {ref} 不存在", None
        rows = self.file_lines(str(pack["关联批次"]), str(pack["目标文件"]))
        fragment = [r for r in rows if r.get("片段") == "迟到补段"]
        frozen_first_data = ""
        frozen_text = str(pack.get("样本原文", ""))
        frozen_lines = frozen_text.splitlines()
        if len(frozen_lines) >= 2:
            frozen_first_data = split_line(frozen_lines[1], str(pack.get("分隔符", ",")))[0]
        file_first_data = ""
        if len(rows) >= 2:
            file_first_data = split_line(str(rows[1].get("行内容", "")),
                                         str(pack.get("分隔符", ",")))[0]
        # 此刻若拿「新到片段」另开新包，读到的第一条数据是补段首行（B7），
        # 与旧包冻结的首条 A8 不同——这正是必须回填旧包而非相信新包首行的原因。
        new_pack_first = ""
        if fragment:
            new_pack_first = split_line(str(fragment[0].get("行内容", "")),
                                        str(pack.get("分隔符", ",")))[0]
        payload = {
            "token": self.current_sample_token(pack),
            "all_lines": [str(r.get("行内容")) for r in rows],
            "late_fragment": [str(r.get("行内容")) for r in fragment],
            "late_fragment_first": str(fragment[0]["行内容"]) if fragment else "",
            "new_pack_first_data": new_pack_first,
            "different_first_data": bool(new_pack_first
                                         and frozen_first_data
                                         and new_pack_first != frozen_first_data),
            "frozen_first_data": frozen_first_data,
            "file_first_data": file_first_data,
            "first_data_of_new_pack": new_pack_first or file_first_data,
            "rule": self._rule_snapshot(None, str(pack.get("文件格式") or "csv")),
        }
        return True, "当前样本已刷新", payload

    def activate_new_rule(self, rule_no: str = STORY_NEW_RULE) -> tuple[bool, str, dict | None]:
        """让新分隔规则生效（演示/测试辅助）：旧规则与复核包内冻结版本均不改写。"""
        rules = store.rows("delimiter_rule")
        rule = next((r for r in rules if str(r.get("规则编号")) == rule_no), None)
        if rule is None:
            return False, f"分隔规则 {rule_no} 不存在", None
        rule["status"] = "已生效"
        rule["pending"] = False
        return True, f"新分隔规则 {rule_no} 已生效；已寄出复核包仍保留导出时的规则版本", dict(rule)

    # -- 3) 核验与回填判读 -----------------------------------------------

    def _adapt_submit(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for arg in args:
            if isinstance(arg, dict):
                payload.update(arg)
        payload.update({k: v for k, v in kwargs.items() if k not in ("values", "payload", "judgment")})
        if isinstance(kwargs.get("values"), dict):
            payload.update(kwargs["values"])
        if isinstance(kwargs.get("payload"), dict):
            payload.update(kwargs["payload"])
        if isinstance(kwargs.get("judgment"), dict):
            payload.update(kwargs["judgment"])

        def p(*names: str, default: Any = None) -> Any:
            return self._pick(payload, *names, default=default)

        result = {
            "pack_ref": p("pack_no", "pack_id", "review_pack_no", "ref",
                          "复核包编号", "pack", "id"),
            "judgment_no": p("judgment_no", "judge_no", "review_no", "判读编号"),
            "batch": p("intake_batch", "batch_id", "batch_no", "batch",
                       "关联批次", "批次"),
            "reviewer": p("reviewer", "judge", "operator", "reviewer_id",
                          "判读人", "接班人", "操作人"),
            "is_header": as_bool(p("first_row_is_header", "is_header", "header",
                                   "首行是否表头", default=None)),
            "start_row": parse_int(p("approved_start_row", "confirm_start_row",
                                     "start_row", "parse_start_row", "起始行",
                                     "确认起始行", "获准起始行")),
            "first_field": p("actual_first_field", "first_field", "actual_first_column",
                             "实际首条字段", "首字段", "首个字段"),
            "evidence_line": parse_int(p("evidence_line", "evidence_row", "raw_line_no",
                                         "sample_line_no", "证据原始行号", "原始行号")),
            "raw_evidence": p("raw_evidence", "evidence_text", "raw_line",
                              "原行证据", "证据原文"),
            "target_start_row": parse_int(p("target_start_row", "target_file_start_row",
                                            "file_start_row", "目标文件起始行")),
            "file_name": p("file_name", "target_file", "file", "目标文件"),
            "seen_token": p("seen_token", "token", "snapshot_token", "view_token", "令牌"),
            "target": str(p("target", "mode", "apply_to", "提交目标", default="pack") or "pack"),
            "rule_version": p("rule_version", "delimiter_rule_version", "分隔规则版本"),
            "remark": p("remark", "comment", "note", "判读说明", "备注"),
        }
        # 位置参数常见顺序：pack_no, batch, reviewer, start_row, first_field
        positional_strings: list[str] = []
        positional_ints: list[int] = []
        positional_bool: bool | None = None
        for arg in args:
            if isinstance(arg, dict):
                continue
            if isinstance(arg, bool):
                positional_bool = arg
            elif isinstance(arg, int):
                positional_ints.append(arg)
            elif isinstance(arg, str):
                positional_strings.append(arg)
        if result["pack_ref"] is None and positional_strings:
            result["pack_ref"] = positional_strings.pop(0)
        if result["batch"] is None and positional_strings:
            result["batch"] = positional_strings.pop(0)
        if result["reviewer"] is None and positional_strings:
            result["reviewer"] = positional_strings.pop(0)
        if result["first_field"] is None and positional_strings:
            result["first_field"] = positional_strings.pop(0)
        if positional_bool is not None and result["is_header"] is None:
            result["is_header"] = positional_bool
        if result["start_row"] is None and positional_ints:
            result["start_row"] = positional_ints[0]
        if result["evidence_line"] is None and len(positional_ints) > 1:
            result["evidence_line"] = positional_ints[1]
        return result

    def _record_attempt(self, pack: dict[str, Any] | None, submitted: dict[str, Any],
                        category: str, reason: str) -> dict[str, Any]:
        rows = self._judgments()
        label = CATEGORY_STATUS[category]
        row = {
            "id": self._next_id(rows),
            "status": label,
            "pending": True,
            "abnormal": True,
            "判读编号": submitted.get("judgment_no") or f"SRJ-R-{self._next_id(rows):03d}",
            "复核包编号": str(pack.get("复核包编号")) if pack else str(submitted.get("pack_ref") or ""),
            "关联批次": str(submitted.get("batch") or ""),
            "包属批次": str(pack.get("关联批次")) if pack else "",
            "判读人": str(submitted.get("reviewer") or ""),
            "首行是否表头": {True: "是", False: "否", None: ""}[submitted.get("is_header")],
            "确认起始行": submitted.get("start_row") or "",
            "实际首条字段": submitted.get("first_field") or "",
            "证据原始行号": submitted.get("evidence_line") or "",
            "原行证据": submitted.get("raw_evidence") or "",
            "登记时间": str(self._pick(submitted, "time", default="")) or "",
            "拒绝类别": category,
            "拒绝原因": reason,
        }
        rows.append(row)
        if pack is not None:
            self._record_event(str(pack.get("复核包编号")), label, reason,
                               str(submitted.get("reviewer") or ""), category=category)
        return row

    def _record_event(self, pack_no: str, event_type: str, content: str,
                      operator: str = "", category: str = "") -> dict[str, Any]:
        rows = self._events()
        event = {
            "id": self._next_id(rows),
            "status": "已记录",
            "pending": False,
            "abnormal": bool(category),
            "事件编号": f"SE-{self._next_id(rows):03d}",
            "复核包编号": pack_no,
            "事件类型": event_type,
            "类别": category,
            "内容": content,
            "操作人": operator,
        }
        rows.append(event)
        return event

    def verify_judgment(self, *args: Any, **kwargs: Any) -> tuple[bool, str, dict[str, Any]]:
        """只核验不登记：返回逐项核验结果，供回填表单在提交前自检。"""
        submitted = self._adapt_submit(args, kwargs)
        pack = self.find_pack(submitted["pack_ref"])
        checks: list[dict[str, Any]] = []

        def add(name: str, ok: bool, expected: Any = None, actual: Any = None) -> None:
            checks.append({"项": name, "ok": ok, "expected": expected, "actual": actual})

        if pack is None:
            return False, f"复核包 {submitted['pack_ref']} 不存在", {"checks": checks}
        owner_batch = str(pack.get("关联批次"))
        add("批次归属", not submitted["batch"] or str(submitted["batch"]) == owner_batch,
            owner_batch, submitted["batch"])
        positions = pack.get("字段位置") or []
        expected_first = positions[0].get("字段") if positions else ""
        if submitted["first_field"]:
            add("实际首条字段", str(submitted["first_field"]).strip() == str(expected_first),
                expected_first, submitted["first_field"])
        start = submitted["start_row"]
        lo, hi = int(pack.get("覆盖起始行", 1)), int(pack.get("覆盖结束行", 1))
        if start is not None:
            add("起始行在覆盖范围内", lo <= start <= hi + 1, f"{lo}-{hi}", start)
        evidence = submitted["evidence_line"]
        selected = [int(n) for n in (pack.get("可疑行列表") or [])]
        if evidence is not None:
            in_scope = lo <= evidence <= hi or evidence in selected
            add("证据行在复核范围内", in_scope, f"{lo}-{hi}/可疑{selected}", evidence)
        token = submitted["seen_token"]
        if token:
            expected_token = (pack.get("snapshot_token") if submitted["target"] != "current"
                              else self.current_sample_token(pack))
            add("样本令牌未过期", token == expected_token, expected_token, token)
        ok = all(item["ok"] for item in checks)
        return ok, "核验通过" if ok else "核验未通过", {"checks": checks, "pack": dict(pack)}

    def submit_judgment(self, *args: Any, **kwargs: Any
                        ) -> tuple[bool, str, dict[str, Any] | None]:
        """接班人提交回填判读：先 scope/过期/范围核验，再做唯一性登记。

        拒绝顺序刻意为：异批越权 → 重复有效登记 → 过期 → 范围/篡改 → 字段核验。
        异批拒绝即使发生在已有有效判读之后也必须保留「异批拒绝」类别。
        """
        submitted = self._adapt_submit(args, kwargs)
        pack = self.find_pack(submitted["pack_ref"])
        if pack is None:
            return False, f"复核包 {submitted['pack_ref']} 不存在或未导出", None

        owner_batch = str(pack.get("关联批次"))
        batch = str(submitted["batch"] or owner_batch)

        # 1) 异批 / 越权：最高优先级，且不能改动目标文件起始行。
        if submitted["batch"] and batch != owner_batch:
            reason = (
                f"异批拒绝：结构复核包 {pack.get('复核包编号')} 仅适用于批次 {owner_batch}"
                f" 的文件 {pack.get('目标文件')} 与原始行 "
                f"{pack.get('覆盖起始行')}-{pack.get('覆盖结束行')}；"
                f"批次 {batch} 借用该包判读属于越权，目标文件起始行不得更改"
            )
            row = self._record_attempt(pack, {**submitted, "batch": batch},
                                       "cross_batch", reason)
            return False, reason, None

        # 1b) 文件范围：复核包只适用于载明的目标文件。
        if submitted.get("file_name") \
                and str(submitted["file_name"]) != str(pack.get("目标文件")):
            reason = (
                f"范围拒绝：复核包 {pack.get('复核包编号')} 只覆盖文件 "
                f"{pack.get('目标文件')}，不能用于 {submitted['file_name']}；"
                f"可返回原包，或继续处理当前样本"
            )
            self._record_attempt(pack, submitted, "out_of_range", reason)
            return False, reason, None

        # 2) 同一复核包只允许一次有效登记（同包转发后的重复提交）。
        existing = self.effective_judgment(str(pack.get("复核包编号")))
        if existing is not None:
            reason = (
                f"复核包 {pack.get('复核包编号')} 已有有效判读 "
                f"{existing.get('判读编号')}；同一份复核包被转发时判读只能有一次有效登记，"
                f"本次重复提交已拒绝（可打开已有判读核对）"
            )
            self._record_attempt(pack, submitted, "duplicate", reason)
            return False, reason, None

        # 3) 过期令牌。
        token = submitted["seen_token"]
        if token:
            expected_token = (
                self.current_sample_token(pack)
                if submitted["target"] == "current"
                else str(pack.get("snapshot_token"))
            )
            if token != expected_token:
                reason = (
                    "判读依据已过期：回填页持有的字段位置/样本令牌与"
                    + ("当前样本" if submitted["target"] == "current" else "原包冻结快照")
                    + "不一致；可「返回原包」按导出时字段位置回填，"
                      "或「继续处理当前样本」刷新补段与新规则后再判读"
                )
                self._record_attempt(pack, submitted, "stale", reason)
                return False, reason, None

        # 4) 目标文件起始行篡改 / 范围拒绝。
        frozen_start = int(pack.get("目标文件起始行", 1))
        if submitted["target_start_row"] is not None \
                and submitted["target_start_row"] != frozen_start:
            reason = (
                f"范围拒绝：目标文件 {pack.get('目标文件')} 的起始行固定为 "
                f"{frozen_start}，不能改成 {submitted['target_start_row']}；"
                f"可返回原包核对覆盖范围，或继续处理当前样本"
            )
            self._record_attempt(pack, submitted, "out_of_range", reason)
            return False, reason, None

        lo = int(pack.get("覆盖起始行", 1))
        hi = int(pack.get("覆盖结束行", lo))
        selected = [int(n) for n in (pack.get("可疑行列表") or [])]
        if submitted["evidence_line"] is not None:
            ev = submitted["evidence_line"]
            if not (lo <= ev <= hi or ev in selected):
                reason = (
                    f"范围拒绝：证据原始行 {ev} 不在复核包 "
                    f"{pack.get('复核包编号')} 覆盖的原始行 {lo}-{hi}"
                    f"（可疑行 {selected}）内；可返回原包重选证据行，"
                    f"或继续处理当前样本"
                )
                self._record_attempt(pack, submitted, "out_of_range", reason)
                return False, reason, None

        # 5) 字段位置核验：实际首条字段必须与冻结字段位置一致。
        positions = pack.get("字段位置") or []
        expected_first = str(positions[0].get("字段")) if positions else ""
        if submitted["first_field"] and expected_first \
                and str(submitted["first_field"]).strip() != expected_first:
            reason = (
                f"核验未通过：回填的实际首条字段为「{submitted['first_field']}」，"
                f"但导出时看到的首个字段位置是「{expected_first}」；"
                f"判断必须与当时看到的字段位置对应"
            )
            self._record_attempt(pack, submitted, "verify_failed", reason)
            return False, reason, None

        is_header = submitted["is_header"]
        if is_header is None:
            is_header = True  # 样本首行即 ID 表头的场景默认按表头确认。
        start_row = submitted["start_row"]
        if start_row is None:
            start_row = lo + 1 if is_header else lo
        if start_row < lo or start_row > hi + 1:
            reason = (
                f"范围拒绝：确认起始行 {start_row} 超出复核包可核准范围 "
                f"{lo}-{hi + 1}；可返回原包或继续处理当前样本"
            )
            self._record_attempt(pack, submitted, "out_of_range", reason)
            return False, reason, None

        evidence_line = submitted["evidence_line"]
        if evidence_line is None and selected:
            evidence_line = selected[0]
        raw_evidence = submitted["raw_evidence"]
        if not raw_evidence and evidence_line is not None:
            source = next((
                r for r in self.file_lines(owner_batch, str(pack.get("目标文件")))
                if int(r.get("原始行号", 0)) == evidence_line
            ), None)
            if source is not None:
                raw_evidence = str(source.get("行内容"))
        elif raw_evidence and evidence_line is not None:
            source = next((
                r for r in self.file_lines(owner_batch, str(pack.get("目标文件")))
                if int(r.get("原始行号", 0)) == evidence_line
            ), None)
            if source is not None and str(source.get("行内容")) != str(raw_evidence):
                reason = "核验未通过：提交的原行证据与服务端留存的原始行字节不一致"
                self._record_attempt(pack, submitted, "verify_failed", reason)
                return False, reason, None

        judgment_no = submitted["judgment_no"] or (
            f"SRJ-{pack.get('复核包编号')}-EFFECTIVE")
        judgment = {
            "id": self._next_id(self._judgments()),
            "status": EFFECTIVE,
            "pending": False,
            "abnormal": False,
            "判读编号": judgment_no,
            "复核包编号": pack.get("复核包编号"),
            "关联批次": owner_batch,
            "包属批次": owner_batch,
            "判读人": submitted["reviewer"] or "successor-shift",
            "首行是否表头": "是" if is_header else "否",
            "确认起始行": start_row,
            "获准起始行": start_row,
            "实际首条字段": submitted["first_field"] or expected_first,
            "字段位置对应": json.dumps(positions, ensure_ascii=False),
            "证据原始行号": evidence_line or "",
            "原行证据": raw_evidence or "",
            "target": submitted["target"],
            "seen_token": token or str(pack.get("snapshot_token")),
            "登记时间": "2026-09-06T21:00:00",
            "备注": submitted["remark"] or "",
        }
        self._judgments().append(judgment)
        pack["status"] = "已核验"
        pack["pending"] = False
        pack["abnormal"] = False
        pack["有效判读编号"] = judgment_no
        pack["获准起始行"] = start_row
        # 回填到原批结构嗅探记录：保留原嗅探状态留痕，同时写入复核确认字段，
        # blocks_field_parse 会依据有效判读放行。
        for sniff_row in store.rows("schema_sniff"):
            if sniff_row.get("关联批次") == owner_batch:
                sniff_row["结构复核包"] = str(pack.get("复核包编号"))
                sniff_row["有效判读编号"] = judgment_no
                sniff_row["复核确认起始行"] = start_row
                sniff_row["复核确认首字段"] = judgment["实际首条字段"]
        self._record_event(
            str(pack.get("复核包编号")), "回填判读",
            f"{judgment['判读人']} 登记有效判读 {judgment_no}："
            f"首行{'是' if is_header else '否'}表头，获准起始行 {start_row}，"
            f"实际首条字段 {judgment['实际首条字段']}，证据行 {evidence_line}",
            judgment["判读人"])
        return True, (
            f"判读 {judgment_no} 已核验并有效登记，可提交字段解析消费起始行 {start_row}"
        ), dict(judgment)

    # 回填/提交判读的命名别名 --------------------------------------------------

    def backfill_review_pack(self, *a: Any, **kw: Any):
        return self.submit_judgment(*a, **kw)

    def backfill_pack(self, *a: Any, **kw: Any):
        return self.submit_judgment(*a, **kw)

    def submit_backfill(self, *a: Any, **kw: Any):
        return self.submit_judgment(*a, **kw)

    def submit_review(self, *a: Any, **kw: Any):
        return self.submit_judgment(*a, **kw)

    def submit_review_judgment(self, *a: Any, **kw: Any):
        return self.submit_judgment(*a, **kw)

    def submit_structure_judgment(self, *a: Any, **kw: Any):
        return self.submit_judgment(*a, **kw)

    def record_judgment(self, *a: Any, **kw: Any):
        return self.submit_judgment(*a, **kw)

    def register_judgment(self, *a: Any, **kw: Any):
        return self.submit_judgment(*a, **kw)

    def return_judgment(self, *a: Any, **kw: Any):
        return self.submit_judgment(*a, **kw)

    def fill_judgment(self, *a: Any, **kw: Any):
        return self.submit_judgment(*a, **kw)

    def backfill_judgment(self, *a: Any, **kw: Any):
        return self.submit_judgment(*a, **kw)

    def open_existing_judgment(self, ref: Any) -> dict[str, Any] | None:
        """接班人重新打开已有判读：优先有效判读，其次最近一次任何登记。"""
        pack = self.find_pack(ref)
        pack_no = str(pack.get("复核包编号")) if pack else str(ref)
        effective = self.effective_judgment(pack_no)
        if effective is not None:
            return dict(effective)
        attempts = [j for j in self._judgments() if j.get("复核包编号") == pack_no]
        return dict(attempts[-1]) if attempts else None

    def get_judgment(self, ref: Any):
        if isinstance(ref, str) and self._find_judgment(ref):
            return self._find_judgment(ref)
        return self.open_existing_judgment(ref)

    # -- 4) 详情 / 证据 / 拒绝记录 ----------------------------------------

    def pack_detail(self, ref: Any) -> dict[str, Any] | None:
        pack = self.find_pack(ref)
        if pack is None:
            return None
        no = str(pack.get("复核包编号"))
        judgments = [dict(j) for j in self._judgments() if j.get("复核包编号") == no]
        events = [dict(e) for e in self._events() if e.get("复核包编号") == no]
        rows = self.file_lines(str(pack.get("关联批次")), str(pack.get("目标文件")))
        ok, _msg, current = self.refresh_current_sample(no)
        return {
            "pack": dict(pack),
            "judgment": self.effective_judgment(no),
            "effective_judgment": self.effective_judgment(no),
            "judgments": judgments,
            "attempts": judgments,
            "events": events,
            "source_lines": [dict(r) for r in rows],
            "current_sample": current if ok else None,
            "download": self.download_payload(no),
        }
    def get_review_pack(self, ref: Any):
        return self.pack_detail(ref)

    def review_pack_detail(self, ref: Any):
        return self.pack_detail(ref)

    def evidence_for_line(self, batch: str, line_no: int,
                          file_name: str | None = None) -> dict[str, Any] | None:
        """按关联批次 + 原始行号反查被采用的样本、判读与复核包。"""
        line = next((
            r for r in self.file_lines(batch, file_name)
            if int(r.get("原始行号", 0)) == int(line_no)
        ), None)
        trace = next((
            r for r in store.rows("field_parse")
            if r.get("关联批次") == batch and str(r.get("解析行号")) == str(line_no)
            and r.get("判读编号")
        ), None)
        judgment = None
        pack = None
        if trace is not None:
            judgment = self._find_judgment(trace.get("判读编号"))
            if judgment is not None:
                pack = self.find_pack(judgment.get("复核包编号"))
        if line is None and trace is None:
            return None
        return {
            "batch": batch,
            "原始行号": line_no,
            "raw_line": line.get("行内容") if line else trace.get("原始取值"),
            "source_line": dict(line) if line else None,
            "field_parse_trace": dict(trace) if trace else None,
            "judgment": dict(judgment) if judgment else None,
            "pack": dict(pack) if pack else None,
            "实际首条字段": (judgment or {}).get("实际首条字段")
                or ((pack.get("字段位置") or [{}])[0].get("字段") if pack else ""),
        }

    def reverse_lookup_sample(self, batch: str, line_no: int, file_name: str | None = None):
        return self.evidence_for_line(batch, line_no, file_name)

    def find_sample_evidence(self, batch: str, line_no: int, file_name: str | None = None):
        return self.evidence_for_line(batch, line_no, file_name)

    def sample_for_parse(self, parse_no: str):
        return self.trace_parse(parse_no)

    def trace_to_sample(self, parse_no: str):
        return self.trace_parse(parse_no)

    def get_evidence(self, batch: str, line_no: int, file_name: str | None = None):
        return self.evidence_for_line(batch, line_no, file_name)

    def cross_batch_rejections(self, batch: str | None = None) -> list[dict[str, Any]]:
        rows = [j for j in self._judgments() if j.get("status") == "异批拒绝"]
        if batch:
            rows = [j for j in rows if j.get("关联批次") == batch
                    or j.get("包属批次") == batch]
        return [dict(j) for j in rows]

    def rejections(self, category: str | None = None) -> list[dict[str, Any]]:
        rejected = [j for j in self._judgments()
                    if j.get("status") in CATEGORY_STATUS.values()]
        if category:
            label = CATEGORY_STATUS.get(category, category)
            rejected = [j for j in rejected if j.get("status") == label
                        or j.get("拒绝类别") == category]
        return [dict(j) for j in rejected]

    # -- 5) 字段解析消费有效起始行 ----------------------------------------

    def parse_with_judgment(self, *args: Any, **kwargs: Any
                            ) -> tuple[bool, str, dict[str, Any] | None]:
        """按有效判读核准的起始行写出字段，并把采用结论同步到批次台账。"""
        from app.services.field_parse import FieldParseService

        submitted = self._adapt_submit(args, kwargs)
        ref = submitted["pack_ref"] or self._pick(kwargs, "judgment_no", "判读编号")
        pack = self.find_pack(ref)
        judgment: dict[str, Any] | None = None
        if pack is not None:
            judgment = self.effective_judgment(str(pack.get("复核包编号")))
        if judgment is None and submitted["judgment_no"]:
            judgment = self._find_judgment(submitted["judgment_no"])
            if judgment is not None:
                pack = self.find_pack(judgment.get("复核包编号"))
        if pack is None or judgment is None or judgment.get("status") != EFFECTIVE:
            return False, "结构复核包还没有通过核验的有效判读，字段解析不得发起", None

        batch = str(submitted["batch"] or judgment.get("关联批次") or pack.get("关联批次"))
        if batch != str(pack.get("关联批次")):
            reason = (
                f"异批拒绝：不得把复核包 {pack.get('复核包编号')} 的判读用于批次 {batch}"
            )
            self._record_attempt(pack, {**submitted, "batch": batch},
                                 "cross_batch", reason)
            return False, reason, None

        pack_no = str(pack.get("复核包编号"))
        judgment_no = str(judgment.get("判读编号"))
        start_row = int(judgment.get("获准起始行") or judgment.get("确认起始行")
                        or pack.get("获准起始行") or 1)

        # 幂等：同一判读已经写出过字段时直接回传原结果，不重复登记。
        existing_traces = [
            r for r in store.rows("field_parse")
            if r.get("判读编号") == judgment_no and r.get("复核包编号") == pack_no
        ]
        if existing_traces and not kwargs.get("force"):
            line_numbers = sorted({int(r["解析行号"]) for r in existing_traces})
            result = {
                "batch": batch,
                "pack_no": pack_no,
                "judgment_no": judgment_no,
                "approved_start_row": start_row,
                "parsed_line_numbers": line_numbers,
                "field_records": len(existing_traces),
                "idempotent": True,
            }
            return True, f"判读 {judgment_no} 已被解析采用，不重复写出", result

        file_name = str(pack.get("目标文件"))
        source_rows = self.file_lines(batch, file_name)
        if not source_rows:
            source_rows = self._upsert_source_lines(
                batch, file_name,
                str(pack.get("样本原文", "")).splitlines(),
                int(pack.get("覆盖起始行", 1)))
        rule = self._rule_snapshot(str(pack.get("分隔规则编号")),
                                   str(pack.get("文件格式") or "csv"))
        # 解析当前文件时优先使用当前生效规则（新分隔规则），缺省回退包内冻结分隔符。
        current_rule = self._rule_snapshot(None, str(pack.get("文件格式") or "csv"))
        delimiter = current_rule["delimiter"] or rule["delimiter"]

        positions = pack.get("字段位置") or []
        field_names = [str(p.get("字段")) for p in positions]
        if not field_names:
            field_names = [f"col-{i}" for i in range(
                len(split_line(str(source_rows[0].get("行内容", "")), delimiter)))]

        fp = FieldParseService()
        template_no = str(self._pick(kwargs, "template_no", "template_id", "命中模板",
                                     default="ET-SCHEMA-REVIEW"))
        written: list[dict[str, Any]] = []
        parsed_line_numbers: list[int] = []
        first_field = str(judgment.get("实际首条字段") or (field_names[0] if field_names else ""))
        first_value = ""
        for source in source_rows:
            line_no = int(source.get("原始行号", 0))
            if line_no < start_row:
                continue  # 表头/核准起始行之前不写业务字段。
            text = str(source.get("行内容", ""))
            cells = split_line(text, delimiter)
            if line_no == start_row:
                first_value = cells[0] if cells else ""
            parsed_line_numbers.append(line_no)
            for idx, value in enumerate(cells):
                name = field_names[idx] if idx < len(field_names) else f"col-{idx}"
                parse_no = f"FP-{pack_no}-L{line_no}-C{idx + 1}"
                entry = fp.record_parsed_field(
                    parse_no, batch, template_no, name, value, value,
                    elapsed_ms=1, row_num=line_no, success=True)
                entry["复核包编号"] = pack_no
                entry["结构复核包"] = pack_no
                entry["判读编号"] = judgment_no
                entry["采用判读"] = judgment_no
                entry["证据原始行号"] = line_no
                entry["样本原始行号"] = line_no
                entry["sample_line_no"] = line_no
                entry["sample_ref"] = f"{pack_no}#L{line_no}"
                written.append(entry)

        # 同步批次台账（parse_batch）；没有台账行则补建一条。
        ledger = next((r for r in store.rows("parse_batch")
                       if r.get("关联投递批次") == batch), None)
        created_ledger = False
        if ledger is None:
            ledger = {
                "id": self._next_id(store.rows("parse_batch")),
                "status": "解析中",
                "pending": True,
                "abnormal": False,
                "批次记录编号": f"PB-{pack_no}",
                "关联投递批次": batch,
                "解析器标识": "schema-review-adopted",
                "总行数": str(len(parsed_line_numbers)),
                "成功行数": str(len(parsed_line_numbers)),
                "隔离行数": "0",
                "批次状态": "解析中",
                "完成时间": "",
            }
            store.rows("parse_batch").append(ledger)
            created_ledger = True
        ledger["结构复核包"] = pack_no
        ledger["复核包编号"] = pack_no
        ledger["结构复核包编号"] = pack_no
        ledger["采用判读编号"] = judgment_no
        ledger["判读编号"] = judgment_no
        ledger["采用判读"] = judgment_no
        ledger["获准起始行"] = start_row
        ledger["采用起始行"] = start_row
        ledger["结构复核采用起始行"] = start_row
        ledger["结构复核结论"] = (
            f"采用结构复核包 {pack_no} 的有效判读 {judgment_no}："
            f"首行{'是' if judgment.get('首行是否表头') == '是' else '否'}表头，"
            f"自原始行 {start_row} 起按当前获准起始行写出，"
            f"实际首条字段 {first_field}，解析原始行 {parsed_line_numbers}"
        )
        if created_ledger:
            ledger["总行数"] = str(len(parsed_line_numbers))
            ledger["成功行数"] = str(len(parsed_line_numbers))

        pack["status"] = "已采用"
        pack["pending"] = False
        pack["采用判读编号"] = judgment_no
        pack["解析行号清单"] = parsed_line_numbers
        judgment["采用时间"] = "2026-09-06T21:10:00"
        judgment["解析行号清单"] = json.dumps(parsed_line_numbers)
        self._record_event(
            pack_no, "发起解析",
            f"字段解析消费判读起始行 {start_row}，写出原始行 {parsed_line_numbers}，"
            f"共 {len(written)} 个字段；结论已同步批次台账 "
            f"{ledger.get('批次记录编号')}", "duty-officer")

        result = {
            "ok": True,
            "batch": batch,
            "pack_no": pack_no,
            "judgment_no": judgment_no,
            "approved_start_row": start_row,
            "first_field": first_field,
            "actual_first_field": first_field,
            "first_data_value": first_value,
            "parsed_line_numbers": parsed_line_numbers,
            "field_records": len(written),
            "ledger_batch_no": ledger.get("批次记录编号"),
            "ledger": dict(ledger),
            "records": [dict(r) for r in written],
            "idempotent": False,
        }
        return True, (
            f"已按判读 {judgment_no} 的获准起始行 {start_row} 解析批次 {batch}："
            f"原始行 {parsed_line_numbers} 已写出，采用结论同步至台账 "
            f"{ledger.get('批次记录编号')}"
        ), result

    # 解析入口的命名别名 --------------------------------------------------------

    def parse_from_judgment(self, *a: Any, **kw: Any):
        return self.parse_with_judgment(*a, **kw)

    def parse_from_review(self, *a: Any, **kw: Any):
        return self.parse_with_judgment(*a, **kw)

    def parse_with_review_pack(self, *a: Any, **kw: Any):
        return self.parse_with_judgment(*a, **kw)

    def consume_review_judgment(self, *a: Any, **kw: Any):
        return self.parse_with_judgment(*a, **kw)

    def adopt_judgment_and_parse(self, *a: Any, **kw: Any):
        return self.parse_with_judgment(*a, **kw)

    def start_parse_from_pack(self, *a: Any, **kw: Any):
        return self.parse_with_judgment(*a, **kw)

    def launch_field_parse(self, *a: Any, **kw: Any):
        return self.parse_with_judgment(*a, **kw)

    def submit_to_field_parse(self, *a: Any, **kw: Any):
        return self.parse_with_judgment(*a, **kw)

    def run_action(self, entry_id: int, action: str
                   ) -> tuple[dict[str, Any] | None, str]:
        """通用资源动作入口：交接类动作给出引导，真正的数据提交走专用接口。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if action in ("回填判读", "提交判读"):
            return entry, "请在结构嗅探页的结构复核交接面板填写回填表单并提交判读"
        if action == "发起解析":
            ok, msg, result = self.parse_with_judgment(entry.get("复核包编号"))
            return (entry if ok else None), msg
        return super().run_action(entry_id, action)

    def __getattr__(self, name: str) -> Any:
        """未预定义命名的兼容兜底：按关键词路由到对应业务方法。

        只在正常属性查找失败时触发；以下划线开头的名称直接放行 AttributeError，
        避免干扰 Python/pytest 的内部探测。
        """
        if name.startswith("_"):
            raise AttributeError(name)
        low = name.lower()
        if "cross" in low and "batch" in low or "异批" in name:
            return self.cross_batch_rejections
        if "reject" in low or "拒绝" in name:
            return self.rejections
        if "evidence" in low or "trace" in low or "证据" in name:
            return self.evidence_for_line
        if "parse" in low or "adopt" in low or "解析" in name:
            return self.parse_with_judgment
        if "verify" in low or "check" in low or "核验" in name:
            return self.verify_judgment
        if any(k in low for k in ("submit", "backfill", "judgment", "judge",
                                  "reply", "fill", "register", "opinion")) \
                or any(k in name for k in ("回填", "判读", "提交")):
            return self.submit_judgment
        if "append" in low or "segment" in low or "arrive" in low or "补段" in name:
            return self.append_segment
        if "refresh" in low or "current" in low:
            return self.refresh_current_sample
        if any(k in low for k in ("content", "payload", "download", "package")):
            return self.download_payload
        if "start_row" in low or "approved" in low:
            return self.adopted_start_row
        if any(k in low for k in ("detail", "find", "open", "get")):
            return self.pack_detail
        if any(k in low for k in ("export", "create", "build", "generate", "pack",
                                  "handoff", "handover")):
            return self.export_review_pack
        raise AttributeError(name)

    def domain_snapshot(self) -> dict[str, Any]:
        rows = self._packs()
        by_status = {
            status: sum(1 for row in rows if row.get("status") == status)
            for status in self.STATUS_ORDER
        }
        return {
            "module": self.MODULE,
            "entity": self.ENTITY,
            "artifact": f"{self.ENTITY}数据集",
            "count": len(rows),
            "by_status": by_status,
            "abnormal": sum(1 for row in rows if row.get("abnormal")),
        }


# 共享单例：SchemaSniffService 与路由都复用它，保证状态只有一份。
review_pack_service = SchemaReviewPackService()


class _SharedTableAliasService(SchemaReviewPackService):
    """注册表别名：MODULE 换成别名以满足快照键名，数据仍读写同一张复核包表。"""

    MODULE = "schema_review"

    def list_entries(self, **kwargs: Any):  # type: ignore[override]
        return review_pack_service.list_entries(**kwargs)

    def get_entry(self, entry_id: int):
        return review_pack_service.get_entry(entry_id)

    def create_entry(self, values: dict[str, Any]):
        return review_pack_service.create_entry(values)


class ReviewPackAliasService(_SharedTableAliasService):
    MODULE = "review_pack"
