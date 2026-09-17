# 主线分析：互斥分桶与 "20%" 论证

> 交付：`analysis.py` → `out/analysis.json`，喂 dashboard 三块 tile 和 `claims.json`。
> 所有数字已在本机跑通（`scripts/spine_check.py`），实现时对上即算完成。

## 0. 一句话结论（CFO 记这一句）

> **20% 的削减目标，只需要动那些 GPU 峰值都没超过 20% 的 job 就能达到——一个正在真干活的任务都不用碰。**

- 集群总量 **594,004 GPU-h**，20% = **118,801 GPU-h = $297,002**（$2.5/GPU-h，`/v1/price-book`）
- 可回收（A + B₁）= **123,480 GPU-h = 20.8% = $308,700**

## 1. 为什么要自己分桶，而不是把 findings 的 `impact_gpu_hours` 加起来

`docs/traps.md` 明说：23 条规则跑在同一份遥测上，一个 job 会触发多条；`impact_gpu_hours` 朴素求和 = 931,607 GPU-h，是集群总量的 157%。另外 `impact_kind`（lost / consumed / unused_capacity / degraded）和 `impact_scope`（job / node / user）不能跨类相加。

所以我们**不加 findings**。我们以 `jobs.parquet` 为准，**每个 job 恰好进一个桶**，桶的总和恒等于 594,004。findings 只用来做 drill-down（点开一个桶 → 这些 job 触发了哪些规则）。

## 2. 分桶定义（精确谓词，按顺序判定，先中先得）

数据源：`data/prepped/jobs.parquet`，一行一个 job。用到的列：
`gpu_hours`（**measured**，DCGM 实测；不要用 `gpu_hours_alloc`）、`sm_util_avg`、`sm_util_max`、`state_name`、`job_type`、`walltime_sec`、`gpu_count`、`id_user`、`id_job`。

```python
never  = (j.sm_util_avg == 0) & (j.sm_util_max == 0)            # A
b1     = ~never & (j.sm_util_avg < 5) & (j.sm_util_max <= 20)    # B1
b2     = ~never & (j.sm_util_avg < 5) & (j.sm_util_max >  20)    # B2
c      = ~never & (j.sm_util_avg >= 5) & (j.sm_util_avg < 20)    # C
d      = (j.sm_util_avg >= 20)                                    # D
assert (never.astype(int)+b1+b2+c+d == 1).all()                  # 互斥且完备
```

| 桶 | 含义 | jobs | GPU-h | 占比 | $ | 置信度 / 动作 |
|---|---|---|---|---|---|---|
| **A 从未计算** | 平均和峰值 SM 都是 0，物理上没跑过一个 kernel | 19,887 | **97,196** | 16.4% | $242,991 | **高** — 可回收 |
| **B₁ 低占用、真没算** | 平均 <5%，峰值 ≤20% | 9,978−4,530 = 5,448 | **26,284** | 4.4% | $65,710 | **中高** — 可回收 |
| B₂ 低占用、但算过 | 平均 <5%，峰值 >20%：真在算，只是占空比低 | 4,530 | 59,084 | 9.9% | $147,711 | **低** — 这是**误杀风险**，进 Tile 3 |
| C 5–20% | | 11,059 | 68,609 | 11.6% | | 别碰 |
| D ≥20% 真干活 | | 33,925 | 342,830 | 57.7% | | 研究在这儿，别碰 |
| 合计 | | 74,849 | 594,004 | 100% | | |

阈值为什么这么选：
- **A 用 `== 0` 而不是 `< 1`**：`rules.md` 里 `gpu-never-computed` / `gpu-not-needed` 就是 avg==0 且 max==0，"峰值到过 35% 的 job 确实算过"。用相同定义，评委能对上。
- **B 的分界用 peak 20%**：`sm_util_avg` 是 job 生命周期的均值，一个 dataloader-bound 或 通信-bound 的任务均值低但峰值高（`efficiency/summary` 的 caveat 原话）。峰值 ≤20% 说明它从没认真跑过；峰值 >20% 说明它跑过——砍它就是砍研究。这是整条论证的 **"cost of being wrong"** 支点。
- 5% 和 20% 沿用 `rules.md` 的阈值（`idle-interactive-session` 用 5%，`multi-node-low-utilization` / `node-under-utilization-slo` 用 20%），不自造数字。

