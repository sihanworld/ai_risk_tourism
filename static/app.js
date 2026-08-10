/**
 * 电商风控系统 - 公共前端工具函数
 */

// 风险等级对应的Badge类名
function getRiskBadgeClass(level) {
    const map = {
        '低': 'badge-risk-low',
        '中': 'badge-risk-mid',
        '高': 'badge-risk-high',
        '极高': 'badge-risk-critical',
    };
    return map[level] || 'bg-secondary';
}

// 通用API请求封装
async function apiRequest(url, options = {}) {
    const defaultOptions = {
        headers: { 'Content-Type': 'application/json' },
    };
    const res = await fetch(url, { ...defaultOptions, ...options });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '请求失败' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
}

/**
 * ML P(拒绝) → 0-100 风险分 (sigmoid 风格校准, 跟 Python 端 _ml_prob_to_risk_score 一致).
 *
 * 【P4-L4 2026-08-08】前端显示统一: 0-100 风险分而不是 0-1 概率, 跟规则分语义一致.
 * 公式: risk_score = 100 * (1 - exp(-k * prob)), k=3
 * 校准点: 0.0→0, 0.1→26, 0.3→59, 0.5→78, 0.7→90, 0.9→97, 1.0→100
 */
function mlProbToRiskScore(prob, k = 3) {
    if (prob == null || isNaN(prob)) return null;
    if (prob <= 0) return 0;
    if (prob >= 1) return 100;
    return Math.round(100 * (1 - Math.exp(-k * prob)));
}

/**
 * 渲染 ML 评分 HTML 片段 (P(拒绝) + 风险分(sigmoid 校准) + ML 决策).
 * 用于风险检查/案件详情/评估历史 三个页面的统一展示.
 */
function renderMLScoreBlock(mlScore, mlDecision) {
    if (mlScore == null) {
        return '<span class="text-muted">未加载模型</span>';
    }
    const riskScore = mlProbToRiskScore(mlScore);
    const pct = (mlScore * 100).toFixed(2);
    const raw = mlScore.toFixed(4);
    const decision = mlDecision
        ? `<span class="badge bg-info">${mlDecision}</span>`
        : '<span class="text-muted">-</span>';
    return `
        P(拒绝): <strong>${pct}%</strong> <small class="text-muted">(${raw})</small><br>
        风险分 (sigmoid 校准): <strong>${riskScore}</strong> <small class="text-muted">/ 100</small><br>
        ML 决策: ${decision}
    `;
}

/**
 * 通用分页 HTML 生成器 (P4-L4 2026-08-08)
 *
 * 设计:
 *   - 最多同时显示 10 个页码 (含 首页/末页 + 上下页 + 省略号)
 *   - 中间用 `...` 占位, 点击跳 ±5 页 (避免点击无意义)
 *   - 末页用 `>>` 单独跳到最后一页 (兼容用户提到的 `>>>` 风格)
 *   - 兼容 totalPages <= 7: 直接显示所有页码, 不省略
 *
 * 参数:
 *   currentPage: 当前页 (1-based)
 *   totalPages: 总页数
 *   pageSize: 每页条数 (用于显示 "X 条/页" 信息)
 *   loadFnName: 加载函数名字符串 (例如 'loadAssessments' / 'loadCases')
 *   containerId: 分页 ul 元素的 id (默认 'pagination')
 *
 * 返回: HTML 字符串, 直接 innerHTML 到 ul 容器即可
 */
