# 重排前后对比示例（heading，hybrid α=0.5 → bge-reranker-v2-m3 重排 Top-20，展示 Top-3）

## q06：SF6气体分解物多久检测一次？
标注：DL_T_1359-2025_六氟化硫电气设备故障气体分析和判断方法.pdf / 7 检测周期；hybrid 名次 2 → 重排后 1

重排前：
```text
[1] 1.0000  DL_T_1359-2025_六氟化硫电气设备故障气体分析和判断方法.pdf  p5-6  6 判断依据  (dense#1 0.6763 | bm25#1 28.3746)
    个月内复检测一次 可能存在缺陷  6.2 当确定SO2、H2S 含量出现异常变化时,应增加实验室分析,根据SF6 气体分解物中CO、CF4 等其它参考指标的变化,结合故障气体分析历史数据、运行工况和吸附剂影响等对设备状态进行综合诊断,采取相应的措施。 6.3 当断路器气室中SO2、H2S 含量超注意
[2] 0.7957  DL_T_1359-2025_六氟化硫电气设备故障气体分析和判断方法.pdf  p6  7 检测周期  (dense#2 0.6715 | bm25#4 20.6864)
    7 检测周期  运行状态下SF6 气体分解物检测周期宜按电压等级划分,见表5。  表5 六氟化硫电气设备故障气体检测周期电压等级检测周期备注  a)新设备和大修后宜投运3 月内检测1 次;  必要时包括下列状况:  66kV 及以上  b)运行后可3 年检测1 次;  a)发生近区短路断路器跳闸时;
[3] 0.7409  DL_T_618-2022_GIS现场交接试验规程.pdf  p8  9 充入GIS 内部气体的质量检测  (dense#6 0.6272 | bm25#3 24.5627)
    9 充入GIS 内部气体的质量检测 9.1 GIS 气室充入SF6气体质量检测项目  9.1.1 GIS隔室充入SF6气体前,应对每瓶SF6气体湿度复核检测,检测结果不应超过表1的规定。 9.1.2 SF6气体湿度检测应采用电解法、露点法,检测方法和要求应按GB/T 5832.1、GB/T 5832
```
重排后：
```text
[1] 0.9884  DL_T_1359-2025_六氟化硫电气设备故障气体分析和判断方法.pdf  p6  7 检测周期  (重排前#2 0.79573 → rerank 0.9884)  (dense#2 0.6715 | bm25#4 20.6864)
    7 检测周期  运行状态下SF6 气体分解物检测周期宜按电压等级划分,见表5。  表5 六氟化硫电气设备故障气体检测周期电压等级检测周期备注  a)新设备和大修后宜投运3 月内检测1 次;  必要时包括下列状况:  66kV 及以上  b)运行后可3 年检测1 次;  a)发生近区短路断路器跳闸时;
[2] 0.9747  DL_T_1359-2025_六氟化硫电气设备故障气体分析和判断方法.pdf  p5-6  6 判断依据  (重排前#1 1.0 → rerank 0.97466)  (dense#1 0.6763 | bm25#1 28.3746)
    个月内复检测一次 可能存在缺陷  6.2 当确定SO2、H2S 含量出现异常变化时,应增加实验室分析,根据SF6 气体分解物中CO、CF4 等其它参考指标的变化,结合故障气体分析历史数据、运行工况和吸附剂影响等对设备状态进行综合诊断,采取相应的措施。 6.3 当断路器气室中SO2、H2S 含量超注意
[3] 0.9281  平高_ZF12B-126_GIS_安装使用说明书.pdf  p16  7 产品的验收 > 7.2 保管  (重排前#18 0.22976 → rerank 0.92807)  (dense#21 0.5689 | bm25#19 11.7184)
    7.2 保管 产品应避免存放在腐蚀性的大气中,存放的环境温度应在+5°C~+35°C,在封放期间各充气密封组件的SF6气体或N2压力不应低于0.03MPa,大约每6 个月应检查一次,若低于0.03MPa,应补进湿度合格的新SF6气体或N2至0.03 MPa。  包装有效期为一年。
```

## q25：How is the closing operation of the VD4 vacuum circuit-breaker initiated?
标注：ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf / 3.3.2 Closing procedure；hybrid 名次 2 → 重排后 1

