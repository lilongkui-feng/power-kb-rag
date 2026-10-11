# 检索评测结果（bge-m3 dense + Chroma cosine）

评测集：32 题（中文 25，英文 7；含 2 道跨语言题）。相关 = 同一文件且块内含标注条款的特征原文（anchor）。

| 集合 | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR@10 | 中文 Hit@5 | 英文 Hit@5 | 文件级 Hit@1 | 文件级 Hit@5 | 单次查询(ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| heading | 0.812 | 0.969 | 1.0 | 1.0 | 0.881 | 1.0 | 1.0 | 0.969 | 1.0 | 14.0 |
| fixed | 0.562 | 0.812 | 0.875 | 0.938 | 0.691 | 0.92 | 0.714 | 0.969 | 0.969 | 2.6 |
| recursive | 0.656 | 0.875 | 0.906 | 0.969 | 0.776 | 0.92 | 0.857 | 1.0 | 1.0 | 3.1 |

## 每题首个相关结果的排名（- 表示前 10 未命中）

| 题 | 问题 | heading | fixed | recursive |
|---|---|---|---|---|
| q01 | 红外诊断中相对温差法怎么计算？适用于哪类缺陷？ | 1 | 3 | 3 |
| q02 | 带电设备红外检测对环境温度、相对湿度和风速有什么要求？ | 1 | 1 | 1 |
| q03 | 500kV变电站设备红外检测周期一年几次？ | 1 | 1 | 1 |
| q04 | 六氟化硫气瓶存放和使用有哪些安全规定？ | 1 | 1 | 1 |
| q05 | SF6设备故障气体分析以哪些组分作为判断依据？SO2和H2S的注意值是多少？ | 1 | 2 | 1 |
| q06 | SF6气体分解物多久检测一次？ | 2 | 1 | 2 |
| q07 | 阀控蓄电池组多长时间做一次核对性放电试验？ | 1 | 1 | 1 |
| q08 | 直流系统蓄电池运行中多久进行一次均衡充电？ | 1 | 3 | 2 |
| q09 | 蓄电池鼓胀变形是什么原因，怎么处理？ | 1 | 2 | 1 |
| q10 | GIS现场交接试验主回路电阻测量电流不小于多少？ | 1 | 1 | 1 |
| q11 | GIS气室的年漏气率要求是多少，怎样做密封性试验？ | 1 | 1 | 1 |
| q12 | GIS耐压前为什么要做老炼试验？ | 1 | 1 | 2 |
| q13 | 高压断路器分、合闸同期性怎么测量？ | 1 | 2 | 1 |
| q14 | 断路器分合闸脱扣器低电压动作试验怎么做？30%额定电压时应该怎样？ | 1 | 1 | 1 |
| q15 | 真空断路器弹跳时间如何测量？ | 1 | 1 | 1 |
| q16 | 哪些情况下应停用整套继电保护装置？ | 1 | 1 | 1 |
| q17 | 保护定值单变更有什么管理要求？ | 1 | 3 | 2 |
| q18 | 继电保护装置评价为严重状态后应该如何检修？ | 1 | 2 | 4 |
| q19 | 充气式开关柜母线验电要满足哪些条件？ | 5 | - | - |
| q20 | 充气柜气箱内气体湿度运行中不应大于多少？ | 1 | 1 | 1 |
| q21 | RM6环网柜负荷开关熔断器组合（F功能）怎么手动合闸？ | 1 | 3 | 1 |
| q22 | RM6熔断器熔断后撞击器会导致什么动作？ | 1 | 1 | 1 |
| q23 | NM1塑壳断路器多久维护一次？维护内容有哪些？ | 1 | 1 | 1 |
| q24 | NM1断路器正常使用的环境温度和海拔条件是什么？ | 1 | 1 | 1 |
| q25 | How is the closing operation of the VD4  | 2 | 4 | 2 |
| q26 | What determines the servicing intervals  | 3 | 6 | 1 |
| q27 | What are the recommended maintenance int | 3 | 4 | 2 |
| q28 | Does the SM6 switchgear need periodic ma | 1 | 1 | 1 |
| q29 | How do I replace the air filters of the  | 1 | 1 | 1 |
| q30 | How does sampling-frequency tracking wor | 1 | 1 | 1 |
| q31 | Infrared diagnosis: how to calculate the | 1 | - | 10 |
| q32 | SM6开关柜正常条件下需要定期维护吗？ | 3 | 9 | 7 |

## heading 集合未进前 1 的题（Top-3 明细）

**q06** SF6气体分解物多久检测一次？  （标注：DL_T_1359-2025_六氟化硫电气设备故障气体分析和判断方法.pdf / 7 检测周期；heading 排名 2）

- 0.676 DL_T_1359-2025_六氟化硫电气设备故障气体分析和判断方法.pdf | 6 判断依据 | p5
- 0.671 DL_T_1359-2025_六氟化硫电气设备故障气体分析和判断方法.pdf | 7 检测周期 | p6
- 0.666 平高_ZF12B-126_GIS_安装使用说明书.pdf | 6 产品的运行和维护 > 6.2 检查项目和推荐周期 > 6.2.4 SF6气体 | p15

**q19** 充气式开关柜母线验电要满足哪些条件？  （标注：DL_T_2228-2021_变电站用充气式开关柜运维检修规程.pdf / 4.4.2.4 母线验电；heading 排名 5）

- 0.737 DL_T_2228-2021_变电站用充气式开关柜运维检修规程.pdf | 4 运维要求 > 4.4 操作 > 4.4.2 验电依据 | p6
- 0.731 DL_T_2228-2021_变电站用充气式开关柜运维检修规程.pdf | 1 范围 | p4
- 0.727 DL_T_2228-2021_变电站用充气式开关柜运维检修规程.pdf | 6 试验要求 > 6.2 试验项目 | p10

**q25** How is the closing operation of the VD4 vacuum circuit-breaker initiated?  （标注：ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf / 3.3.2 Closing procedure；heading 排名 2）

- 0.727 ABB_VD4_36-40.5kV_VCB_Installation_Servi | 5 Installation > 5.2 Assembly/installation of the  | p20
- 0.717 ABB_VD4_36-40.5kV_VCB_Installation_Servi | 3 Structure and function > 3.3 Function > 3.3.2 Cl | p14
- 0.693 ABB_VD4_36-40.5kV_VCB_Installation_Servi | 3 Structure and function > 3.3 Function > 3.3.5 Qu | p14

**q26** What determines the servicing intervals of ABB VD4 vacuum circuit breakers?  （标注：ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf / 7.1 General；heading 排名 3）

- 0.707 ABB_VD4_36-40.5kV_VCB_Installation_Servi | 1 Summary | p6
- 0.694 ABB_VD4_36-40.5kV_VCB_Installation_Servi | 3 Structure and function > 3.3 Function > 3.3.5 Qu | p14
- 0.688 ABB_VD4_36-40.5kV_VCB_Installation_Servi | 7 Maintenance > 7.1 General | p25

**q27** What are the recommended maintenance intervals and tools for SafeRing ring main units?  （标注：ABB_SafeRing-SafePlus_12-24kV_RMU_IOM_1YVA000024_RevF.pdf / 18.2 Maintenance intervals；heading 排名 3）

- 0.716 ABB_SafeRing-SafePlus_12-24kV_RMU_IOM_1Y | 18 Service and maintenance > 18.1 General warnings | p44
- 0.715 ABB_SafeRing-SafePlus_12-24kV_RMU_IOM_1Y | 2 General description | p6
- 0.698 ABB_SafeRing-SafePlus_12-24kV_RMU_IOM_1Y | 18 Service and maintenance > 18.2 Maintenance inte | p44

**q32** SM6开关柜正常条件下需要定期维护吗？  （标注：Schneider_SM6-24_Operating_Maintenance_S1B7039801.pdf / Maintenance > Periodical Maintenance（跨语言）；heading 排名 3）

- 0.623 平高_ZF12B-126_GIS_安装使用说明书.pdf | 6 产品的运行和维护 | p13
- 0.614 DL_T_2228-2021_变电站用充气式开关柜运维检修规程.pdf | 5 检修要求 > 5.2 检修类别 > 5.2.1 例行检修 | p8
- 0.612 Schneider_SM6-24_Operating_Maintenance_S | Operating Safety | p41