function buildPaginationHtml(currentPage, totalPages, pageSize, loadFnName, containerId = 'pagination') {
    if (totalPages < 1) {
        // 【P4-L4 2026-08-08v2】无数据也渲染"暂无数据"占位条, 避免底栏空白让用户以为出 bug
        return '<li class="page-item disabled"><span class="page-link text-muted" style="cursor:default;">暂无数据</span></li>';
    }
    // totalPages >= 1 都渲染 (包括 =1, 占位"上一页 1 下一页"让用户看到分页栏在工作, 不显空白)

    const html = [];
    const addItem = (label, page, opts = {}) => {
        const { active = false, disabled = false, isEllipsis = false } = opts;
        if (disabled) {
            html.push(`<li class="page-item disabled"><span class="page-link">${label}</span></li>`);
        } else if (isEllipsis) {
            // 省略号: 点击跳 ±5 页 (避免点无意义)
            const jumpTo = page;
            html.push(
                `<li class="page-item"><a class="page-link" href="#" `
                + `onclick="${loadFnName}(${jumpTo});return false;" `
                + `title="跳到第 ${jumpTo} 页" style="cursor:pointer;">...</a></li>`
            );
        } else {
            html.push(
                `<li class="page-item ${active ? 'active' : ''}">`
                + `<a class="page-link" href="#" onclick="${loadFnName}(${page});return false;">${label}</a></li>`
            );
        }
    };

    // 上一页 (单字符紧凑版, P4-L4 2026-08-08 第二轮)
    addItem('«', currentPage - 1, { disabled: currentPage <= 1 });

    // 总页数 <= 7, 直接全显示
    if (totalPages <= 7) {
        for (let i = 1; i <= totalPages; i++) {
            addItem(String(i), i, { active: i === currentPage });
        }
    } else {
        // 总页数 > 7, 用 ... 省略号
        // 总是显示首页
        addItem('1', 1, { active: currentPage === 1 });

        // 左边省略号: 当前页 > 4 时显示 (跳到 currentPage-3)
        if (currentPage > 4) {
            addItem('...', Math.max(2, currentPage - 3), { isEllipsis: true });
        }

        // 中间页码: max(2, currentPage-2) ... min(totalPages-1, currentPage+2)
        const start = Math.max(2, currentPage - 2);
        const end = Math.min(totalPages - 1, currentPage + 2);
        for (let i = start; i <= end; i++) {
            addItem(String(i), i, { active: i === currentPage });
        }

        // 右边省略号: 当前页 < totalPages-3 时显示 (跳到 currentPage+3)
        if (currentPage < totalPages - 3) {
            addItem('...', Math.min(totalPages - 1, currentPage + 3), { isEllipsis: true });
        }

        // 末页 (总是显示)
        addItem(String(totalPages), totalPages, { active: currentPage === totalPages });
    }

    // 下一页 (单字符紧凑版)
    addItem('»', currentPage + 1, { disabled: currentPage >= totalPages });

    // 末页快捷跳: 只有在 totalPages > 10 才显示 (单字符, 不再双 »»)
    if (totalPages > 10 && currentPage < totalPages) {
        html.push(
            `<li class="page-item">`
            + `<a class="page-link" href="#" onclick="${loadFnName}(${totalPages});return false;" `
            + `title="跳到末页 (第 ${totalPages} 页)" style="cursor:pointer;">››</a></li>`
        );
    }

    return html.join('');
}


/* ============================================================
 * 规则条件构建器 (P4-L5 2026-08-10):
 *   - 26 个特征 key ↔ 中文标签映射 (FEATURE_LABELS)
 *   - 风险等级 ↔ 分数区间 (RISK_LEVEL_SCORE_MAP, 跟后端 config.py 一致)
 *   - 按 event_type 拆的阈值 (RISK_EVENT_THRESHOLDS)
 *   - 可视化构建器: buildConditionUI / collectCondition / parseCondition
 *   - 双向: UI ↔ JSON 互相转换
 * ============================================================ */

// 1. 26 特征 key↔中文标签 (跟 ml_model.py FEATURE_COLUMNS 对齐, 中文按业务语义)
const FEATURE_LABELS = {
    // 用户画像 (14 维)
    "user_total_orders":         "用户总订单数",
    "user_orders_30d":           "用户30天订单数",
    "user_orders_7d":            "用户7天订单数",
    "user_total_amount":         "用户累计消费金额",
    "user_avg_order_amount":     "用户平均订单金额",
    "user_max_order_amount":     "用户最大单笔金额",
    "user_refund_count":         "用户退款次数",
    "user_postsale_count":       "用户售后次数",
    "user_refund_rate":          "用户退款率",
    "user_postsale_rate":        "用户售后率",
    "user_refund_amount":        "用户退款金额",
    "user_cancel_count":         "用户取消订单次数",
    "user_complaint_count":      "用户投诉次数",
    "user_address_count":        "用户使用地址数",
    // 订单画像 (8 维)
    "order_total_amount":        "订单总金额",
    "order_item_count":          "订单商品件数",
    "order_sku_count":           "订单SKU种类数",
    "order_discount_amount":     "订单优惠金额",
    "order_discount_rate":       "订单折扣率",
    "order_pay_interval_sec":    "下单到支付间隔(秒)",
    "order_is_night":            "是否凌晨下单",
    "order_category_count":      "订单商品类目数",
    // 地址画像 (3 维)
    "addr_total_count":          "用户地址总数",
    "addr_province_count":       "用户地址跨省数",
    "addr_is_new":               "是否新地址",
};

// 反向: 中文标签 → key (前端下拉显示中文, 内部存 key)
const LABEL_TO_FEATURE = Object.fromEntries(
    Object.entries(FEATURE_LABELS).map(([k, v]) => [v, k])
);