重排前：
```text
[1] 1.0000  ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf  p20-24  5 Installation > 5.2 Assembly/installation of the circuit-breaker on a  (dense#1 0.727 | bm25#1 25.0839)
    the operating mechanism is of the manual type.  6.3.2 Closing and opening Vacuum circuit-breaker type VD4, for fixed installation Closing: – Press mec
[2] 0.7612  ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf  p14  3 Structure and function > 3.3 Function > 3.3.2 Closing procedure  (dense#2 0.7171 | bm25#4 19.485)
    3/4, 3/7, 6/1, 6/3, 6/4, 6/7, 7/2 and 7/3) The closing process is initiated manually using mechanical ON push-button 54.2 (for fixed installation brea
[3] 0.6835  ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf  p6  1 Summary  (dense#5 0.6852 | bm25#3 20.0289)
    1 Summary 1.1 General Vacuum circuit-breakers of type VD4 are intended for indoor installation in air-insulated switchgear. The circuit-breakers of co
```
重排后：
```text
[1] 0.9960  ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf  p14  3 Structure and function > 3.3 Function > 3.3.2 Closing procedure  (重排前#2 0.76119 → rerank 0.99595)  (dense#2 0.7171 | bm25#4 19.485)
    3/4, 3/7, 6/1, 6/3, 6/4, 6/7, 7/2 and 7/3) The closing process is initiated manually using mechanical ON push-button 54.2 (for fixed installation brea
[2] 0.9813  ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf  p20-24  5 Installation > 5.2 Assembly/installation of the circuit-breaker on a  (重排前#1 1.0 → rerank 0.9813)  (dense#1 0.727 | bm25#1 25.0839)
    the operating mechanism is of the manual type.  6.3.2 Closing and opening Vacuum circuit-breaker type VD4, for fixed installation Closing: – Press mec
[3] 0.8428  ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf  p20-24  5 Installation > 5.2 Assembly/installation of the circuit-breaker on a  (重排前#19 0.25798 → rerank 0.84276)  (dense#21 0.6061 | bm25#21 15.1248)
    2.1. 6.3.3 Run-on block When any irregularities occur in the internal control mechanism or with the charging function of the spring-energy storage mec
```

## q32：SM6开关柜正常条件下需要定期维护吗？
标注：Schneider_SM6-24_Operating_Maintenance_S1B7039801.pdf / Maintenance > Periodical Maintenance（跨语言）；hybrid 名次 4 → 重排后 1

重排前：
```text
[1] 1.0000  平高_ZF12B-126_GIS_安装使用说明书.pdf  p13-14  6 产品的运行和维护  (dense#1 0.6229 | bm25#1 25.6978)
    6 产品的运行和维护 由于受现场条件的限制,产品的本体及操动机构中的元件一般不能现场解体。如有需要应通知制造厂派专人到现场检修。  一般来说只要保证不漏气,则只需定期维护及检修操动机构和有关传动的机械部分。除了正常的日常维护外,其大修周期应与开关设备的电寿命和机械寿命相当。
[2] 0.5537  DL_T_2228-2021_变电站用充气式开关柜运维检修规程.pdf  p5-6  4 运维要求 > 4.2 巡视  (dense#4 0.6031 | bm25#4 14.1931)
    4.2 巡视  充气式开关柜巡视包括例行巡视和特殊巡视,根据巡视结果对相关装置、设备进行处理。 例行巡视:定期开展巡视,无人值守的另定。 特殊巡视:运行状态变化或经历特殊工况后,进行必要的巡视。 4.2.1 例行巡视  例行巡视是对运行中的充气式开关柜本体及附属设备和运行环境进行检查,主要检查设备、
[3] 0.4869  DL_T_2228-2021_变电站用充气式开关柜运维检修规程.pdf  p8  5 检修要求 > 5.2 检修类别 > 5.2.1 例行检修  (dense#2 0.6142 | bm25#27 9.2775)
    5.2.1 例行检修  a) 检查柜体状况,清扫柜体表面、电缆室、仪表室; b) 清扫断路器操作机构内部元件,包括分、合闸线圈,主轴、连杆、拐臂及辅助接点等; c) 清扫带接地开关的隔离开关机构内部元件,包括电机、主轴、连杆、拐臂及限位开关接点等; d) 清扫气体压力表,检查并紧固密度继电器接点; 
```
重排后：
```text
[1] 0.9752  Schneider_SM6-24_Operating_Maintenance_S1B7039801.pdf  p41-52  Operating Safety  (重排前#4 0.42966 → rerank 0.97518)  (dense#3 0.6118 | bm25#- -)
    Maintenance  Preventive Maintenance Periodical Maintenance In normal operating conditions (temperature between -5 °C and 40 °C) no special maintenance
[2] 0.5163  平高_ZF12B-126_GIS_安装使用说明书.pdf  p13-14  6 产品的运行和维护  (重排前#1 1.0 → rerank 0.51626)  (dense#1 0.6229 | bm25#1 25.6978)
    6 产品的运行和维护 由于受现场条件的限制,产品的本体及操动机构中的元件一般不能现场解体。如有需要应通知制造厂派专人到现场检修。  一般来说只要保证不漏气,则只需定期维护及检修操动机构和有关传动的机械部分。除了正常的日常维护外,其大修周期应与开关设备的电寿命和机械寿命相当。
[3] 0.1067  Schneider_SM6-24_Operating_Maintenance_S1B7039801.pdf  p5-12  Foreword  (重排前#11 0.33333 → rerank 0.10667)  (dense#7 0.5966 | bm25#- -)
    to local regulations and rules (Regulation (EU) No 517/2014 for all European countries). Schneider Electric offers a complete service to dismantle and
```

