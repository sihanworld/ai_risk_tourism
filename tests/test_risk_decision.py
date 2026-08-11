"""
测试 - 决策引擎 (risk_decision.py)
"""

import pytest

from app.engine.rule import RuleHitResult
from app.engine.decision import calculate_final_score, check_veto, _score_to_level, _score_to_decision, _ml_prob_to_risk_score


class _MockRule:
    """模拟 RiskRule 对象"""
    def __init__(self, rule_id, rule_name, rule_category, risk_level, risk_score, action, description=""):
        self.rule_id = rule_id
        self.rule_name = rule_name
        self.rule_category = rule_category
        self.risk_level = risk_level
        self.risk_score = risk_score
        self.action = action
        self.description = description


class TestScoreCalculation:
    """测试评分计算"""

    def test_no_hits(self):
        assert calculate_final_score([]) == 0

    def test_single_hit(self):
        hit = RuleHitResult(_MockRule("R1", "测试", "预订欺诈", "高", 70, "人工审核"))
        assert calculate_final_score([hit]) == 70

    def test_multiple_hits_bonus(self):
        """多规则命中: max + BONUS × extra_count"""
        hits = [
            RuleHitResult(_MockRule("R1", "测试1", "预订欺诈", "高", 70, "人工审核")),
            RuleHitResult(_MockRule("R2", "测试2", "支付风险", "中", 40, "标记")),
            RuleHitResult(_MockRule("R3", "测试3", "账户风险", "低", 20, "通过")),
        ]
        # max=70, extra=2, bonus=3*2=6, total=76
        assert calculate_final_score(hits) == 76

    def test_score_cap_100(self):
        """评分上限100"""
        hits = [
            RuleHitResult(_MockRule("R1", "t", "x", "极高", 95, "拒绝")),
            RuleHitResult(_MockRule("R2", "t", "x", "高", 80, "人工审核")),
            RuleHitResult(_MockRule("R3", "t", "x", "高", 70, "人工审核")),
        ]
        # max=95, extra=2, bonus=6, total=101 → cap 100
        assert calculate_final_score(hits) == 100


class TestVetoCheck:
    """测试一票否决"""

    def test_no_veto(self):
        hits = [RuleHitResult(_MockRule("R1", "t", "x", "高", 70, "人工审核"))]
        assert not check_veto(hits)

    def test_has_veto(self):
        hits = [
            RuleHitResult(_MockRule("R1", "t", "x", "高", 70, "人工审核")),
            RuleHitResult(_MockRule("R2", "t", "x", "极高", 95, "拒绝")),
        ]
        assert check_veto(hits)


class TestScoreMapping:
    """测试评分到等级/决策的映射"""

    def test_level_mapping(self):
        assert _score_to_level(0) == "低"
        assert _score_to_level(29) == "低"
        assert _score_to_level(30) == "中"
        assert _score_to_level(59) == "中"
        assert _score_to_level(60) == "高"
        assert _score_to_level(79) == "高"
        assert _score_to_level(80) == "极高"
        assert _score_to_level(100) == "极高"

    def test_decision_mapping(self):
        # 【P0-S2 修复 2026-08-07】原代码 score=80→"人工审核"是 bug
        # 应按 RISK_REVIEW_THRESHOLD=80 严格分界, 80 起就是"拒绝"
        assert _score_to_decision(0) == "通过"
        assert _score_to_decision(29) == "通过"
        assert _score_to_decision(30) == "标记"
        assert _score_to_decision(59) == "标记"
        assert _score_to_decision(60) == "人工审核"
        assert _score_to_decision(79) == "人工审核"
        assert _score_to_decision(80) == "拒绝"
        assert _score_to_decision(100) == "拒绝"


