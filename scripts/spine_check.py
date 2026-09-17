import pandas as pd, numpy as np
j = pd.read_parquet("data/prepped/jobs.parquet"); g = pd.read_parquet("data/prepped/gpus.parquet")
T = j.gpu_hours.sum(); P = 2.5
def row(name, m, conf):
    h = j.loc[m, "gpu_hours"].sum(); print(f"{name:<44} {m.sum():>6} jobs {h:>10,.0f} GPU-h {h/T:>6.1%}  ${h*P:>10,.0f}  [{conf}]")

print(f"TOTAL {T:,.0f} GPU-h   20% target = {0.2*T:,.0f} GPU-h = ${0.2*T*P:,.0f}\n")
# --- 互斥分桶：每个 job 只进一个桶，按"确定性"从高到低 ---
never = (j.sm_util_avg == 0) & (j.sm_util_max == 0)          # GPU 从头到尾没跑过一个 kernel
row("A  never computed (avg==0 & max==0)", never, "HIGH: 物理上没算过任何东西")
row("   ├ COMPLETED  -> 本不该要 GPU (放 CPU 队列)", never & (j.state_name=="COMPLETED"), "")
row("   ├ CANCELLED  -> 挂了/人走了", never & (j.state_name=="CANCELLED"), "")
row("   ├ TIMEOUT    -> 空转到被 wall clock 杀", never & (j.state_name=="TIMEOUT"), "")
row("   └ FAILED     -> 起不来", never & (j.state_name=="FAILED"), "")
barely = ~never & (j.sm_util_avg < 5)
row("B  barely used (0<avg<5%)", barely, "MEDIUM: 可能是 dataloader-bound")
row("   └ 其中 max>20%: 确实算过、只是占空比低", barely & (j.sm_util_max > 20), "  <- 这是 idle-kill 策略的误杀风险")
low = ~never & ~barely & (j.sm_util_avg < 20)
row("C  low (5-20%)", low, "LOW: 别碰")
row("D  working (>=20%)", ~never & ~barely & ~low, "研究在这儿，别碰")
print()
# 目标：只动 A 能不能到 20%？
hA = j.loc[never,"gpu_hours"].sum()
print(f"只回收 A 桶 = {hA/T:.1%} of cluster  ->  {'>= 20% 目标，够了' if hA/T>=0.2 else '< 20%，需要加 B 桶的一部分'}")
# A 桶里 job 有多长？（idle-timeout 策略的参数）
a = j[never]
print(f"A 桶 job 时长中位数 {a.walltime_sec.median()/3600:.1f}h, p75 {a.walltime_sec.quantile(.75)/3600:.1f}h; >4h 的占 GPU-h {a.loc[a.walltime_sec>4*3600,'gpu_hours'].sum()/hA:.0%}")
print(f"A 桶 interactive 会话: {(a.job_type=='LLSUB:INTERACTIVE').sum()} jobs, {a.loc[a.job_type=='LLSUB:INTERACTIVE','gpu_hours'].sum():,.0f} GPU-h")
print(f"A 桶多卡(>=2 GPU) job: {(a.gpu_count>=2).sum()} jobs, {a.loc[a.gpu_count>=2,'gpu_hours'].sum():,.0f} GPU-h  <- 宽 job 空转是重灾区?")
print(f"A 桶 GPU-h 集中度: top 10 users 占 {a.groupby('id_user').gpu_hours.sum().nlargest(10).sum()/hA:.0%}")
print()
# --- 卡间不均衡（claims 字段）：gpus.parquet 按 gpu_id pivot ---
multi = g.groupby("id_job").filter(lambda x: len(x)>=2)
piv = multi.groupby("id_job").agg(busy=("smutilization_pct_avg","max"), quiet=("smutilization_pct_avg","min"), gh=("gpu_hours","sum"), n=("gpu_id","size"))
piv = piv.join(j.set_index("id_job")[["walltime_sec"]])
imb = piv[(piv.busy>=20)&((piv.busy-piv.quiet)>30)&(piv.walltime_sec>3600)]
# 闲置分数 = 每张卡相对最忙卡的差额
idle_frac = 1 - (multi.groupby("id_job").smutilization_pct_avg.mean() / piv.busy)
print(f"card imbalance: {len(imb)} jobs (规则说 689), 涉及 {imb.gh.sum():,.0f} GPU-h, 闲置卡当量 ≈ {(imb.gh*idle_frac.loc[imb.index]).sum():,.0f} GPU-h")
print()
# --- 无声硬件故障：同一台机器、多个用户、同一 exit_code、别处不出现 ---
f = j[j.state_name=="FAILED"].copy()
f["node"] = f.primary_node
sig = f.groupby(["node","exit_code"]).agg(users=("id_user","nunique"), n=("id_job","size")).reset_index()
tot = f.groupby("exit_code").agg(n_all=("id_job","size"), nodes_all=("node","nunique")).reset_index()
sig = sig.merge(tot, on="exit_code"); sig["share_here"] = sig.n/sig.n_all
cand = sig[(sig.users>=3)&(sig.share_here>0.5)&(sig.n>=20)].sort_values("n", ascending=False)
print("疑似无声硬件故障 (>=3 用户, 同 exit_code, >50% 该 code 的失败都在这一台):")
print(cand.head(5).to_string(index=False))