// 2. 风险等级 ↔ 分数区间 (跟后端 config.py RISK_LEVEL_SCORE_MAP 一致)
const RISK_LEVEL_SCORE_MAP = {
    "低":   [0, 29],
    "中":   [30, 59],
    "高":   [60, 84],
    "极高": [85, 100],
};

// 3. 按 event_type 拆的阈值 (跟后端 config.py RISK_EVENT_THRESHOLDS 一致)
const RISK_EVENT_THRESHOLDS = {
    "下单":     {pass: 30, mark: 60, review: 80},
    "支付":     {pass: 25, mark: 55, review: 75},
    "售后申请":  {pass: 40, mark: 70, review: 85},
    "物流投诉":  {pass: 35, mark: 65, review: 80},
    "通用":     {pass: 30, mark: 60, review: 80},
};

// 4. 支持的运算符
const OPERATORS = [
    {value: "",        label: "(任意, 仅作为占位条件)"},
    {value: ">",       label: "> 大于"},
    {value: ">=",      label: ">= 大于等于"},
    {value: "<",       label: "< 小于"},
    {value: "<=",      label: "<= 小于等于"},
    {value: "==",      label: "== 等于"},
    {value: "!=",      label: "!= 不等于"},
    {value: "in",      label: "in 包含 (数组)"},
    {value: "not_in",  label: "not_in 不包含 (数组)"},
    {value: "between", label: "between 区间 [min, max]"},
];

// 5. 风险等级 (跟后端 risk_level enum 对齐)
const RISK_LEVELS = ["低", "中", "高", "极高"];

/* === 核心 API === */

// 把 JSON 条件渲染成可视化 UI (递归, 跟 JSON 树一一对应)
function buildConditionUI(cond, containerId) {
    const c = document.getElementById(containerId);
    if (!c) { console.error('buildConditionUI: container not found', containerId); return; }
    c.innerHTML = '';
    if (!cond || typeof cond !== 'object') cond = {and: []};
    try {
        renderCondNode(cond, c, true);
        // [P4-L5 2026-08-10 调试] render 完再 console 一行
        console.log('[buildConditionUI] OK, children=', c.children.length);
    } catch (e) {
        console.error('renderCondNode throw', e, 'cond=', cond);
        c.innerHTML = '<pre style="color:red;font-size:11px;">' + (e && e.message || e) + '\n\n' + (e && e.stack || '') + '</pre>';
    }
}