## k09：DL/T 724 的 7.4.1.2 条
标注：DL_T_724-2021_蓄电池直流电源装置运行与维护技术规程.pdf / 7.4.1.2 阀控蓄电池核对性放电周期；hybrid 名次 3 → 重排后 1

重排前：
```text
[1] 0.7448  DL_T_724-2021_蓄电池直流电源装置运行与维护技术规程.pdf  p1  （前置内容/封面/目录）  (dense#6 0.4828 | bm25#2 6.6809)
    ICS 27.100 CCS F 23  中华人民共和国电力行业标准  DL/T 724—2021 代替DL/T 724—2000电力系统用蓄电池直流电源装置运行与维护技术规程Specification of operation and maintenance of battery DC power
[2] 0.5000  ABB_VD4_36-40.5kV_VCB_Installation_Service_1VCD601314.pdf  p26-27  7 Maintenance > 7.2 Inspection and functional testing > 7.2.5 Breaker pole  (dense#1 0.5053 | bm25#- -)
    7.2.5 Breaker pole No inspection of the breaker pole above and beyond the stipulations of section 7.2.1 is necessary. 7.3 Servicing
[3] 0.5000  DL_T_724-2021_蓄电池直流电源装置运行与维护技术规程.pdf  p20  7 维护 > 7.4 周期性测试 > 7.4.1 阀控蓄电池的核对性放电 > 7.4.1.2 阀控蓄电池核对性放电周期  (dense#- - | bm25#1 7.4803)
    7.4.1.2 阀控蓄电池核对性放电周期  新安装或大修后的阀控蓄电池组,应进行全容量核对性放电试验,以后每2 年至少进行一次核对性试验,运行了4 年以后的阀控蓄电池,应每年作一次容量核对性放电试验。 7.4.1.3 其他方法  a) “50%放电”方法  阀控蓄电池“50%放电”的容量核对性放电试
```
重排后：
```text
[1] 0.9681  DL_T_724-2021_蓄电池直流电源装置运行与维护技术规程.pdf  p20  7 维护 > 7.4 周期性测试 > 7.4.1 阀控蓄电池的核对性放电 > 7.4.1.2 阀控蓄电池核对性放电周期  (重排前#3 0.5 → rerank 0.96811)  (dense#- - | bm25#1 7.4803)
    7.4.1.2 阀控蓄电池核对性放电周期  新安装或大修后的阀控蓄电池组,应进行全容量核对性放电试验,以后每2 年至少进行一次核对性试验,运行了4 年以后的阀控蓄电池,应每年作一次容量核对性放电试验。 7.4.1.3 其他方法  a) “50%放电”方法  阀控蓄电池“50%放电”的容量核对性放电试
[2] 0.9297  DL_T_724-2021_蓄电池直流电源装置运行与维护技术规程.pdf  p17-18  7 维护  (重排前#18 0.19658 → rerank 0.92973)  (dense#13 0.4627 | bm25#- -)
    7 维护 7.1 技术档案  7.1.1 发电厂、变电站及其专业班(组)应建立健全直流电源装置的设备台账和运行维护记录等技术文件档案。 7.1.2 技术档案  技术档案包括: a) 设备台账主要有设备卡片(含名称、型号、生产厂家、出厂日期、合格证等)、出厂技术文件(技术参数资料、使用说明书、出厂试验
[3] 0.8380  DL_T_724-2021_蓄电池直流电源装置运行与维护技术规程.pdf  p18  7 维护 > 7.2 蓄电池组的维护 > 7.2.2 蓄电池组的一般维护  (重排前#13 0.21897 → rerank 0.83804)  (dense#19 0.4554 | bm25#25 3.8972)
    7.2.2 蓄电池组的一般维护  蓄电池组一般维护的要求: a) 检查和调整浮充电电压; b) 在满足安全的条件下进行清扫,清扫周期由各运行单位在现场(运行)规程中明确; c) 采用蓄电池短时(5min~10min)带经常性负荷放电,实测蓄电池单体电压值,每年不少于2次; d) 由专业维护人员进行清
```