class TestVetoHardVetoAfterFusion:
    """
    【P0-S2 修复 2026-08-07】一票否决在双轨融合后必须仍生效.

    反例: R002 (单笔 10000+) 命中 → rule_score=95, XGBoost 给 P=0.1 → 10
          融合: 0.5×95 + 0.5×10 = 52.5 → 原代码 → "标记"放行 ❌
          修后: 仍 → "拒绝" ✅

    【P5 优化 2026-08-08】monkeypatch 路径改成 decision.predict / decision.is_model_loaded,
    因为 decision.py 顶部 from app.engine.ml_model import predict 已经把函数对象
    引用到 decision 的 namespace, patch ml_model.predict 不影响 decision 的引用.
    """
    def test_veto_with_low_ml_still_reject(self, monkeypatch):
        """veto + ML 低分 → 强制拒绝, 不被 ML 拉成标记"""
        from app.engine import decision

        # 模拟一票否决规则: R002 (极高, 95 分)
        veto_hit = RuleHitResult(_MockRule(
            "R002", "单笔极端高额订单", "预订欺诈", "极高", 95, "拒绝",
        ))

        # mock 掉 decision 模块内引用的 predict (不是 ml_model.predict)
        # 因为 decision.py 顶部 `from app.engine.ml_model import predict` 已经
        # 把函数对象引用过来, patch ml_model.predict 不影响这个引用.
        class _FakeMlResult:
            score = 0.1
            decision = "通过"
            is_loaded = True
        monkeypatch.setattr(decision, "predict", lambda features: _FakeMlResult())
        monkeypatch.setattr(decision, "is_model_loaded", lambda: True)

        final_score, risk_level, decision_str, ml_score, ml_decision = decision._calculate_decision(
            [veto_hit],
            {"order_total_amount": 12000},  # 触发 R002
        )

        # 验证: 即使 ML 觉得"通过", 一票否决也要硬性拒绝
        assert decision_str == "拒绝", f"veto 命中必须拒绝, 实际={decision_str}"
        assert risk_level == "极高"
        # final_score 至少被抬到 VETO_MIN_SCORE (90)
        assert final_score >= decision.settings.RISK_VETO_MIN_SCORE
        # ml_score 仍按真实值返回 (供前端展示 ML 维度)
        assert ml_score == 0.1
        assert ml_decision == "通过"

    def test_veto_with_high_ml_also_reject(self, monkeypatch):
        """veto + ML 高分 → 拒绝 (本来也是拒绝, 验证不破坏正常路径)"""
        from app.engine import decision

        veto_hit = RuleHitResult(_MockRule(
            "R007", "30天30单", "支付风险", "极高", 90, "拒绝",
        ))

        class _FakeMlResult:
            score = 0.95
            decision = "拒绝"
            is_loaded = True
        monkeypatch.setattr(decision, "predict", lambda features: _FakeMlResult())
        monkeypatch.setattr(decision, "is_model_loaded", lambda: True)

        final_score, risk_level, decision_str, *_ = decision._calculate_decision(
            [veto_hit],
            {"user_orders_30d": 50},
        )
        assert decision_str == "拒绝"
        assert risk_level == "极高"

    def test_no_veto_high_rule_low_ml_becomes_mark(self, monkeypatch):
        """没 veto + 规则高 + ML 低 → 会被融合成"标记" (验证不破坏正常路径)"""
        from app.engine import decision

        # 普通高风险规则 (不是 veto)
        normal_hit = RuleHitResult(_MockRule(
            "R001", "单笔超高金额", "预订欺诈", "高", 70, "人工审核",
        ))

        class _FakeMlResult:
            score = 0.1
            decision = "通过"
            is_loaded = True
        monkeypatch.setattr(decision, "predict", lambda features: _FakeMlResult())
        monkeypatch.setattr(decision, "is_model_loaded", lambda: True)

        final_score, risk_level, decision_str, *_ = decision._calculate_decision(
            [normal_hit],
            {"order_total_amount": 6000},
        )
        # rule_score=70, ml_score_100 = sigmoid 校准 0.1→26 (P4-L4 2026-08-08 修复)
        # final_score = 0.5×70 + 0.5×26 = 48 → "标记" (中风险)
        # 注: 之前线性是 40 (0.1×100=10), 现在校准后是 48, 仍判"标记"
        assert decision_str == "标记", f"融合后应=标记, 实际={decision_str}"
        assert risk_level == "中"
        assert final_score == 48, f"sigmoid 校准后 final_score=48, 实际={final_score}"


