"""
P4-L4 2026-08-08 回归测试: force 模式 3 个 picker 的 source_id 跟 validator 校验对得上

之前 bug: _pick_forced_logistics_complaint 拼 source_id=f"COMP_{rec_id}",
          record_id 是 bigint AUTO_INCREMENT, validator 强转 int("COMP_xxx") ValueError,
          每天固定 ~20 次失败 (200 条/天 * 30% force * 1/3 picker).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "gen_risk_data_with_dates.py"
SQL_PATH = ROOT / "sql" / "init_business_tables.sql"


class TestForcePickerSourceId:
    """force 模式 3 个 picker 的 source_id 必须跟 validator 校验对得上"""

    def test_logistics_complaint_source_id_no_prefix(self):
        """物流投诉 picker 不能拼 COMP_ 前缀, 必须用原始 record_id (整数转字符串)."""
        src = SCRIPT_PATH.read_text(encoding="utf-8")
        assert 'source_id=f"COMP_' not in src, (
            "物流投诉 picker 不能再用 f\"COMP_{rec_id}\" 拼字符串, "
            "validator 强转 int() 会 ValueError"
        )
        assert 'source_id=str(rec_id)' in src, (
            "物流投诉 picker 应直接用 record_id, 写 source_id=str(rec_id)"
        )

    def test_all_three_force_pickers_in_script(self):
        """3 个 force picker 都应在脚本中定义."""
        src = SCRIPT_PATH.read_text(encoding="utf-8")
        assert '"售后申请", _pick_forced_postsale' in src, "应有售后 picker"
        assert '"物流投诉", _pick_forced_logistics_complaint' in src, "应有物流投诉 picker"
        assert '"下单", _pick_forced_order_for_high_amount' in src, "应有高额订单 picker"
        assert src.count("RiskCheckRequest(") >= 3, "3 个 picker 都应构造 RiskCheckRequest"

    def test_logistics_complaint_record_id_is_bigint(self):
        """logistics_complaints_record.record_id 必须是整数 (跟 validator 强转 int 对应)."""
        sql = SQL_PATH.read_text(encoding="utf-8")
        m = re.search(r"`record_id`\s+(\w+)[^,]*AUTO_INCREMENT", sql)
        assert m, "logistics_complaints_record.record_id 必须是 AUTO_INCREMENT 整数"
        col_type = m.group(1).lower()
        assert "int" in col_type or "bigint" in col_type, (
            f"record_id 必须是整数类型, 实际: {col_type}"
        )

    def test_validator_caster_matches_record_id_type(self):
        """validator 强转 int() 必须跟 record_id 类型 (整数) 对得上."""
        # validator.py: ("物流投诉",): (LogisticsComplaintsRecord, "record_id", int, ...)
        # source_id=str(rec_id) → "123" → int("123") = 123 OK
        # source_id=f"COMP_{rec_id}" → "COMP_123" → int("COMP_123") ValueError
        src = SCRIPT_PATH.read_text(encoding="utf-8")
        assert 'source_id=str(rec_id)' in src, "source_id 必须是整数字符串, 不带前缀"
