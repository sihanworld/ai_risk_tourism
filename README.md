# 电商风控系统 AI_Risk — 项目启动文档

> 5 层架构 · 26 张表 · **329 个测试** · 25 维特征 · 30 条规则 · 8 个 AI 工具 · V2 XGBoost 双轨融合 + sigmoid 校准 + 训练数据严格化 + 一条龙命令 + 教学场景训练 + 统一日志 + 一键启动 + 通用分页 + 左侧固定布局 + 训练质量验收 + 最佳 F1 阈值 + RISK 用户参数化生成 + 训练数据校验 + 训练数据生成器正例控制 + 造数据 day_offset 循环回归 + 强制正例比例 + 分页栏粘底 + 分页按钮文字可见 + 脚本 emoji GBK 修复 + 校验函数去重
>
> 适用：项目第一次启动 / 老环境升级 / 规则制定 / XGBoost 训练 / 启动服务

---

## 目录

1. [环境准备](#1-环境准备)
2. [数据库初始化](#2-数据库初始化)
3. [数据生成（4 种场景）](#3-数据生成)
4. [规则制定](#4-规则制定)
5. [XGBoost 模型训练](#5-xgboost-模型训练)
6. [启动 FastAPI 服务](#6-启动-fastapi-服务)  ← P4-L4 一键启动加 6 步自检
7. [跑测试](#7-跑测试)
8. [生产部署 (Docker)](#8-生产部署-docker)  ← P4-L4 移到 docker/ 子目录
9. [日志管理](#9-日志管理)  ← P4-L4 2026-08-08
10. [常见问题 FAQ](#10-常见问题-faq)
11. [一句话总结](#11-一句话总结)

---

## 1. 环境准备

### 1.1 Python 依赖

```bash
# 推荐: conda
conda create -n risk python=3.11 -y
conda activate risk
pip install -r requirements.txt

# 或: venv
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

依赖：`fastapi 0.115` / `uvicorn 0.34` / `sqlalchemy 2.0` / `aiomysql 0.2` / `pymysql 1.1` / `pydantic 2.10` / `jinja2 3.1` / `langchain 1.2` / `langchain-openai 1.1` / `langchain-deepagents 0.5` / `pandas 2.2` / `numpy 2.2` / `faker 33` / `ulid-py 1.1` / `pytest 8.3` / `pytest-asyncio 0.25` / `cryptography 44` / `xgboost 2.1` / `httpx 0.27`

### 1.2 MySQL 准备

```bash
# Docker (推荐)
docker run -d --name risk-mysql \
  -e MYSQL_ROOT_PASSWORD=123321 \
  -e MYSQL_DATABASE=ecs \
  -p 3306:3306 \
  mysql:8.0 \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_0900_ai_ci

# 或本地 MySQL: 确保 utf8mb4 + 用户能 CREATE DATABASE
```

### 1.3 .env 配置

```ini
# .env (项目根目录)
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=123321
DB_NAME=ecs
TEST_DB_NAME=ecs_test

# LLM (阿里云百炼 OpenAI 兼容)
LLM_API_KEY=sk-你的key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# XGBoost 开关 (默认 True, 第一次没模型时自动降级)
XGB_ENABLED=True
```

---

## 2. 数据库初始化

### 2.1 新装环境（首次）

```bash
python scripts/init_db.py
```

**会按顺序执行**：
1. 创建数据库 `ecs`
2. `init_business_tables.sql` — 17 张业务表
3. `init_business_data.sql` — ~4100 条业务测试数据
4. `init_risk_tables.sql` — 9 张风控表（含 P4 2 张：risk_action_log + risk_alert）
5. `init_risk_data.sql` — 30 条预置风控规则 (R001-R030)

加 `--drop` 参数可以**先删后建**（⚠️ 危险，会清空所有数据）：
```bash
python scripts/init_db.py --drop
```

### 2.2 老环境升级（2026-08-07 之前装过）

```bash
# 1. 加 2 张 P4 新表 (幂等)
mysql -u root -p ecs < sql/migration_add_p4_tables.sql

# 2. 加 4 个新字段 (幂等)
mysql -u root -p ecs < sql/migration_add_2026_08_07_fields.sql
```

新增字段：
- `risk_rule.deleted_at` (P3-M9 软删)
- `risk_blacklist.deleted_at` (P3-M9 软删)
- `risk_assessment.ml_score` (V2 XGBoost 拒绝概率)
- `risk_assessment.ml_decision` (V2 XGBoost 决策)

> 重复执行无副作用（用 `INFORMATION_SCHEMA` 查重）

### 2.3 验证 DDL 同步

```bash
DDL_CHECK_ENABLED=1 pytest tests/test_ddl_sync.py -v
```

`test_ddl_sync.py` 用 SQLAlchemy 反射真实数据库，对比 `models_risk.py` 字段定义。**默认 skip**（需要真实 DB）。

---

## 3. 数据生成

有 4 个场景，按需选：

### 3.1 大量随机业务数据（10w 条 / 5w 用户 / 30w 订单）

**默认 10w，可指定**：
```bash
# 默认 10w
python scripts/gen_10w_data.py

# 指定 5w 业务数据
python scripts/gen_10w_data.py --users 5000 --orders 30000

# 指定每用户 1-8 单
python scripts/gen_10w_data.py --min-orders 1 --max-orders 8
```

**产出**：
- `N` 用户 (默认 10,000)
- 每个用户 1-3 个收货地址
- 每个用户 1-8 笔订单（平均 3）
- 每笔订单 1-5 个明细
- 10-20% 概率有售后
- 5% 概率有物流投诉

**风险画像**（自动注入）：
- 80% 正常用户
- 15% 中风险（高退款率 / 多地址）
- 5% 高风险（大额订单 / 深夜下单 / 极高退款率 90%+）

### 3.2 业务数据补充（如果 init_db.py 的 4100 条不够用）

```bash
# 默认 30 条风控评估
python scripts/gen_risk_data.py
python scripts/gen_risk_data.py 100   # 100 条

# P4-L3 2026-08-08: 训练 XGBoost 时, 想要正例 (人工审核/拒绝) 占比 >= 20%
# 加 --balance-pos, 80% 概率从 RISK00X 高风险用户里挑数据
python scripts/gen_risk_data.py --count 200 --balance-pos
```

从现有订单/售后里随机挑，跑 `process_event()` 7 步流水线，**生成 risk_event / risk_feature / risk_assessment / risk_case 记录**。
`--balance-pos` 优先抽 `RISK00X` 预置高风险用户（高退款率/高频下单/大额退款/多地址/有投诉），让训练时正例占比 25%~35%。

### 3.2.1 训练数据严格化（**P4-L4 2026-08-08**）

**问题**：之前的 `gen_risk_data.py` 随机抽样，标签跟用户身份弱相关，正例比例 < 3%，模型假收敛。

**解决**：`gen_train_dataset.py` 严格造 1500 条训练数据：

```bash
python scripts/gen_train_dataset.py --reset
# 30 RISK × 25 售后申请 (高风险事件) + 30 普通 × 25 下单 (正常事件) = 1500 条
# 标签: 30 规则跑出 (decision 字段)
# 特征: 25 维真实从 DB 查 (feature.py)
# ml_score: 写库后强制 NULL (干净, 避免"未训练模型"垃圾值)
```

**回填 ml_score**（训完用 `backfill_ml_score.py` 回填合理值）：
```bash
python scripts/train_xgb_model.py
python scripts/backfill_ml_score.py  # 用训好的模型推理回填
```

### 3.2.2 教学场景训练（**P4-L4 2026-08-08**）

不需要真实 DB，纯 numpy 合成训练数据：

```bash
python scripts/train_demo_model.py --n 2000
# 6 种高风险模式 + 1 种正常模式 (高退款率/高投诉/大额/多地址/夜间/混合 + 普通)
# 5 秒出结果, val_auc = 1.0 (合成数据太干净, 教学场景够用)
```

**适用**：用户没真实业务数据时，立即能得到一个可用的 XGBoost 模型。

### 3.2.3 一条龙命令（**P4-L4 2026-08-08**）

6 步 Python 入口脚本，从 0 到启动：

```bash
python scripts/one_command.py                # 跑全部 6 步
python scripts/one_command.py --skip-init    # 跳过 1+2 (DB + RISK 用户已就绪)
python scripts/one_command.py --skip-train   # 跳过 3+4+5 (训练数据 + 模型已就绪)
python scripts/one_command.py --only-start   # 只跑步骤 6 (造今日业务数据)
```

**6 步**：`init_db.py --reset --yes` → `gen_risky_users.py --count 30` → `gen_train_dataset.py --reset` → `train_xgb_model.py` → `backfill_ml_score.py` → `gen_risk_data_with_dates.py --days 1 --per-day 50 --live`

**特性**：跨平台（Windows/Linux/Mac），失败立即中断 + 排查建议。

### 3.3 带日期范围的造数据（仪表盘跨天趋势用）

```bash
# 近 7 天, 每天随机 1~30 条
python scripts/gen_risk_data_with_dates.py

# 每天固定 15 条
python scripts/gen_risk_data_with_dates.py --per-day 15

# 近 30 天, 每天固定 10 条
python scripts/gen_risk_data_with_dates.py --days 30 --per-day 10

# 清空后重建
python scripts/gen_risk_data_with_dates.py --days 7 --per-day 20 --clean
```

### 3.4 高风险用户样本（规则测试用）

```bash
python scripts/gen_risky_users.py
```

生成 5 个 RISK001-RISK005 高风险样本（高退款率 / 高频下单 / 高退款金额 / 多地址 / 有投诉），用于规则引擎单测和前端演示。

---

## 4. 规则制定

### 4.1 30 条预置规则

`init_risk_data.sql` 已经插入了 30 条规则 (R001-R030)，分布 6 大类：

| 类别 | 数量 | 典型规则 |
|---|---:|---|
| 订单欺诈 | 5 | R001 (≥5000 标记) / R002 (≥10000 拒绝, 极高) |
| 支付风险 | 4 | R006 (7 天 10 单) / R007 (30 天 30 单, 极高) |
| 账户风险 | 4 | R010 (退款率 ≥30%) / R015 (≥80%, 极高) |
| 售后滥用 | 3 | R012 (退款次数 ≥5) |
| 地址风险 | 4 | R017 (多省份) |
| 物流风险 | 3 | R022 (投诉 ≥3) |

### 4.2 规则 JSON 结构

```json
{
  "field": "order_total_amount",   // 25 维特征名
  "op": ">=",                       // > >= < <= == != in not_in between
  "value": 5000                     // 比较值 / 列表 [min, max]
}
```

支持嵌套（`and` / `or`）：
```json
{
  "and": [
    {"field": "user_refund_rate", "op": ">=", "value": 0.3},
    {"field": "user_total_orders", "op": ">=", "value": 5}
  ]
}
```

### 4.3 通过 SQL 加规则（推荐）

```sql
INSERT INTO risk_rule (
  rule_id, rule_name, rule_category, event_type,
  rule_condition, risk_level, risk_score, action, is_enabled, priority, description
) VALUES (
  'R025', '我的新规则', '订单欺诈', '下单',
  '{"field": "order_total_amount", "op": ">=", "value": 3000}',
  '高', 60, '人工审核', 1, 50,
  '单笔订单 ≥3000 触发审核'
);
```

### 4.4 通过 API 加规则

```bash
# 创建
curl -X POST http://localhost:8000/api/rules \
  -H "Content-Type: application/json" \
  -d '{
    "rule_id": "R025",
    "rule_name": "我的新规则",
    "rule_category": "订单欺诈",
    "event_type": "下单",
    "rule_condition": {"field": "order_total_amount", "op": ">=", "value": 3000},
    "risk_level": "高",
    "risk_score": 60,
    "action": "人工审核",
    "priority": 50,
    "description": "单笔订单 ≥3000 触发审核"
  }'

# 列表
curl http://localhost:8000/api/rules
```

### 4.5 软删（不删行，P3-M9）

```sql
-- 单条
UPDATE risk_rule SET deleted_at = NOW() WHERE rule_id = 'R025';

-- 查未软删
SELECT * FROM risk_rule WHERE deleted_at IS NULL;
```

---

## 5. XGBoost 模型训练

### 5.1 需不需要训练？

**先看模型状态**：
```bash
ls -la app/engine/xgb_model.json
```

- 文件存在 → 已训练，加载就能用
- 文件不存在 → 没训练，XGBoost 路径自动降级到"纯规则"（不影响业务）

### 5.2 什么时候需要训练？

✅ **要训练的场景**：
- 第一次部署（想用 V2 双轨融合）
- 业务策略调整后（规则改了）
- 累计评估 > 1 万条（数据量增长）
- 至少每季度一次（fraud drift）

❌ **不用训练**：
- 教学演示用纯规则就够
- 评估数据 < 50 条（样本不足，脚本会拒绝）
- 业务还没上线（没有真实数据）

### 5.3 训练流程

```bash
# 0. 准备: 至少 50 条评估 (decision 不为空). 想要正例占比 20%+, 加 --balance-pos
python scripts/gen_risk_data.py --count 200 --balance-pos
# 或者跑前端 /api/risk/check 100 次

# 1. 训练
python scripts/train_xgb_model.py
```

**训练脚本会自动**（P4-L3 2026-08-08 第二轮优化）：
1. 从 `risk_assessment` 拉最近 5000 条评估（**P4-L4** 显式 `WHERE ml_score IS NULL` 锁定"无 ml 痕迹"数据）
2. 每个 `event_id` JOIN 出 25 维特征（`risk_feature`）
3. 标签二分类：0=通过/标记, 1=人工审核/拒绝
4. 过滤掉特征不全的样本
5. **样本 < 1250 打 WARNING**（25 维 × 50 倍经验值，不阻断训练）
6. **scale_pos_weight 超 10 截断并警告**（防止极端不平衡时过拟合）
7. **80/20 stratify 拆分**（验证集正负比 = 训练集正负比）
8. **早停**：验证集 logloss/AUC 连续 10 轮不升就停
9. 同时监控 logloss + auc, 输出训练集 + 验证集两套指标
10. 训练 + 评估 + 保存到 `app/engine/xgb_model.json`

**ML 评分 sigmoid 校准**（**P4-L4 2026-08-08** 修复）：

之前 `decision.py` 用 `int(score*100)` 是**量纲错配**（0.7 概率 ≠ 70 风险分）。改用 sigmoid 校准：

```python
# decision.py::_ml_prob_to_risk_score
risk_score = 100 * (1 - exp(-k * prob))  # k=3
# 0.1→26 / 0.3→59 / 0.5→78 / 0.7→90 / 0.9→97
```

**修复效果**（rule=60 + ml_prob=0.5）：
- 旧：`ml=50, final=55`（被规则拉到 55，**风险被低估**）
- 新：`ml=78, final=69`（跟规则协同增强，**正确反映中高风险**）

**输出指标**：
```
训练完成: n=200, pos=60 (30.0%), neg=140
  scale_pos_weight: 2.33 (raw=2.33)
  best_iteration:   67 (早停在验证集 logloss 连续 10 轮不降时触发)
  AUC=0.9123, F1=0.8420, Acc=0.8950, P=0.8654, R=0.8200
  [验证集]  n=40, AUC=0.8812, F1=0.7890, Acc=0.8500
  模型保存: app/engine/xgb_model.json
[特征重要性 TOP 10] (XGBoost gain)
   1. user_total_orders              18.5  25.3%  ##################
   2. user_refund_rate               12.3  16.8%  ##############
   ...
```

**4 个训练参数**（`app/config.py` 配，`.env` 可覆盖）：

| 参数 | 默认值 | 含义 |
|---|---|---|
| `XGB_TEST_SIZE` | 0.2 | 验证集比例（stratify 拆分）|
| `XGB_EARLY_STOPPING_ROUNDS` | 10 | 验证集 logloss 连续 N 轮不升就停 |
| `XGB_MIN_SAMPLES` | 1250 | 最小训练样本数 = 25 维 × 50 倍 |
| `XGB_MAX_SCALE_POS_WEIGHT` | 10.0 | scale_pos_weight 上限，防过拟合 |

### 5.4 训练权重加载流程（自动）

**无需手动加载**！`app/engine/ml_model.py` 在 import 时自动调度：

```
[启动顺序]
1. 任何代码 import app.engine.ml_model
2. _schedule_load() 在模块底部被调用
3. 检测 settings.XGB_ENABLED
   ├─ False → 跳过加载, 走纯规则
   └─ True → 检查 app/engine/xgb_model.json
      ├─ 不存在 → 跳过加载, 走纯规则 (logger.warn 提示)
      └─ 存在 → xgb.Booster().load_model(path) 加载
4. 设置 _LOADED = True
5. 业务调用 predict(features) 时用
```

**手动验证模型已加载**：
```bash
python -c "
from app.engine.ml_model import is_model_loaded, get_model
print('Loaded:', is_model_loaded())
print('Model:', get_model())
"
```

### 5.5 训练参数调节

在 `app/config.py`：
```python
ML_WEIGHT_RULE: float = 0.5    # 规则分权重 (α)
ML_WEIGHT_XGB: float = 0.5     # XGBoost 分权重 (β, α+β=1)
ML_PASS_THRESHOLD: float = 0.30  # ML 通过阈值
ML_MARK_THRESHOLD: float = 0.60  # ML 标记阈值
ML_REVIEW_THRESHOLD: float = 0.80  # ML 人工审核阈值
```

### 5.6 重训脚本

```bash
# 重训会覆盖 xgb_model.json
python scripts/train_xgb_model.py
```

---

## 6. 启动 FastAPI 服务

### 6.1 一键启动（推荐，**P4-L4 2026-08-08 升级**）

```bash
python run_app.py
```

> 之前叫 `_run.py`（下划线开头 Python 不可 import），已重命名为 `run_app.py`。

启动前自动跑 **6 步自检**：

| 检查项 | 失败级别 | 后果 |
|---|---|---|
| ① .env 文件 | WARN | 提示复制 `docker/.env.example` |
| ② Python 11 个核心依赖 | **FAIL** | 直接退出，提示 `pip install -r requirements.txt` |
| ③ MySQL 连接 (`localhost:3306`) | WARN | 业务功能会失败，提示排查 MySQL |
| ④ 数据库初始化 (`risk_rule` 表) | WARN | 提示跑 `python scripts/init_db.py --yes` |
| ⑤ 8000 端口 | WARN | 提示杀进程 / 改 `APP_PORT` |
| ⑥ XGBoost 模型文件 | WARN | 业务仍能跑（纯规则），提示训练 |

**真实环境跑通示例**：
```
============================================================
【启动前自检】 (P4-L4 2026-08-08)
============================================================
  [OK] .env           .env 存在
  [OK] Python 依赖      所有 11 个核心依赖已装
  [OK] MySQL 连接       MySQL root@ecs 可连
  [OK] 数据库初始化         数据库已初始化, risk_rule 有 24 条规则
  [OK] 端口 8000        端口 8000 空闲
  [OK] XGBoost 模型     XGBoost 模型已加载 (317.1 KB)
============================================================
汇总: 6 OK / 0 WARN / 0 FAIL
一切就绪, 启动 uvicorn...
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 6.2 直接启动（跳过自检）

```bash
python scripts/main.py
```

跳过 preflight 直接 uvicorn。生产部署时一般用 `cd docker && docker compose up -d`。

启动成功会看到：
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

**访问入口**：
| URL | 用途 |
|---|---|
| http://localhost:8000/ | 仪表盘 |
| http://localhost:8000/docs | Swagger API 文档 |
| http://localhost:8000/api/agent/chat | AI 对话（流式） |
| http://localhost:8000/api/risk/check | 实时风控检查（POST） |
| http://localhost:8000/api/alerts/check | 手动触发告警（POST） |

**测试一个风控检查**：
```bash
curl -X POST http://localhost:8000/api/risk/check \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "下单",
    "source_id": "ORD_TEST_001",
    "user_id": "1001",
    "order_id": "ORD_TEST_001"
  }'
```

---

## 7. 跑测试

```bash
# 全部 329 个 (~30 秒, 含 15 个校验去重 + 14 个黑名单 4 action 回归)
pytest tests/

# 详细输出
pytest tests/ -v

# 某个具体测试
pytest tests/test_risk_decision.py -v

# 端到端 DDL 同步检查（需真实 DB）
DDL_CHECK_ENABLED=1 pytest tests/test_ddl_sync.py -v
```

---

## 8. 生产部署 (Docker)

> **P4-L4 2026-08-08 整理**: Docker 相关文件全部移到 `docker/` 子目录（含 `Dockerfile` + `docker-compose.yml` + `nginx.conf` + `.env.example` + `.dockerignore` + `README.md`）。从项目根跑 `cd docker && docker compose up -d` 启动。

### 8.1 一键启动 (推荐)

```bash
# 1. 复制环境变量模板 (在 docker/ 目录下)
cd docker
cp .env.example .env
# 编辑 .env, 改 MYSQL_ROOT_PASSWORD + LLM_API_KEY
# 编辑 .env, 填 LLM_API_KEY (阿里云百炼) 等

# 2. 启动 (MySQL + FastAPI app + Nginx, 3 个容器)
docker compose up -d

# 3. 查看启动日志
docker compose logs -f app

# 4. 跑数据初始化 (首次部署)
docker compose exec app python scripts/init_db.py --yes

# 5. 灌业务数据 + 训练 XGBoost
docker compose exec app python scripts/gen_10w_data.py
docker compose exec app python scripts/gen_risk_data_with_dates.py --days 7 --per-day 20
docker compose exec app python scripts/train_xgb_model.py
# 训练日志会显示 [特征重要性 TOP 10] — 业务含义清楚

# 6. 访问
# http://localhost               ← Nginx 80 → app 8000
# http://localhost/docs           ← Swagger API
```

### 8.2 架构

```
┌─ Nginx (80/443) ─┐
│  反代 + 静态文件 │
└────────┬─────────┘
         ↓
┌─ FastAPI app (gunicorn 4 workers) ─────┐
│  lifespan: lifespan 启/停后台调度器     │
│  • 案件超时自动关闭 (24h)              │
│  • 告警自动检查 (15 分钟)               │
│  • XGBoost 自动加载 + 双轨融合          │
└────────┬─────────────────────────────────┘
         ↓
┌─ MySQL 8.0 (utf8mb4) ───────────────────┐
│  26 张表 (17 业务 + 9 风控)            │
│  init SQL 自动跑 (entrypoint-initdb.d)   │
└────────────────────────────────────────┘
```

### 8.3 关键配置 (.env)

```env
# 调度 (P4-L3)
CASE_TIMEOUT_HOURS=24            # 待审案件超 24h 自动关
ALERT_SCHEDULER_INTERVAL_MIN=15   # 告警检查 15 分钟一次 (0 = 关闭)

# 阿里云百炼 LLM
LLM_API_KEY=sk-xxxxxxxxxxxxxxxx  # 必填, 否则 Agent 功能降级
```

### 8.4 老环境升级 (已部署过)

```bash
# 不重置数据, 只补字段 + ENUM 扩展
docker compose exec app python scripts/migrate_2026_08_07.py
# 会自动补 6 字段 + 1 索引 + 1 ENUM (AUTO_REJECT_CASE / AUTO_CLOSE_CASE), 幂等
```

### 8.5 不用 Docker 的传统部署

```bash
# 1. 系统装 Python 3.11 + MySQL 8.0
# 2. 创建数据库 + 跑 init SQL
mysql -u root -p < sql/init_all.sql

# 3. pip install
pip install -r requirements.txt

# 4. gunicorn 启动 (4 workers)
gunicorn scripts.main:app \
    -w 4 -k uvicorn.workers.UvicornWorker \
    -b 0.0.0.0:8000 \
    --timeout 120

# 5. 配 systemd (开机自启)
# /etc/systemd/system/ai-risk.service
[Unit]
Description=AI Risk System
After=network.target mysql.service

[Service]
Type=simple
User=app
WorkingDirectory=/opt/ai-risk
ExecStart=/usr/local/bin/gunicorn scripts.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 9. 日志管理

> **P4-L4 2026-08-08 新增**：`app/logging_config.py` 统一配置，业务 logger + uvicorn 全部走 stdout + `logs/app.log`，50 MB 自动轮转保留 5 份。

### 9.1 日志输出到哪？

启动后所有日志都同时进 **2 个地方**：

| 输出目标 | 路径 | 适用场景 |
|---|---|---|
| **stdout** | 终端 / 容器 | 开发实时看，Docker 自动捕获 |
| **logs/app.log** | `项目根/logs/app.log` | 事后排查、历史归档、文件已自动轮转 |

包含的 logger：
- 业务 logger（`app.engine.decision` / `app.service.case` / `app.scheduler` 等 14 个文件）
- `uvicorn.access`（每个 HTTP 请求一行）
- `uvicorn.error`（应用异常 traceback）

### 9.2 日志轮转

`logs/app.log` 用 `RotatingFileHandler`：

```python
MAX_BYTES = 50 * 1024 * 1024  # 50 MB
BACKUP_COUNT = 5              # 保留 app.log.1 ~ app.log.5
```

满 50 MB 自动重命名成 `app.log.1`，下次写进新的 `app.log`，超过 5 份的最旧被删。**最多占 250 MB**。

### 9.3 怎么用？

```python
# 业务代码里
import logging
logger = logging.getLogger(__name__)
logger.info("正常信息")
logger.warning("警告")
logger.exception("异常, 自动带 traceback")
```

启动服务时已经自动配好：
- `python _run.py` → 用 `app/logging_config.py::LOGGING_CONFIG` 启动 uvicorn
- 容器化部署 → 同样的配置，stdout 进 Docker 日志 + 容器内 `logs/app.log` 持久化

### 9.4 看日志

```bash
# PowerShell (Windows)
Get-Content logs/app.log -Tail 50 -Wait

# Linux / Mac
tail -f logs/app.log

# 看最新一个 HTTP 请求
grep "uvicorn.access" logs/app.log | tail -1

# 看 ERROR
grep "ERROR" logs/app.log
```

### 9.5 想看更多配置？

```bash
python app/logging_config.py    # demo 脚本, 打印完整配置
```

## 10. 常见问题 FAQ

### Q1: 启动报 "ModuleNotFoundError: No module named 'app'"

**A**: 在项目根目录运行，或先 `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`。

### Q2: 启动报 "aiomysql 跨 event loop 时 Event loop is closed"

**A**: `database.py::get_db_async` 已经处理（显式 `try/finally + 显式 close`）。如果还遇到，重启服务。

### Q3: XGBoost 加载失败 / 模型没训练

**A**: 看 `app/engine/ml_model.py` 的 `_schedule_load()`。如果 `xgb_model.json` 不存在，自动走纯规则（不影响业务）。要训练跑 `python scripts/train_xgb_model.py`。

### Q4: 训练时报 "没有评估数据, 先跑几次 /api/risk/check"

**A**: 先造评估数据：
```bash
python scripts/gen_risk_data.py --count 200
# 或加 --balance-pos 让正例占比 20%+, 训练效果更好
python scripts/gen_risk_data.py --count 200 --balance-pos
python scripts/train_xgb_model.py
```

### Q5: 训练样本不足 50 条

**A**: 多造数据（业务表 + 评估数据），最少 50 条建议 200+ 条才有意义。
**P4-L3 2026-08-08**：< 1250 条时 `ml_model.py` 会打 WARNING，**不阻断**训练（教学允许小样本试跑），但生产前必须积累到 1250+（25 维 × 50 倍经验值）。

### Q6: 数据库中文乱码

**A**: 必须 utf8mb4 字符集。`init_db.py` 已加 `CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci`。如果是老库，需要 ALTER TABLE 转码。

### Q7: AI Agent 报 LLM 错误

**A**:
- 检查 `.env` 的 `LLM_API_KEY` 是否正确
- 阿里云百炼需要 OpenAI 兼容接口：`LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- Qwen-Plus 4 元/百万 token（输入/输出分别算）

### Q8: 端口 8000 被占

**A**: 改 `scripts/main.py`：
```python
uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
```

### Q9: 软删字段对业务影响

**A**: 软删后 `is_enabled=0` + `deleted_at=NOW()`，规则匹配 / 黑名单检查 / 列表查询都加 `WHERE deleted_at IS NULL`。业务看不到软删的记录。审计日志 (P4-L1) 永久保留。

### Q10: 告警 (P4-L2) 配置

**A**: 在 `.env`：
```ini
ALERT_PENDING_CASE_THRESHOLD=50       # 待审核积压告警阈值
ALERT_RULE_HIT_RATE_MIN=5.0            # 命中率下限 (%)
ALERT_BLACKLIST_HIT_RATE_MAX=30.0      # 撞黑率上限 (%)
ALERT_CHECK_WINDOW_HOURS=1             # 时间窗口 (小时)
```

### Q11: 案件状态机流转错误

**A**: 状态机白名单在 `app/service/case.py::_ALLOWED_CASE_TRANSITIONS`：
```
待审核 → 审核中 / 已通过 / 已拒绝 / 已关闭
审核中 → 已通过 / 已拒绝 / 已关闭
已通过 / 已拒绝 / 已关闭 → 终态
```

### Q12: 我改了 `app/engine/feature.py` 加新特征，怎么让 XGBoost 用上？

**A**:
1. 在 `compute_*_features` 的 dict 里加新 key
2. 在 `app/engine/ml_model.py::FEATURE_COLUMNS` 列表里加同名字符串
3. **重训**：`python scripts/train_xgb_model.py`
4. **改测试**：确保 `tests/test_xgboost.py::test_feature_columns_align` 通过
5. 启动服务，验证 `is_model_loaded() = True`

---

## 11. 一句话总结

```bash
# 启动一个新项目
pip install -r requirements.txt
python scripts/init_db.py
python scripts/gen_10w_data.py
python scripts/train_xgb_model.py
python scripts/main.py
# → http://localhost:8000
```

**目录速记**：
- 代码：`app/` (5 层架构)
- 脚本：`scripts/` (8 个脚本, 含 gen_10w_data / gen_risk_data_with_dates / migrate_2026_08_07)
- DDL/SQL：`sql/` (6 个 DDL + 3 个 migration)
- 文档：`docs/` (含 11 份教学 md, 新增 `agent_design.md` 介绍 8 @tool 设计)
- 测试：`tests/` (329 cases, 含 P4-L3 案件超时关闭 + XGBoost 特征重要性 + XGBoost 训练优化 4 个 + XGBoost 训练质量验收 6 个 (假收敛检测 + 最佳 F1 阈值) + P4-L4 统一日志 13 个 + 一键启动 preflight 16 个 + scheduler bug 回归 1 个 + 通用分页 9 个 + 左侧固定布局 10 个 (含分页栏粘底 2 个 + 分页按钮文字可见 1 个) + train 脚本解包顺序回归 1 个 + RISK 用户参数化生成 8 个 + 训练数据校验 6 个 (条数/pos 比例/时间跨度) + 训练数据生成器正例控制 12 个 (`--balance-pos` / `--target-pos-ratio` / `--live` / `--force-pos-ratio` 参数 + 正例统计 + 比例提示 + day_offset 循环回归 + 3 个高风险 picker + retry 机制 + 脚本 emoji GBK 修复 + decision_hit 引用清理) + 前端 ML 评分 sigmoid 校准 21 个 + 一条龙命令 13 个 + 教学场景训练 11 个 + 训练数据严格化 15 个 + sigmoid 校准 15 个 + ML 风险检查页 7 个 + 物流投诉 picker bug 修复 4 个 + P4-L5 校验去重 15 个 (死代码删除 + 决策引擎重复调用清理) + P4-L5 黑名单 4 action 14 个 (manage_blacklist 字典派发按 action 动态传参 + 移除走 case.remove_blacklist 软删 + 边界签名锁定))
- 部署：`docker/` (P4-L4 2026-08-08, 含 Dockerfile + docker-compose.yml + nginx.conf + .env.example + README)
- 环境管理：`uv/` (P4-L4 2026-08-08, 含 pyproject.toml + requirements-uv.txt + uv.lock + README)
- 部署：`Dockerfile` + `docker-compose.yml` + `nginx.conf` (P4-L3 一键启动)