class TestCaseDeduplication:
    """
    【P1-S6 修复 2026-08-07】同一 (source_id, event_type) 不应建多个未结案.

    场景: 同一订单的"预订"事件被前端重试 3 次, 每次都触发"人工审核"
          决策. 原代码会建 3 个 case. 修复后: 第 2/3 次直接 skip.
    """
    @pytest.mark.asyncio
    async def test_existing_open_case_skips_new_one(self):
        """已有"待审核"case → skip, 不再 add"""
        from app.engine import decision
        from app.schemas import RiskCheckRequest
        from types import SimpleNamespace

        # mock ctx
        request = RiskCheckRequest(
            event_type="预订", source_id="order_001", user_id="1001",
        )
        ctx = SimpleNamespace(
            request=request,
            user_id="1001",
        )
        hit = RuleHitResult(_MockRule("R1", "测试", "预订欺诈", "高", 70, "人工审核"))

        # mock db: execute 返回已有 case_id
        existing_case_id = "cas_existing_xxx"
        class _FakeResult:
            def scalar_one_or_none(self):
                return existing_case_id
        class _FakeDB:
            def __init__(self):
                self.added = []
                self.committed = False
            async def execute(self, stmt):
                return _FakeResult()
            def add(self, obj):
                self.added.append(obj)
            async def commit(self):
                self.committed = True

        db = _FakeDB()
        await decision._maybe_create_case(
            db, "ast_xxx", ctx, [hit], 75, "人工审核",
        )
        # 关键断言: 没有 add 新 case
        assert len(db.added) == 0, f"应不建新 case, 实际 add 了 {len(db.added)} 个"

    @pytest.mark.asyncio
    async def test_no_existing_case_creates_new(self):
        """没有未结案 case → 正常 add"""
        from app.engine import decision
        from app.schemas import RiskCheckRequest
        from types import SimpleNamespace

        request = RiskCheckRequest(
            event_type="预订", source_id="order_002", user_id="1001",
        )
        ctx = SimpleNamespace(request=request, user_id="1001")
        hit = RuleHitResult(_MockRule("R1", "测试", "预订欺诈", "高", 70, "人工审核"))

        class _FakeResult:
            def scalar_one_or_none(self):
                return None  # 没有已有 case
        class _FakeDB:
            def __init__(self):
                self.added = []
            async def execute(self, stmt):
                return _FakeResult()
            def add(self, obj):
                self.added.append(obj)
            async def commit(self):
                pass

        db = _FakeDB()
        await decision._maybe_create_case(
            db, "ast_xxx", ctx, [hit], 75, "人工审核",
        )
        assert len(db.added) == 1, f"应 add 1 个 case, 实际 {len(db.added)}"
        assert db.added[0].case_status == "待审核"
        assert db.added[0].source_id == "order_002"
        assert db.added[0].event_type == "预订"

    @pytest.mark.asyncio
    async def test_pass_decision_skips_creation(self):
        """decision="通过" → 不查重也不建案"""
        from app.engine import decision
        from app.schemas import RiskCheckRequest
        from types import SimpleNamespace

        request = RiskCheckRequest(
            event_type="预订", source_id="order_003", user_id="1001",
        )
        ctx = SimpleNamespace(request=request, user_id="1001")
        hit = RuleHitResult(_MockRule("R1", "测试", "预订欺诈", "高", 70, "人工审核"))

        # db.execute 调了就报错 (说明代码去查重了, 不该)
        class _FakeDB:
            def __init__(self):
                self.executed = 0
            async def execute(self, stmt):
                self.executed += 1
                raise AssertionError("decision=通过 不该查重")
            def add(self, obj):
                raise AssertionError("decision=通过 不该 add")

        db = _FakeDB()
        await decision._maybe_create_case(
            db, "ast_xxx", ctx, [hit], 20, "通过",
        )
        assert db.executed == 0

    @pytest.mark.asyncio
    async def test_auto_reject_creates_closed_case(self):
        """【P2-S8 2026-08-08】decision="拒绝" → case_status="已拒绝" 自动关案.

        原 bug: 一刀切 case_status="待审核", 90+ 分的"拒绝"案件也卡在"待审核"
        等人工, 业务上看着像"没拒"实际已经拒. 修复: 自动拒绝的案件直接
        case_status="已拒绝" + reviewer="system" + review_time, 并记
        AUTO_REJECT_CASE 审计. 决策"人工审核" 才走"待审核".
        """
        from app.engine import decision
        from app.schemas import RiskCheckRequest
        from types import SimpleNamespace

        request = RiskCheckRequest(
            event_type="预订", source_id="order_reject_001", user_id="U001",
        )
        ctx = SimpleNamespace(request=request, user_id="U001")
        # R002 风格: risk_level="极高" risk_score=95
        hit = RuleHitResult(_MockRule("R002", "单笔极端高额订单",
                                      "预订欺诈", "极高", 95, "拒绝"))

        class _FakeResult:
            def scalar_one_or_none(self):
                return None  # 没有已存在 case
        class _FakeDB:
            def __init__(self):
                self.added = []
            async def execute(self, stmt):
                return _FakeResult()
            def add(self, obj):
                self.added.append(obj)
            async def commit(self):
                pass

        db = _FakeDB()
        await decision._maybe_create_case(
            db, "ast_xxx", ctx, [hit], 95, "拒绝",
        )
        # 应 add 1 个 case + 1 条 AUTO_REJECT_CASE 审计
        case = next((x for x in db.added if x.__class__.__name__ == "RiskCase"), None)
        log = next((x for x in db.added if x.__class__.__name__ == "RiskActionLog"), None)
        assert case is not None, f"应建 1 个 case, 实际 add: {[type(x).__name__ for x in db.added]}"
        assert case.case_status == "已拒绝", f"自动拒绝应直接关案, 实际 {case.case_status}"
        assert case.reviewer == "system", f"reviewer 应是 system, 实际 {case.reviewer}"
        assert case.review_time is not None, "review_time 应填"
        assert "95" in (case.review_comment or ""), "review_comment 应含 final_score"
        assert log is not None, "应记 1 条 AUTO_REJECT_CASE 审计"
        assert log.operator == "system"
        assert log.action_type == "AUTO_REJECT_CASE"

    @pytest.mark.asyncio
    async def test_manual_review_keeps_pending(self):
        """decision="人工审核" → 仍走"待审核" (不自动关案, 留给人工审)"""
        from app.engine import decision
        from app.schemas import RiskCheckRequest
        from types import SimpleNamespace

        request = RiskCheckRequest(
            event_type="预订", source_id="order_review_001", user_id="U002",
        )
        ctx = SimpleNamespace(request=request, user_id="U002")
        hit = RuleHitResult(_MockRule("R005", "高折扣率订单",
                                      "预订欺诈", "高", 65, "人工审核"))

        class _FakeResult:
            def scalar_one_or_none(self):
                return None
        class _FakeDB:
            def __init__(self):
                self.added = []
            async def execute(self, stmt):
                return _FakeResult()
            def add(self, obj):
                self.added.append(obj)
            async def commit(self):
                pass

        db = _FakeDB()
        await decision._maybe_create_case(
            db, "ast_xxx", ctx, [hit], 65, "人工审核",
        )
        case = next((x for x in db.added if x.__class__.__name__ == "RiskCase"), None)
        log = next((x for x in db.added if x.__class__.__name__ == "RiskActionLog"), None)
        assert case is not None
        assert case.case_status == "待审核", f"人工审核应留待审核, 实际 {case.case_status}"
        assert case.reviewer is None, "人工审核时 reviewer 应为空 (留给人工填)"
        assert log is None, "人工审核不应记 AUTO_REJECT_CASE 审计"