## 3. A 桶按结局拆 = "Where to cut" 三条具体建议

A 桶 97,196 GPU-h 按 `state_name` 拆开，每一条对应**一个可执行的策略**，不是"提高利用率"：

| # | 结局 | jobs | GPU-h | $ | 建议动作 | 关联规则（drill-down 用） |
|---|---|---|---|---|---|---|
| 1 | CANCELLED + TIMEOUT | 2,047 + 834 | 36,101 + 30,670 = **66,771** | $166,928 | **交互会话 idle 超时**。A 桶里 1,902 个 `LLSUB:INTERACTIVE` 会话 = 32,775 GPU-h；A 桶 98% 的小时来自 walltime >4h 的 job → **4 小时阈值几乎全覆盖** | `idle-interactive-session`, `slow-cancel-of-idle-job`, `wallclock-kill` |
| 2 | COMPLETED | 4,817 | **12,301** | $30,751 | **放错队列**：任务成功了但 GPU 全程为 0，是 CPU 任务申请了 GPU → 调度到 CPU 分区 / 申请 GPU 需要理由 | `gpu-not-needed` |
| 3 | FAILED | 12,171 | **17,065** | $42,663 | **fail-fast**：起不来的 job 不该占卡。12k 个 job 中位时长 ≈ 0，绝大多数是秒挂；但少数挂着占卡的贡献了大部分小时 → 启动 N 分钟内 SM 仍为 0 即释放 | `gpu-never-computed`, `array-mass-failure` |

补充事实（写进 tile 副标题或 REPORT）：
- A 桶多卡（≥2 GPU）job：3,295 个，33,887 GPU-h —— 宽 job 空转是重灾区，一张卡空转按卡数放大。
- A 桶 GPU-h 的 57% 集中在 10 个用户 → **只说"集中度高、少数策略就能覆盖"，不排名、不点名**（traps.md：按浪费给人排名的 dashboard 会被扣分；用户 hash 也不要展示）。

## 4. `claims.json` 从这里取的字段

```jsonc
"recoverable_gpu_hours": {
  "point": 123480,          // A + B1
  "low":    97196,          // 只算 A：物理上零计算，最保守
  "high":  182564,          // A + B1 + B2：假设低占空比任务也能挪走
  "confidence": 0.7,
  "basis": "Mutually exclusive partition of jobs.parquet by (sm_util_avg, sm_util_max). Point = jobs whose GPU never exceeded 20% SM at peak (avg==0&max==0, plus 0<avg<5&max<=20). Low = only jobs with avg==0 and max==0. High adds jobs with avg<5 but max>20, which did compute at low duty cycle. gpu_hours is DCGM-measured, not gpu_count x walltime. Findings' impact_gpu_hours were NOT summed (they double count; naive sum is 157% of the cluster)."
},
"recoverable_usd": { "point": 308700, "low": 242991, "high": 456410, "confidence": 0.7 },
"cancelled_is_waste": false,
"cancelled_rationale": "Not as a category. CANCELLED is 203,930 GPU-h; we count only the 36,101 GPU-h of cancelled jobs whose GPU never computed (avg==0 & max==0) plus the B1 slice. A cancellation of a job that was computing is a user correctly killing a bad run — that is good practice, not waste, and it stays in bucket C/D."
```

`recoverable_usd` = GPU-h × 2.5。high 的 456,410 = 182,564 × 2.5。

## 5. 交付物：`out/analysis.json` 的形状

