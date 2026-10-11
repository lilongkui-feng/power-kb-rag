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
| 10-11 11:58 | xl_none | heading_v2+hybrid+rr@20β0.8,k=5 | - | 58% | 75% | 0.657 | 86% | - | - | - | - | - | - | 4.58 | output/eval_runs/xl_none_20261011-115837 |
| 10-11 12:01 | xl_dict | heading_v2+hybrid+rr@20β0.8,k=5 | - | 64% | 81% | 0.716 | 92% | - | - | - | - | - | - | 4.48 | output/eval_runs/xl_dict_20261011-120121 |
| 10-11 12:04 | v3set_sf_v3_p2 (rescore+归因拆分) | heading_v2+hybrid+rr@20β0.8,k=5,p2 | deepseek-ai/DeepSeek-V3 | 84% | 97% | 0.893 | 99% | 85% | 12% | 0.91 | 94% | 100% | 1% | 13.95 | output/eval_runs/v3set_sf_v3_p2_attr_20261011-120349 |
| 10-11 12:09 | xl_llm | heading_v2+hybrid+rr@20β0.8,k=5 | - | 64% | 83% | 0.726 | 92% | - | - | - | - | - | - | 12.94 | output/eval_runs/xl_llm_20261011-120908 |
| 10-11 12:27 | v3_xl_dict | heading_v2+hybrid+rr@20β0.8,k=5 | - | 77% | 94% | 0.841 | 97% | - | - | - | - | - | - | 7.83 | output/eval_runs/v3_xl_dict_20261011-122759 |
| 10-11 12:51 | v3_ctx | heading_v2_ctx+hybrid+rr@20β0.8,k=5 | - | 82% | 98% | 0.890 | 99% | - | - | - | - | - | - | 2.43 | output/eval_runs/v3_ctx_20261011-125125 |
| 10-11 13:00 | v3_mq_rule | heading_v2+hybrid+rr@20β0.8,k=5 | - | 78% | 96% | 0.852 | 99% | - | - | - | - | - | - | 3.71 | output/eval_runs/v3_mq_rule_20261011-130020 |
| 10-11 13:03 | xl_ctx | heading_v2_ctx+hybrid+rr@20β0.8,k=5 | - | 58% | 83% | 0.688 | 92% | - | - | - | - | - | - | 5.41 | output/eval_runs/xl_ctx_20261011-130341 |
| 10-11 13:09 | xl_auto | heading_v2+hybrid+rr@20β0.8,k=5 | - | 61% | 75% | 0.666 | 89% | - | - | - | - | - | - | 9.18 | output/eval_runs/xl_auto_20261011-130931 |
| 10-11 13:12 | xl_auto_llm | heading_v2+hybrid+rr@20β0.8,k=5 | - | 61% | 75% | 0.667 | 89% | - | - | - | - | - | - | 4.56 | output/eval_runs/xl_auto_llm_20261011-131221 |
| 10-11 13:21 | v3_xl_auto | heading_v2+hybrid+rr@20β0.8,k=5 | - | 83% | 96% | 0.888 | 99% | - | - | - | - | - | - | 3.68 | output/eval_runs/v3_xl_auto_20261011-132112 |
| 10-11 13:24 | rf3b_p1 | heading_v2+hybrid+rr@20β0.8,k=5,p1 | qwen2.5:3b-instruct | 68% | 86% | 0.779 | 96% | 23% | 46% | 0.455 | 41% | - | 4% | 16.33 | output/eval_runs/rf3b_p1_20261011-132414 |
| 10-11 13:34 | rf3b_p3 | heading_v2+hybrid+rr@20β0.8,k=5,p3 | qwen2.5:3b-instruct | 68% | 86% | 0.779 | 96% | 27% | 55% | 0.545 | 50% | - | 0% | 31.17 | output/eval_runs/rf3b_p3_20261011-133403 |
| 10-11 13:47 | rf3b_p3_reflect | heading_v2+hybrid+rr@20β0.8,k=5,p3 | qwen2.5:3b-instruct | 68% | 86% | 0.779 | 96% | 27% | 50% | 0.523 | 46% | - | 0% | 39.68 | output/eval_runs/rf3b_p3_reflect_20261011-134700 |
| 10-11 15:42 | xl_v3llm | heading_v2+hybrid+rr@20β0.8,k=5 | - | 61% | 75% | 0.667 | 92% | - | - | - | - | - | - | 8.07 | output/eval_runs/xl_v3llm_20261011-154205 |
| 10-11 15:42 | v3set_sf_v3_p3 | heading_v2+hybrid+rr@20β0.8,k=5,p3 | deepseek-ai/DeepSeek-V3 | 84% | 97% | 0.893 | 99% | 86% | 10% | 0.906 | 89% | 100% | 1% | 12.83 | output/eval_runs/v3set_sf_v3_p3_20261011-154227 |
| 10-11 16:08 | v3set_sf_v3_p3_reflect | heading_v2+hybrid+rr@20β0.8,k=5,p3 | deepseek-ai/DeepSeek-V3 | 84% | 97% | 0.893 | 99% | 86% | 11% | 0.917 | 90% | 100% | 1% | 46.35 | output/eval_runs/v3set_sf_v3_p3_reflect_20261011-160820 |
| 10-11 16:23 | v3_xl_v3llm | heading_v2+hybrid+rr@20β0.8,k=5 | - | 81% | 95% | 0.875 | 97% | - | - | - | - | - | - | 17.27 | output/eval_runs/v3_xl_v3llm_20261011-162333 |
| 10-11 16:31 | v3_xl_v3mismatch | heading_v2+hybrid+rr@20β0.8,k=5 | - | 83% | 97% | 0.889 | 99% | - | - | - | - | - | - | 3.18 | output/eval_runs/v3_xl_v3mismatch_20261011-163118 |
| 10-11 16:42 | v3_xl_v3cap | heading_v2+hybrid+rr@20β0.8,k=5 | - | 84% | 97% | 0.896 | 99% | - | - | - | - | - | - | 4.54 | output/eval_runs/v3_xl_v3cap_20261011-164218 |
| 10-11 16:47 | xl_v3mismatch | heading_v2+hybrid+rr@20β0.8,k=5 | - | 56% | 78% | 0.644 | 86% | - | - | - | - | - | - | 8.1 | output/eval_runs/xl_v3mismatch_20261011-164722 |
| 10-11 16:51 | xl_v3cap | heading_v2+hybrid+rr@20β0.8,k=5 | - | 67% | 86% | 0.745 | 89% | - | - | - | - | - | - | 6.22 | output/eval_runs/xl_v3cap_20261011-165113 |
