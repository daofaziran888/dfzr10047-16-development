"""结构复核包交接链路测试：冻结快照、唯一有效判读、异批/过期/范围拒绝、解析消费与反查。"""
from __future__ import annotations

import pytest

from app.store import store
from app.services import SERVICES


@pytest.fixture(autouse=True)
def fresh():
    store.reload_seed()
    yield
    store.reload_seed()


@pytest.fixture()
def svc():
    return SERVICES["schema_review_pack"]


def test_first_export_contains_id_header_and_a8_first_datum(svc):
    payload = svc.download_payload("SRP-A8-OLD")
    lines = payload["sample_text"].splitlines()
    assert lines[0].split(",")[0] == "ID"
    assert lines[1].split(",")[0] == "A8"
    # 导出时规则版本冻结为 DR-001，不随后续 DR-006 上线改变。
    assert payload["delimiter_rule_no"] == "DR-001"
    assert "2026-06-01" in payload["delimiter_rule_version"]
    assert payload["field_positions"][0]["字段"] == "ID"


def test_export_new_pack_freezes_given_bytes_and_rule(svc):
    ok, msg, pack = svc.export_review_pack(
        "SRP-T1", "FI-T1", [2],
        ["ID,name", "A8,x", "A9,y"], "DR-001")
    assert ok is True
    assert pack["样本原文"].splitlines()[1].startswith("A8")
    ok2, _m, again = svc.export_review_pack(pack_no="SRP-T1", intake_batch="FI-T1")
    assert ok2 is True and again["id"] == pack["id"]  # 同包重复导出不重建快照


def test_late_segment_makes_new_fragment_first_datum_differ(svc):
    svc.append_segment(batch="FI-20260906001", lines=["B7,z", "B8,w"])
    ok, _m, current = svc.refresh_current_sample("SRP-A8-OLD")
    assert ok is True
    assert current["late_fragment_first"].startswith("B7")
    assert current["new_pack_first_data"] == "B7"
    assert current["frozen_first_data"] == "A8"
    assert current["different_first_data"] is True
    # 旧包冻结样本不变。
    assert "B7" not in svc.find_pack("SRP-A8-OLD")["样本原文"]


def test_valid_backfill_then_duplicate_only_one_effective(svc):
    kw = dict(reviewer="yi", actual_first_field="ID",
              first_row_is_header=True, start_row=2, evidence_line=2)
    ok, msg, j = svc.submit_judgment(pack_no="SRP-A8-OLD", **kw)
    assert ok is True and j["status"] == "有效"
    effective = [x for x in svc._judgments()
                 if x["复核包编号"] == "SRP-A8-OLD" and x["status"] == "有效"]
    assert len(effective) == 1
    ok2, msg2, _ = svc.submit_judgment(pack_no="SRP-A8-OLD", reviewer="copy")
    assert ok2 is False and "一次有效" in msg2
    effective = [x for x in svc._judgments()
                 if x["复核包编号"] == "SRP-A8-OLD" and x["status"] == "有效"]
    assert len(effective) == 1


def test_cross_batch_is_forbidden_and_recorded(svc):
    ok, msg, _ = svc.submit_judgment(
        pack_no="SRP-A8-OLD", batch="FI-OTHER", reviewer="mallory")
    assert ok is False
    assert "异批" in msg and "越权" in msg
    rows = svc.cross_batch_rejections("FI-OTHER")
    assert rows and rows[0]["status"] == "异批拒绝"
    # 异批提交没有产生有效判读，目标批次起始行未被修改。
    assert svc.adopted_start_row("FI-OTHER") is None


def test_stale_token_rejected_with_recovery_semantics(svc):
    ok, msg, _ = svc.submit_judgment(
        pack_no="SRP-A8-OLD", seen_token="snap-OLD-OTHER")
    assert ok is False and "过期" in msg
    assert "返回原包" in msg and "继续处理当前样本" in msg


def test_out_of_range_evidence_and_start_row_rejected(svc):
    ok, msg, _ = svc.submit_judgment(pack_no="SRP-A8-OLD", evidence_line=99)
    assert ok is False and "范围拒绝" in msg
    ok, msg, _ = svc.submit_judgment(
        pack_no="SRP-A8-OLD", target_start_row=7)
    assert ok is False and "起始行" in msg


def test_wrong_first_field_fails_verification(svc):
    ok, msg, _ = svc.submit_judgment(
        pack_no="SRP-A8-OLD", actual_first_field="UUID")
    assert ok is False and "字段位置" in msg


def test_parse_consumes_start_row_syncs_ledger_and_traces_sample(svc):
    svc.submit_judgment(
        pack_no="SRP-A8-OLD", reviewer="yi", actual_first_field="ID",
        first_row_is_header=True, start_row=2, evidence_line=2)
    svc.append_segment(batch="FI-20260906001",
                       lines=["B7,late,9.1,2026-09-02", "B8,late2,9.2,2026-09-02"])
    ok, msg, result = svc.parse_with_judgment(pack_no="SRP-A8-OLD")
    assert ok is True
    # 从获准起始行 2 开始，原始行 2..5 都被写出，表头行 1 不写。
    assert result["approved_start_row"] == 2
    assert result["parsed_line_numbers"] == [2, 3, 4, 5]
    assert result["first_field"] == "ID"
    assert result["first_data_value"] == "A8"
    # 每次解析用到的判读可回到样本。
    evidence = svc.evidence_for_line("FI-20260906001", 2)
    assert evidence["实际首条字段"] == "ID"
    assert evidence["raw_line"].startswith("A8")
    assert evidence["judgment"]["判读编号"] == result["judgment_no"]
    # 批次台账同步采用结论。
    ledger = next(r for r in store.rows("parse_batch")
                  if r["关联投递批次"] == "FI-20260906001")
    assert ledger["获准起始行"] == 2
    assert ledger["采用判读编号"] == result["judgment_no"]
    # schema_sniff 的 parse_start_row 也消费该获准起始行（按批次）。
    sniff = SERVICES["schema_sniff"]
    assert sniff.parse_start_row("FI-20260906001") == 2


def test_parse_without_effective_judgment_blocked(svc):
    ok, msg, result = svc.parse_with_judgment(pack_no="SRP-A8-OLD")
    assert ok is False and "有效判读" in msg and result is None


def test_same_judgment_parse_is_idempotent(svc):
    svc.submit_judgment(pack_no="SRP-A8-OLD", start_row=2)
    ok1, _m, r1 = svc.parse_with_judgment(pack_no="SRP-A8-OLD")
    before = len([r for r in store.rows("field_parse") if r.get("复核包编号") == "SRP-A8-OLD"])
    ok2, _m, r2 = svc.parse_with_judgment(pack_no="SRP-A8-OLD")
    after = len([r for r in store.rows("field_parse") if r.get("复核包编号") == "SRP-A8-OLD"])
    assert ok1 and ok2 and r2["idempotent"] is True
    assert before == after


def test_seed_existing_judgment_can_be_opened(svc):
    j = svc.open_existing_judgment("SRP-DONE-02")
    assert j is not None and j["status"] == "有效"
    assert j["实际首条字段"] == "UUID"
