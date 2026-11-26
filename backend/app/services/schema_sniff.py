"""结构嗅探领域服务：对无声明结构的文件抽样推断列数、列名与列类型，产出结构推断数据集。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.schema_review_pack import review_pack_service
from app.store import store


class SchemaSniffService(BaseModuleService):
    MODULE = "schema_sniff"
    ENTITY = "结构推断"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["嗅探编号", "关联批次", "样本行数", "推断列数", "列名清单", "列类型推断", "首行是否表头", "嗅探置信度"]
    REQUIRED_FIELDS = ["嗅探编号", "关联批次", "样本行数"]
    STATUS_ORDER = ["待嗅探", "已推断", "低置信", "推断冲突"]
    ACTION_RULES = {"执行嗅探": "已推断", "标记低置信": "低置信", "登记冲突": "推断冲突"}
    NEGATIVE_ACTIONS = ["登记冲突"]

    LOW_CONFIDENCE = 0.60

    @staticmethod
    def _looks_numeric(value: str) -> bool:
        text = value.strip()
        if not text:
            return False
        try:
            float(text)
            return True
        except ValueError:
            return False

    def detect_header(self, sample_rows: list[list[str]]) -> tuple[bool, float]:
        """判定首行是否表头，返回 (是否表头, 判定置信度)。

        依据：首行全为非数值文本、且后续数据行同列类型稳定时判为表头。
        """
        if len(sample_rows) < 2:
            return False, 0.30
        first = sample_rows[0]
        rest = sample_rows[1:]
        first_alpha = all(
            cell.strip() and not self._looks_numeric(cell)
            for cell in first if cell.strip()
        )
        column_count = len(first)
        stable_columns = 0
        for index in range(column_count):
            column_values = [r[index] for r in rest if index < len(r)]
            numeric = sum(1 for v in column_values if self._looks_numeric(v))
            if column_values and (numeric == len(column_values) or numeric == 0):
                stable_columns += 1
        stability = stable_columns / column_count if column_count else 0.0
        is_header = bool(first_alpha and stability >= 0.75)
        confidence = round(min(0.99, 0.5 + stability * 0.4 + (0.09 if is_header else 0.0)), 2)
        return is_header, confidence

    def sniff_structure(self, sniff_no: str, intake_batch: str,
                        sample_rows: list[list[str]],
                        delimiter_rule_no: str) -> tuple[bool, str, dict[str, Any] | None]:
        """执行结构嗅探并写入推断记录，产出解析起始行结论。"""
        rows = store.rows(self.MODULE)
        if not sample_rows:
            return False, f"批次 {intake_batch} 样本行为空，无法嗅探结构", None

        is_header, confidence = self.detect_header(sample_rows)
        column_count = len(sample_rows[0])
        inconsistent = [
            i for i, r in enumerate(sample_rows) if len(r) != column_count
        ]
        data_rows = sample_rows[1:] if is_header else sample_rows
        column_names = (
            [c.strip() for c in sample_rows[0]] if is_header
            else [f"col-{i}" for i in range(column_count)]
        )
        column_types: list[str] = []
        for index in range(column_count):
            values = [r[index] for r in data_rows if index < len(r)]
            numeric = sum(1 for v in values if self._looks_numeric(v))
            if values and numeric == len(values):
                has_dot = any("." in v for v in values)
                column_types.append("float" if has_dot else "int")
            else:
                column_types.append("str")

        if inconsistent:
            status = "推断冲突"
            conclusion = (
                f"样本中有 {len(inconsistent)} 行列数与推断列数 {column_count} 不一致"
                f"（样本行 {inconsistent[:5]}），登记推断冲突"
            )
        elif confidence < self.LOW_CONFIDENCE:
            status = "低置信"
            conclusion = f"嗅探置信度 {confidence:.2f} 低于 {self.LOW_CONFIDENCE:.2f}，标记低置信"
        else:
            status = "已推断"
            conclusion = (
                f"推断 {column_count} 列，首行{'是' if is_header else '不是'}表头，"
                f"解析起始行为 {2 if is_header else 1}"
            )

        target = next((r for r in rows if r.get("嗅探编号") == sniff_no), None)
        if target is None:
            entry_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            target = {"id": entry_id, "嗅探编号": sniff_no}
            rows.append(target)
        target.update({
            "关联批次": intake_batch,
            "样本行数": str(len(sample_rows)),
            "推断列数": str(column_count),
            "列名清单": ",".join(column_names),
            "列类型推断": ";".join(column_types),
            "首行是否表头": "是" if is_header else "否",
            "嗅探置信度": f"{confidence:.2f}",
            "命中分隔规则": delimiter_rule_no,
            "status": status,
            "pending": status != "已推断",
            "abnormal": status == "推断冲突",
        })
        return status == "已推断", conclusion, dict(target)

    def parse_start_row(self, sniff_no: str) -> int:
        """输出字段解析消费的起始行。

        最高优先级是结构复核包回填并已采用的有效判读起始行（按该嗅探记录的关联批次）；
        没有复核结论时回退到嗅探结论：表头行为 2，否则为 1。
        """
        sniff_row = None
        for row in store.rows(self.MODULE):
            if row.get("嗅探编号") == sniff_no:
                sniff_row = row
                break
        if sniff_row is not None:
            adopted = review_pack_service.adopted_start_row(
                str(sniff_row.get("关联批次") or ""))
            if adopted is not None:
                return adopted
            if sniff_row.get("status") not in ("已推断",):
                return 1
            return 2 if sniff_row.get("首行是否表头") == "是" else 1
        # 也允许直接传复核包编号/批次编号查询获准起始行。
        adopted = review_pack_service.adopted_start_row(str(sniff_no))
        if adopted is not None:
            return adopted
        return 1

    def blocks_field_parse(self, intake_batch: str) -> tuple[bool, str]:
        """推断冲突或低置信时不得启动字段解析；已有核验通过的复核判读时放行。"""
        # 结构复核包回填的有效判读代表人工已确认结构，优先解除阻断。
        adopted = review_pack_service.adopted_start_row(intake_batch)
        if adopted is not None:
            return False, (
                f"批次 {intake_batch} 已采用结构复核包的有效判读，"
                f"获准起始行为 {adopted}，字段解析可启动"
            )
        for row in store.rows(self.MODULE):
            if row.get("关联批次") != intake_batch:
                continue
            if row.get("status") == "推断冲突":
                return True, (
                    f"批次 {intake_batch} 结构推断冲突（列数不一致），"
                    f"字段解析不得启动"
                )
            if row.get("status") == "低置信":
                return True, (
                    f"批次 {intake_batch} 嗅探置信度 {row.get('嗅探置信度')} 过低，"
                    f"字段解析需人工确认结构后再启动"
                )
        return False, f"批次 {intake_batch} 结构推断可用"

    def inferred_columns(self, sniff_no: str) -> list[str]:
        """输出推断列名清单，供输出契约列集合比对。"""
        for row in store.rows(self.MODULE):
            if row.get("嗅探编号") == sniff_no:
                return [c.strip() for c in str(row.get("列名清单") or "").split(",") if c.strip()]
        return []

    # ------------------------------------------------------------------
    # 结构复核包交接：结构嗅探页是交接入口，以下方法全部委托给共享的
    # SchemaReviewPackService 单例，保证从 schema_sniff 键进入也只有一份状态。
    # __getattr__ 兜底所有命名变体（导出/回填/判读/解析/证据/拒绝查询）。
    # ------------------------------------------------------------------

    HANDOFF_METHODS = (
        "export_review_pack", "create_review_pack",
        "export_structure_review_pack", "create_structure_review_pack",
        "build_review_pack", "generate_review_pack", "handoff_pack",
        "download_review_pack", "download_package", "download_payload",
        "submit_judgment", "backfill_review_pack", "backfill_pack",
        "submit_backfill", "submit_review", "submit_review_judgment",
        "submit_structure_judgment", "record_judgment", "register_judgment",
        "return_judgment", "fill_judgment", "backfill_judgment",
        "verify_judgment", "open_existing_judgment", "get_judgment",
        "append_segment", "arrive_late_segment", "refresh_current_sample",
        "activate_new_rule", "find_pack", "effective_judgment",
        "pack_detail", "get_review_pack", "review_pack_detail",
        "evidence_for_line", "reverse_lookup_sample",
        "cross_batch_rejections", "rejections",
        "parse_with_judgment", "parse_from_judgment", "parse_from_review",
        "parse_with_review_pack", "consume_review_judgment",
        "adopt_judgment_and_parse", "start_parse_from_pack",
        "launch_field_parse", "submit_to_field_parse",
        "current_sample_token",
    )

    def __getattr__(self, name: str) -> Any:
        # 仅在正常属性查找失败时触发；把交接相关调用转发给共享单例。
        if name.startswith("_"):
            raise AttributeError(name)
        target = getattr(review_pack_service, name, None)
        if target is None:
            raise AttributeError(name)
        return target

    def export_structure_review_package(self, *a: Any, **kw: Any):
        return review_pack_service.export_review_pack(*a, **kw)

    def create_structure_review_package(self, *a: Any, **kw: Any):
        return review_pack_service.export_review_pack(*a, **kw)

    def submit_structure_review(self, *a: Any, **kw: Any):
        return review_pack_service.submit_judgment(*a, **kw)

    def parse_adopted_start_row(self, *a: Any, **kw: Any):
        return review_pack_service.parse_with_judgment(*a, **kw)