`analysis.py` 从 `data/prepped/` 读，输出一个 JSON，dashboard 只读这个文件、不重算：

```jsonc
{
  "generated_at": "...", "price_usd_per_gpu_hour": 2.5,
  "total_gpu_hours": 594004, "target_pct": 0.20, "target_gpu_hours": 118801,
  "buckets": [
    { "id": "A", "label": "从未计算", "jobs": 19887, "gpu_hours": 97196, "usd": 242991,
      "share": 0.164, "confidence": "high", "recoverable": true,
      "by_state": { "COMPLETED": {"jobs":4817,"gpu_hours":12301}, "CANCELLED": {...}, "TIMEOUT": {...}, "FAILED": {...} } },
    { "id": "B1", ... }, { "id": "B2", ..., "recoverable": false, "note": "false-positive risk" },
    { "id": "C", ... }, { "id": "D", ... }
  ],
  "recoverable": { "gpu_hours": 123480, "usd": 308700, "share": 0.208 },
  "recommendations": [
    { "id": "idle_timeout", "title": "交互会话 4h idle 超时", "gpu_hours": 66771, "usd": 166928,
      "jobs": 2881, "evidence": { "interactive_sessions": 1902, "interactive_gpu_hours": 32775,
      "share_hours_over_4h": 0.98 }, "rule_ids": ["rules::idle-interactive-session", "rules::slow-cancel-of-idle-job", "rules::wallclock-kill"] },
    { "id": "cpu_queue", ... }, { "id": "fail_fast", ... }
  ],
  "cost_if_wrong": { "b2_gpu_hours": 59084, "b2_usd": 147711, "b2_jobs": 4530,
                     "note": "jobs an avg<5% idle-kill policy would hit that DID compute (peak>20%)" }
}
```

另外把**每个桶的 job 明细**存成 `out/jobs_bucketed.parquet`（= jobs.parquet + 一列 `bucket`），dashboard 点桶 → 直接 filter 这张表显示 job_id / GPU-h / SM avg·max / state / 节点，就是 drill-down。

## 6. 复现与验收

```bash
cd MantisAi_Hackathon
docker compose run --rm prep python scripts/spine_check.py     # 打印上面所有数字
```

验收清单：
1. 五个桶 GPU-h 之和 == 594,004（±1），job 数之和 == 74,849
2. A = 97,196 / B₁ = 26,284 / B₂ = 59,084 / C = 68,609 / D = 342,830
3. A 按 state 拆：COMPLETED 12,301 / CANCELLED 36,101 / TIMEOUT 30,670 / FAILED 17,065
4. 任何一个桶都能列出具体 `id_job` 清单（drill-down 不能断）
5. 输出里**没有任何用户排名**；`id_user` 只出现在明细表里

## 7. 别踩的坑（都在 `docs/traps.md`、`docs/rules.md`，这里只列和本模块相关的）

- **`gpu_hours` 用实测的，不用 `gpu_hours_alloc`**：两者在 7% 的 job 上差 >10%，最差 19.5×（requeue 链导致）。所有美元数字都基于实测值。
- **hour-weighted，不是 row-weighted**：三分之一的 job 记录只占 0.012% 的算力。任何"平均利用率"都要按 GPU-h 加权；`df.sm_util_avg.mean()` 是错的。
- **`sm_util_avg` 是 job 内各卡的均值**：一张卡 0%、一张 65% 显示为 35%。卡间不均衡（`card_imbalance_*` 字段）要用 `gpus.parquet` 按 `gpu_id` pivot，是另一个模块，不在这里算。
- **未分配的空闲不在这份数据里**：遥测按 job 采集，没分配的卡什么都不发。我们的 594,004 是"已分配"总量，不是集群容量；dashboard 上注明 *"of allocated GPU-hours in this 4-month sample"*。
- **样本声明**：MIT 说这是子集，不能用来估整机利用率。每个集群级数字都要带"本样本、本窗口"的限定。