// 递归渲染 1 个条件节点 (单条件 或 and/or 组合)
function renderCondNode(cond, parent, isRoot) {
    if (cond && (cond.and || cond.or)) {
        // 组合: and/or
        const op = cond.and ? 'and' : 'or';
        const wrap = document.createElement('div');
        wrap.className = 'cond-group mb-2 p-2 border rounded';
        wrap.style.background = op === 'and' ? '#f0f9ff' : '#fef3c7';

        // 顶部: 组合操作符下拉 + 删除按钮
        const head = document.createElement('div');
        head.className = 'd-flex align-items-center mb-2';
        head.innerHTML = `
            <select class="form-select form-select-sm w-auto me-2 cond-op-select">
                <option value="and" ${op === 'and' ? 'selected' : ''}>全部满足 (AND)</option>
                <option value="or" ${op === 'or' ? 'selected' : ''}>任一满足 (OR)</option>
            </select>
            <button type="button" class="btn btn-sm btn-outline-danger ms-auto cond-del-group">删除分组</button>
        `;
        // op 切换: and ↔ or
        head.querySelector('.cond-op-select').addEventListener('change', e => {
            const newOp = e.target.value;
            if (newOp === 'and') {
                cond.or = cond.and; delete cond.and;
            } else {
                cond.and = cond.or; delete cond.or;
            }
        });
        // 删分组
        head.querySelector('.cond-del-group').addEventListener('click', () => {
            // 把这个分组替换成 [] (空 and), 父级需要重新渲染
            // 简化: 直接移除
            wrap.remove();
        });
        wrap.appendChild(head);

        // 递归渲染子条件
        const children = op === 'and' ? cond.and : cond.or;
        const childBox = document.createElement('div');
        childBox.className = 'cond-children';
        children.forEach(child => renderCondNode(child, childBox, false));
        wrap.appendChild(childBox);

        // 底部: +条件 / +分组 按钮
        // [P4-L5 2026-08-10] + 条件一次加 3 个空条件框 (用户填完删, 不用一次一次点),
        // 减少点击次数. 不填的留空也行, saveRule 跳过空 op='' 的 leaf.
        const footer = document.createElement('div');
        footer.className = 'mt-2';
        footer.innerHTML = `
            <button type="button" class="btn btn-sm btn-outline-primary me-1 cond-add-leaf">+ 条件 (一次 3 个)</button>
            <button type="button" class="btn btn-sm btn-outline-secondary cond-add-group">+ 分组 (${op === 'and' ? 'AND' : 'OR'})</button>
        `;
        footer.querySelector('.cond-add-leaf').addEventListener('click', () => {
            for (let i = 0; i < 3; i++) {
                children.push({field: 'user_total_orders', op: '>=', value: 0});
            }
            buildConditionUI(collectCondition(parent), parent.id);
        });
        footer.querySelector('.cond-add-group').addEventListener('click', () => {
            // [P4-L5 2026-08-10] + 分组默认带 1 个 AND 子组 (嵌套场景), 用户可继续往里加
            children.push({and: [{field: 'user_total_orders', op: '>=', value: 0}]});
            buildConditionUI(collectCondition(parent), parent.id);
        });
        wrap.appendChild(footer);

        parent.appendChild(wrap);
    } else {
        // [P4-L5 2026-08-10] 单条件改用 CSS Grid 4 列布局, 不再 d-flex, 解决:
        //   1) 窄 modal 下 op 下拉被压窄 (160px minWidth 在 d-flex 不够稳)
        //   2) value 框被挤看不到完整 placeholder
        //   3) 移动端/小屏下 4 个控件挤一行难看
        // 4 列: 字段(2fr) / op(1fr) / value(2fr) / 操作(60px), value 列宽固定不缩
        const row = document.createElement('div');
        row.className = 'cond-leaf mb-2 p-2 border rounded';
        row.style.background = '#f9fafb';
        row.style.display = 'grid';
        row.style.gridTemplateColumns = 'minmax(220px, 2fr) minmax(140px, 1fr) minmax(220px, 2fr) 60px';
        row.style.gap = '8px';
        row.style.alignItems = 'center';

        // 字段下拉 (中文标签)
        const fieldSel = document.createElement('select');
        fieldSel.className = 'form-select form-select-sm cond-field';
        Object.entries(FEATURE_LABELS).forEach(([key, label]) => {
            const opt = document.createElement('option');
            opt.value = key;
            opt.textContent = label + ` (${key})`;
            if (cond.field === key) opt.selected = true;
            fieldSel.appendChild(opt);
        });
        fieldSel.addEventListener('change', e => { cond.field = e.target.value; });

        // 运算符下拉
        const opSel = document.createElement('select');
        opSel.className = 'form-select form-select-sm cond-op';
        OPERATORS.forEach(({value, label}) => {
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = label;
            if (cond.op === value) opt.selected = true;
            opSel.appendChild(opt);
        });
        opSel.addEventListener('change', e => {
            cond.op = e.target.value;
            // between 切到 2 个输入框
            updateValueInput(row, cond);
        });

        // 值输入 (随 op 联动)
        const valBox = document.createElement('div');
        valBox.className = 'cond-val-box';
        row.appendChild(fieldSel);
        row.appendChild(opSel);
        row.appendChild(valBox);
        updateValueInput(row, cond);

        // 删除
        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'btn btn-sm btn-outline-danger cond-del-leaf';
        delBtn.textContent = '×';
        delBtn.addEventListener('click', () => row.remove());
        row.appendChild(delBtn);

        parent.appendChild(row);
    }
}

// 值输入框随 op 联动 (in/not_in 数组, between 区间, 其他单值)
function updateValueInput(row, cond) {
    const box = row.querySelector('.cond-val-box');
    if (!box) return;
    box.innerHTML = '';
    const op = cond.op;

    if (op === 'between') {
        // [min, max] 2 个输入框
        let arr = Array.isArray(cond.value) ? cond.value : [0, 100];
        const wrap = document.createElement('div');
        wrap.className = 'd-flex align-items-center';
        wrap.innerHTML = `
            <input type="number" step="any" class="form-control form-control-sm me-1 cond-v-between-low" style="width:80px" value="${arr[0]}">
            <span class="me-1">~</span>
            <input type="number" step="any" class="form-control form-control-sm cond-v-between-high" style="width:80px" value="${arr[1]}">
        `;
        wrap.querySelector('.cond-v-between-low').addEventListener('input', e => {
            if (!Array.isArray(cond.value)) cond.value = [0, 100];
            cond.value[0] = parseFloat(e.target.value) || 0;
        });
        wrap.querySelector('.cond-v-between-high').addEventListener('input', e => {
            if (!Array.isArray(cond.value)) cond.value = [0, 100];
            cond.value[1] = parseFloat(e.target.value) || 100;
        });
        box.appendChild(wrap);
    } else if (op === 'in' || op === 'not_in') {
        // 数组, 逗号分隔
        const arrStr = Array.isArray(cond.value) ? cond.value.join(',') : (cond.value || '');
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.className = 'form-control form-control-sm cond-v-arr';
        inp.placeholder = '逗号分隔, 如: 1,2,3';
        inp.value = arrStr;
        inp.addEventListener('input', e => {
            cond.value = e.target.value.split(',').map(s => s.trim()).filter(Boolean);
        });
        box.appendChild(inp);
    } else if (op === 'in' || op === 'not_in' || op === '') {
        // 占位 op 不需要 value
        box.innerHTML = '<small class="text-muted">无 value</small>';
    } else {
        // 单值 (数字或字符串, 默认数字)
        const inp = document.createElement('input');
        inp.type = 'number';
        inp.step = 'any';
        inp.className = 'form-control form-control-sm cond-v-single';
        inp.value = cond.value ?? 0;
        inp.addEventListener('input', e => {
            cond.value = parseFloat(e.target.value) || 0;
        });
        box.appendChild(inp);
    }
}

