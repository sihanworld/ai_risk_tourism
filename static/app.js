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

