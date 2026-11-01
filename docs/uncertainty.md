# 通过率与配置配对差值的置信区间

更新：2026 年 11 月 1 日，Asia/Shanghai。实现见 [091](changes/2026-11-01-091-confidence-intervals.md)。使用原 `--report` 入口生成独立报告；新报告 JSON、Markdown 和浏览页面显示标称 95% 的逐项区间，不调用模型。原配置报告格式版本 1 / 2 / 3、执行结果、描述性差值与回归门禁退出码不变。

## 计算范围

- 通过率只在同一 caseEntryId / configurationId / source 内计算，使用 verification=verified、configurationMatch=matched、执行 completed、录制 complete，且断言和任务 outcome 为 passed / failed 的样本。分子是这些样本中 passed 的数量，分母 n 为这些样本数量。
- 不为跨用例的总通过率、混合来源、全尝试通过率或覆盖率生成区间。原 summary 中的这些描述性比例仍保留。
- 配置差值以同一用例、同重复编号、同来源的两侧合格样本为一对；方向固定为右减左。相同 configRef 的两个标签不作为配置差异。
- 数值指标还要求这对样本的两侧指标均为非负有限数值；缺失、布尔、非有限值不补零。每个指标单独确定纳入的配对及其分母。
- 续跑报告按原样本矩阵计数，历史复用与本轮新增不会重复成为独立观测。随机调度种子不等于模型采样种子，也不验证样本独立性。

## 区间方法

固定 confidenceLevel=0.95，不提供可调置信水平、p 值或自动优胜判定。

### 单配置通过率：Wilson score

令 p=k/n，z 为标准正态 0.975 分位数，区间中心和半宽分别为：

```text
center = (p + z²/(2n)) / (1 + z²/n)
half   = z * sqrt(p(1-p)/n + z²/(4n²)) / (1 + z²/n)
```

端点限制在 [0,1]；k=0 时下界精确为 0，k=n 时上界精确为 1。n=0 不计算；n=1 可以计算，但区间很宽。Wilson 是近似的二项比例区间，不承诺所有小样本参数下的实际覆盖都至少为 95%，尤其不能把全部通过显示成零宽的 [1,1]。公式和适用说明依据 [NIST 比例区间](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)。

### 配对通过率差：Hoeffding 保守区间

对每个合格配对构造 d=I(右通过)-I(左通过)，取值为 -1、0、1。对固定 n 的独立配对差值，使用有界变量双尾界反解：

```text
estimate = mean(d)
half = sqrt(2 * ln(2/0.05) / n)
interval = [max(-1, estimate-half), min(1, estimate+half)]
```