class TestCaseCategoryAggregation:
    """
    【P2-S5 修复 2026-08-07】案件分类按命中规则 category 聚合, 取命中数最多的.
    原代码用 rules[0].rule_category (priority 高的首条), 业务上不准.
    """

    @pytest.mark.asyncio
    async def test_majority_category_wins(self):
        """3 条支付风险 + 1 条预订欺诈 → 分类 = 支付风险 (命中数最多)"""
        from app.engine import decision
        from app.schemas import RiskCheckRequest
        from types import SimpleNamespace

        request = RiskCheckRequest(
            event_type="支付", source_id="order_x", user_id="1001",
        )
        ctx = SimpleNamespace(request=request, user_id="1001")
        # priority 高的 R007 (支付风险) 排第一
        rules = [
            RuleHitResult(_MockRule("R007", "30天30单", "支付风险", "极高", 90, "拒绝")),
            RuleHitResult(_MockRule("R006", "7天10单", "支付风险", "高", 70, "人工审核")),
            RuleHitResult(_MockRule("R008", "金额异常", "支付风险", "高", 65, "人工审核")),
            RuleHitResult(_MockRule("R001", "5000+", "预订欺诈", "高", 70, "人工审核")),
        ]

        class _FakeResult:
            def scalar_one_or_none(self):
                return None  # 没已存在 case
        class _FakeDB:
            def __init__(self):
                self.added = []
            async def execute(self, stmt):
                return _FakeResult()
            def add(self, obj):
                self.added.append(obj)
            async def commit(self):
                pass

        db = _FakeDB()
        await decision._maybe_create_case(db, "ast_xxx", ctx, rules, 90, "拒绝")
        # decision="拒绝" → 1 个 case + 1 条 AUTO_REJECT_CASE 审计 (P2-S8 2026-08-08)
        case = next((x for x in db.added if x.__class__.__name__ == "RiskCase"), None)
        log = next((x for x in db.added if x.__class__.__name__ == "RiskActionLog"), None)
        assert case is not None and log is not None
        # 3 条支付风险 vs 1 条预订欺诈 → 取多的
        assert case.case_category == "支付风险", (
            f"应取命中数最多的 '支付风险', 实际 {case.case_category}"
        )

    @pytest.mark.asyncio
    async def test_tie_first_one_wins(self):
        """2+2 平局 → 取 first occurrence (Counter.most_common 行为)"""
        from app.engine import decision
        from app.schemas import RiskCheckRequest
        from types import SimpleNamespace

        request = RiskCheckRequest(
            event_type="预订", source_id="order_y", user_id="1001",
        )
        ctx = SimpleNamespace(request=request, user_id="1001")
        # 1 条预订欺诈 + 1 条行程风险 → 平局
        rules = [
            RuleHitResult(_MockRule("R1", "a", "预订欺诈", "高", 70, "人工审核")),
            RuleHitResult(_MockRule("R2", "b", "行程风险", "高", 70, "人工审核")),
        ]

        class _FakeResult:
            def scalar_one_or_none(self):
                return None
        class _FakeDB:
            def __init__(self):
                self.added = []
            async def execute(self, stmt):
                return _FakeResult()
            def add(self, obj):
                self.added.append(obj)
            async def commit(self):
                pass

        db = _FakeDB()
        await decision._maybe_create_case(db, "ast_xxx", ctx, rules, 80, "人工审核")
        # 平局时, Counter.most_common 返回先出现的 (Python 3.7+ dict 有序)
        assert db.added[0].case_category in ("预订欺诈", "行程风险")
