# 实验对比表（evaluate.py 自动追加）

| 时间 | 实验 | 检索配置 | LLM | 块Hit@1 | 块Hit@5 | 块MRR | 文档Hit@1 | 正确 | 部分 | 得分 | 引用含标注块 | 库外拒答 | 误拒 | 秒/题 | 目录 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10-10 19:28 | smoke | heading+hybrid+rr@20β0.8,k=5 | qwen2.5:3b-instruct | 100% | 100% | 1.000 | 100% | 67% | 33% | 0.833 | 33% | - | 0% | 18.69 | output/eval_runs/smoke_20261010-192825 |
| 10-10 19:51 | baseline（规则 v1，生成时） | heading+hybrid+rr@20β0.8,k=5 | qwen2.5:3b-instruct | 80% | 100% | 0.892 | 98% | 42% | 34% | 0.59 | 56% | 100% | 2% | 26.07 | output/eval_runs/baseline_20261010-195131 |
| 10-10 19:53 | baseline（规则 v2 重算） | heading+hybrid+rr@20β0.8,k=5 | qwen2.5:3b-instruct | 80% | 100% | 0.892 | 98% | 50% | 36% | 0.68 | 56% | 100% | 2% | 26.07 | output/eval_runs/baseline_20261010-195131 |

说明：smoke 为 3 题冒烟；baseline 生成一次，规则 v1/v2 只是重算，不重跑生成。v2 调规则用了 18 题人工校准集，留出集 12 题一致率见 report.md。
| 10-10 20:49 | v1_heading_retr | heading+hybrid+rr@20β0.8,k=5 | - | 80% | 100% | 0.892 | 98% | - | - | - | - | - | - | 5.7 | output/eval_runs/v1_heading_retr_20261010-204951 |
| 10-10 21:16 | v2_heading_retr | heading_v2+hybrid+rr@20β0.8,k=5 | - | 78% | 100% | 0.870 | 98% | - | - | - | - | - | - | 3.89 | output/eval_runs/v2_heading_retr_20261010-211618 |
| 10-10 21:16 | v1_table_gen | heading+hybrid+rr@20β0.8,k=5 | qwen2.5:3b-instruct | 89% | 100% | 0.944 | 89% | 33% | 33% | 0.5 | 44% | - | 0% | 15.85 | output/eval_runs/v1_table_gen_20261010-211651 |
| 10-10 21:19 | v2_table_gen | heading_v2+hybrid+rr@20β0.8,k=5 | qwen2.5:3b-instruct | 78% | 100% | 0.870 | 89% | 56% | 11% | 0.611 | 56% | - | 0% | 16.73 | output/eval_runs/v2_table_gen_20261010-211922 |
| 10-10 21:38 | v2_full_gen | heading_v2+hybrid+rr@20β0.8,k=5 | qwen2.5:3b-instruct | 78% | 100% | 0.870 | 98% | 54% | 28% | 0.68 | 58% | 100% | 2% | 23.6 | output/eval_runs/v2_full_gen_20261010-213855 |
| 10-10 22:02 | retr_heading_v2 | heading_v2+hybrid+rr@20β0.8,k=5 | - | 78% | 100% | 0.873 | 98% | - | - | - | - | - | - | 6.48 | output/eval_runs/retr_heading_v2_20261010-220206 |
| 10-10 22:21 | retr_v2s400o50 | v2s400o50+hybrid+rr@20β0.8,k=5 | - | 68% | 98% | 0.813 | 98% | - | - | - | - | - | - | 12.95 | output/eval_runs/retr_v2s400o50_20261010-222128 |
| 10-10 22:36 | retr_v2s1200o50 | v2s1200o50+hybrid+rr@20β0.8,k=5 | - | 76% | 98% | 0.852 | 98% | - | - | - | - | - | - | 12.04 | output/eval_runs/retr_v2s1200o50_20261010-223633 |
| 10-10 22:44 | retr_v2s800o0 | v2s800o0+hybrid+rr@20β0.8,k=5 | - | 74% | 98% | 0.847 | 98% | - | - | - | - | - | - | 4.65 | output/eval_runs/retr_v2s800o0_20261010-224435 |
| 10-10 22:56 | retr_v2s800o150 | v2s800o150+hybrid+rr@20β0.8,k=5 | - | 78% | 98% | 0.863 | 98% | - | - | - | - | - | - | 4.35 | output/eval_runs/retr_v2s800o150_20261010-225639 |
| 10-10 23:22 | gen_v2fix_p0_k5 | heading_v2+hybrid+rr@20β0.8,k=5 | qwen2.5:3b-instruct | 78% | 100% | 0.873 | 98% | 56% | 28% | 0.7 | 60% | 80% | 4% | 28.02 | output/eval_runs/gen_v2fix_p0_k5_20261010-232224 |
| 10-10 23:48 | gen_v2_p1_k5 | heading_v2+hybrid+rr@20β0.8,k=5,p1 | qwen2.5:3b-instruct | 78% | 100% | 0.873 | 98% | 56% | 28% | 0.7 | 66% | 100% | 2% | 18.71 | output/eval_runs/gen_v2_p1_k5_20261010-234817 |
| 10-11 00:28 | gen_v2_p2_k5 | heading_v2+hybrid+rr@20β0.8,k=5,p2 | qwen2.5:3b-instruct | 78% | 100% | 0.873 | 98% | 60% | 26% | 0.73 | 76% | 80% | 4% | 43.41 | output/eval_runs/gen_v2_p2_k5_20261011-002811 |
| 10-11 00:54 | sf_v3_p1_k5 | heading_v2+hybrid+rr@20β0.8,k=5,p1 | deepseek-ai/DeepSeek-V3 | 78% | 100% | 0.873 | 98% | 78% | 22% | 0.89 | 96% | 100% | 0% | 15.82 | output/eval_runs/sf_v3_p1_k5_20261011-005425 |
| 10-11 01:02 | sf_q72_p1_k5 | heading_v2+hybrid+rr@20β0.8,k=5,p1 | Qwen/Qwen2.5-72B-Instruct | 78% | 100% | 0.873 | 98% | 80% | 20% | 0.9 | 92% | 100% | 0% | 13.0 | output/eval_runs/sf_q72_p1_k5_20261011-010206 |
| 10-11 01:07 | sf_v3_p2_k5 | heading_v2+hybrid+rr@20β0.8,k=5,p2 | deepseek-ai/DeepSeek-V3 | 78% | 100% | 0.873 | 98% | 86% | 14% | 0.93 | 98% | 100% | 0% | 11.79 | output/eval_runs/sf_v3_p2_k5_20261011-010749 |
| 10-11 01:40 | sf_v3_p2_ex_neighbor | heading_v2+hybrid+rr@20β0.8,k=5,p2 | deepseek-ai/DeepSeek-V3 | 78% | 100% | 0.873 | 98% | 84% | 16% | 0.92 | 98% | 100% | 0% | 12.11 | output/eval_runs/sf_v3_p2_ex_neighbor_20261011-014010 |
| 10-11 01:40 | sf_v3_p2_ex_parent | heading_v2+hybrid+rr@20β0.8,k=5,p2 | deepseek-ai/DeepSeek-V3 | 78% | 100% | 0.873 | 98% | 84% | 16% | 0.92 | 94% | 100% | 0% | 11.08 | output/eval_runs/sf_v3_p2_ex_parent_20261011-014052 |
| 10-11 02:09 | v3set_sf_v3_p2 | heading_v2+hybrid+rr@20β0.8,k=5,p2 | deepseek-ai/DeepSeek-V3 | 84% | 97% | 0.893 | 99% | 77% | 9% | 0.813 | 94% | 100% | 1% | 13.95 | output/eval_runs/v3set_sf_v3_p2_20261011-020946 |
| 10-11 02:12 | v3set_sf_v3_p2 (rescore) | heading_v2+hybrid+rr@20β0.8,k=5,p2 | deepseek-ai/DeepSeek-V3 | 84% | 97% | 0.893 | 99% | 85% | 12% | 0.91 | 94% | 100% | 1% | 13.95 | output/eval_runs/v3set_sf_v3_p2_20261011-020946 |