由 Hoeffding 界代入 [-1,1] 的范围得到；独立性假设下是保守区间，小 n 可能覆盖完整 [-1,1]。所有配对都一致时仍有非零宽度，不根据零次不一致推断零不确定性。discordantPairs 记录 d≠0 的配对数。数学界及推导可核对 [Pollard 公开概率讲义 §7.3](https://www.stat.yale.edu/~pollard/Books/Pttm/Pttm26-04.pdf)。这不是将左右两个独立比例区间相减。

### 数值指标配对均值差：Student t

仅对完整配对的 d=右指标-左指标计算均值、样本标准差 s_d，区间为 `mean(d) ± t(0.975,n-1) * s_d / sqrt(n)`。方差来自逐对差值，不使用两个独立组的方差。方法依赖配对之间独立，以及差值分布近似正态；小样本下尤其需要这些假设。[NIST 配对观测](https://www.itl.nist.gov/div898/handbook/prc/section3/prc311.htm)给出相应统计量。

实现只用 Python 标准库：通过正则不完全 beta 函数计算 t 双尾概率，再二分求临界值；连分式依据 [NIST DLMF 8.17.22–23](https://dlmf.nist.gov/8.17#v)，有收敛次数限制。测试核对 df=1 / 2 的解析值、[NIST 临界值表](https://www.itl.nist.gov/div898/handbook/eda/section3/eda3672.htm)及大自由度极限。[092](changes/2026-11-01-092-confidence-interval-review.md) 将差值先相对首项中心化，再按最大偏差绝对值缩放，减少大偏移对小波动的舍入影响；中心化本身溢出时退回原值缩放，还原端点时避免可抵消的中间量溢出。端点仍受浮点精度限制，不把区间裁剪到观测最小 / 最大值。

数值区间不足两对时不可用。观察方差为零时，t 公式会退化为零宽区间；本工具选择不输出该区间，保留点估计并标明 zero_observed_variance。不能由此宣称真实过程确定。非有限端点、收敛失败或精度丢失也返回不可用，不能输出 Infinity / NaN。

## 小样本与缺失边界

| 情况 | 处理 |
| --- | --- |
| n=0 | estimate / lower / upper 为 null，明确不可用原因 |
| 通过率 n=1 | 可计算 Wilson；标注 small_sample |
| 配对通过率差 n=1 | 可计算保守界；可能为完整 [-1,1] |
| 数值差值 n=1 | 保留点估计，区间不可用：insufficient_pairs |
| 数值差值无观察方差 | 保留点估计，区间不可用：zero_observed_variance |
| n<30 | 统一提示 small_sample；30 只是显示阈值，不是有效性或正态性的保证 |
| 数值端点不可表示 / 求解失败 | reason=numeric_unavailable；不删掉已观测配对，也不填零 |
| 端点因浮点精度合并 | reason=precision_loss，区间端点为 null |
| 缺证据、取消、坏路由、断言无法评测 | 排除相应样本或完整配对，不计作普通失败 |
| 单个指标缺值 | 只排除该指标的对应配对，仍可参与通过率差 |

缺失 / 排除可能不是随机发生的。这些区间仅针对实际纳入子集，无法修复选择偏差，也不能外推到全部计划。总分母、来源分母和纳入分母分别保存；页面不会把它们混用。

## JSON 字段与审计

新报告顶层 uncertaintyPolicy 保存 version=1、标称置信水平、小样本提示阈值，并声明 independenceVerified、normalityVerified、multiplicityAdjusted、optionalStoppingAdjusted 均为 false。

通用区间字段：method、confidenceLevel、n、status（available / unavailable）、estimate、lower、upper、reason、warnings。available 表示计算条件满足并产出有限端点，不代表统计假设已经验证。unavailable 的端点始终为 null；有观测时可以保留 estimate。

`repeatDistributions[].passRateInterval` 另保存 successes、plannedSamples、sourceSamples、excludedSamples、otherSourceSamples、repeatIndices。n 与该来源排除数之和等于 sourceSamples，sourceSamples 与其他来源数之和等于 plannedSamples；不能把不同来源行的计划分母相加。

`comparisons[].uncertainty` 保存 direction=right-minus-left、passRateDifference 及 metrics 中各指标区间。每项包括 plannedPairs、includedPairs、excludedPairs、repeatIndices、excludedReasons；纳入与排除之和等于原计划配对数。排除原因按以下优先顺序互斥计数：

1. same_configuration：两标签对应同一配置。
2. missing_verified_matched_pair：该重复编号缺少同来源、复验且配置匹配的一侧或两侧。
3. not_jointly_evaluable：虽有上述配对，但并非双方都正常完成且可评测。
4. missing_metric：双方均可评测，但这个指标有一侧缺值或不可用。

区间自己的 estimate 以纳入配对的逐对差值计算，可能因纳入样本范围或浮点运算与旧 metrics.meanDifference / rateDifferences 不同；不能把新区间附到旧描述性点估计上解释。旧字段保持原口径。通过率差使用概率差，0.1 代表 10 个百分点，不是相对提升 10%。

## 解释限制

这些是逐项、固定样本量下的条件区间，不是同时覆盖全部用例和指标的联合区间。未做多重比较、反复查看结果后的选择、或可选停止校正；按 token / 错误等条件提前停止也不能自动获得这些校正。区间跨零不证明配置相同，不跨零也不会自动生成显著性或赢家结论。名义 95% 描述重复抽样方法的覆盖目标，不是“本次固定区间有 95% 概率包含参数”。

只读浏览器显示保存值，不重新计算。旧报告没有统计字段时不补算，需使用原稳定归档重新生成新报告。原 --report 仍以成功生成为退出 0，基线回归的 0 / 1 / 2 仍按已观测状态变化判定；不根据区间修改模型成绩、历史结果或门禁。
