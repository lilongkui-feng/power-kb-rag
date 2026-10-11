# 跨语言检索评测集：问题由人工翻译（中问英档 / 英问中档），gold（source/evidence/chunk_ids）沿用 eval_set_v3 原题
import json, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EN2ZH = {
 "P15": "正常运行条件下，VD4真空断路器多久检查一次？",
 "P16": "ABB对SafeRing/SafePlus环网柜推荐的维护周期是什么？",
 "P17": "SM6-24开关柜维护时，开关设备应多久操作一次？",
 "P19": "ABB SafeRing/SafePlus 12-24kV环网柜维护时推荐用什么清洁剂？",
 "P20": "ABB VD4断路器的储能弹簧怎么储能？",
 "P21": "用三角钥匙手动操作ABB VD4断路器时，旋转角度和方向是怎样的？",
 "P34": "SIPROTEC 5中，输入信号源处于测试状态而被处理的功能处于正常状态、源信号数据值被忽略时，有哪两种处理选项？",
 "P35": "SIPROTEC 5装置的指示信号可以通过哪些方式输出？",
 "P36": "压力表指针处于红区时应采取什么措施？",
 "P46": "SafeRing/SafePlus开关柜的内部燃弧能力按什么标准试验？",
 "P47": "ABB VD4 36/40.5kV真空断路器的额定雷电冲击耐受电压是多少？",
 "F14": "Galaxy VS UPS告警“电池状况差”是什么意思？和“电池状况弱”有什么区别？",
 "F15": "SIPROTEC 5中，功能健康状态为警告和报警有什么区别？",
 "F29": "SM6-24开关柜前面板打不开或关不上怎么办？",
 "F38": "SIPROTEC 5装置功能退出登录后，其数据对象会怎样？",
 "O14": "Galaxy VS UPS（GVSOPT001/GVSOPT015）的空气滤网怎么更换？",
 "O15": "SM6 QM/PM柜更换中压熔断器的初始条件和关键规则是什么？",
 "O16": "SIPROTEC 5装置上确认自发故障显示时，LED复归起什么作用？",
 "O17": "ABB VD4断路器绝缘件表面和导电部件上附着牢固的污垢应如何清洁？",
 "O18": "检查ABB VD4 36-40.5kV断路器手车上的辅助开关设置时，试验操作中手车应如何移动？",
 "O27": "Galaxy VS UPS更换空气滤网后如何复位滤网提醒？",
 "O28": "按初始条件，SM柜安全分闸的步骤是什么？",
 "O41": "如何用DIGSI 5读取SIPROTEC 5装置的用户自定义日志？",
 "O42": "Galaxy VS UPS如何从正常运行切换到静态旁路运行，再切回正常运行？",
}
ZH2EN = {
 "P24": "What are the requirements for sampling pipe length and sampling period of a pump-suction SF6 leakage monitoring device?",
 "O31": "How do you operate the earthing switch on a Schneider RM6 SeT switchgear?",
 "O24": "How should a breakdown discharge during the AC withstand voltage test of GIS be handled?",
 "P09": "What are the requirements for the operating voltage of circuit-breaker opening and closing releases?",
 "P42": "What is the rated current of the Pinggao ZF12B-126 GIS?",
 "P22": "What is the fault gas detection interval for SF6 equipment rated 66 kV and above under normal operation?",
 "F22": "What should be done when the valve of an SF6 gas cylinder is frozen on site?",
 "O05": "What are the steps for UHF partial discharge detection on GIS?",
 "O37": "What procedures must operators follow when switching setting groups on a microprocessor protection device?",
 "F16": "Does an unlit VPIS voltage indicator on a SafeRing RMU prove the line is dead? What are the VPIS indication characteristics and operating temperature range?",
}
if __name__ == "__main__":
    base = {d["id"]: d for d in map(json.loads, open(os.path.join(HERE, "eval_set_v3.jsonl"), encoding="utf-8"))}
    out = []
    for tbl, lang, kind in ((EN2ZH, "zh", "zh→en档"), (ZH2EN, "en", "en→zh档")):
        for i, q in tbl.items():
            d = dict(base[i], id=i + "x", question=q, lang=lang, xling=kind, orig_question=base[i]["question"])
            out.append(d)
    for i in ("F39", "F40"):        # 原题即中文问英文手册
        out.append(dict(base[i], id=i + "x", lang="zh", xling="zh→en档", orig_question=base[i]["question"]))
    with open(os.path.join(HERE, "eval_xling.jsonl"), "w", encoding="utf-8") as f:
        for d in out:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(len(out), "题 -> eval_xling.jsonl")