// 从 UI 容器收集当前 JSON 条件
function collectCondition(container) {
    // 容器只有一个根节点 (group 或 leaf)
    const root = container.children[0];
    if (!root) return {and: []};
    return extractNode(root);
}

// [P4-L5 2026-08-10] 递归去掉未填的 leaf (op === '' 表示用户没改这个占位条件),
// 防止默认 3 个空条件框被原样存进数据库. 保留有内容的 leaf 和 group 结构.
function stripEmptyLeaves(node) {
    if (!node || typeof node !== 'object') return node;
    if (node.and) {
        const children = (node.and || []).map(stripEmptyLeaves).filter(c => c !== null);
        return children.length > 0 ? {and: children} : null;
    }
    if (node.or) {
        const children = (node.or || []).map(stripEmptyLeaves).filter(c => c !== null);
        return children.length > 0 ? {or: children} : null;
    }
    // leaf: op === '' 视为未填, 去掉
    if (node.op === '' || node.op === undefined || node.op === null) {
        return null;
    }
    return node;
}

function extractNode(node) {
    if (node.classList.contains('cond-group')) {
        const op = node.querySelector('.cond-op-select').value;
        const children = [];
        node.querySelectorAll('.cond-children > *').forEach(child => {
            children.push(extractNode(child));
        });
        return op === 'and' ? {and: children} : {or: children};
    } else if (node.classList.contains('cond-leaf')) {
        const field = node.querySelector('.cond-field').value;
        const op = node.querySelector('.cond-op').value;
        // 值: 从不同输入框读
        const between = node.querySelector('.cond-v-between-low');
        const arr = node.querySelector('.cond-v-arr');
        const single = node.querySelector('.cond-v-single');
        let value = 0;
        if (between) {
            value = [
                parseFloat(node.querySelector('.cond-v-between-low').value) || 0,
                parseFloat(node.querySelector('.cond-v-between-high').value) || 0,
            ];
        } else if (arr) {
            value = arr.value.split(',').map(s => s.trim()).filter(Boolean);
        } else if (single) {
            value = parseFloat(single.value) || 0;
        }
        if (op === '') {
            // 占位条件: 只返 field
            return {field};
        }
        return {field, op, value};
    }
    return {and: []};
}

// 工具: 根据分数反查风险等级 (前端用, 跟后端 settings.get_risk_level_by_score 对齐)
function getRiskLevelByScore(score) {
    for (const [level, [low, high]] of Object.entries(RISK_LEVEL_SCORE_MAP)) {
        if (score >= low && score <= high) return level;
    }
    return score > 100 ? '极高' : '低';
}

// 工具: 根据 event_type 查阈值
function getEventThresholds(eventType) {
    return RISK_EVENT_THRESHOLDS[eventType] || RISK_EVENT_THRESHOLDS['通用'];
}

// 工具: 校验 risk_score 是否在 risk_level 区间内
function validateScoreLevel(level, score) {
    if (!RISK_LEVEL_SCORE_MAP[level]) {
        return {ok: false, msg: `未知风险等级: ${level}`};
    }
    if (typeof score !== 'number' || score < 0 || score > 100) {
        return {ok: false, msg: `risk_score 必须是 0-100 数字, 当前 ${score}`};
    }
    const [low, high] = RISK_LEVEL_SCORE_MAP[level];
    if (score < low || score > high) {
        return {ok: false, msg: `${level} 等级分数应在 [${low}, ${high}], 当前 ${score} 越界`};
    }
    return {ok: true};
}
