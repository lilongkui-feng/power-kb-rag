# README 截图（docs/images/）：① 前端云端 DeepSeek-V3 问答 + 出处展开（调用 1 次硅基流动）② 上传入库进度 + 文档列表 ③ FastAPI /docs
# 用法：先启动 API(:8000) 与前端(:8501)，再 .venv/bin/python deploy/readme_screenshots.py
import os, sys, time, httpx, fitz
from playwright.sync_api import sync_playwright
IMG = "/workspace/power_kb/docs/images"; os.makedirs(IMG, exist_ok=True)
Q = "运行中SF6设备灭弧气室的湿度限值是多少？超标后应如何处理？"
PDF = "/tmp/演示_开关柜巡视作业指导书.pdf"
d = fitz.open(); pg = d.new_page()
lines = ["开关柜巡视作业指导书（演示文档）", "1 范围", "本指导书适用于 10kV 开关柜的日常巡视。", "2 巡视周期",
         "2.1 有人值班变电站每天巡视不少于 1 次；无人值班变电站每周不少于 2 次。", "3 巡视内容",
         "3.1 检查带电显示器指示正常，柜体无异常声响和放电声。", "3.2 检查温湿度控制器工作正常，柜内温度不超过 40 ℃。"]
for i, t in enumerate(lines):
    pg.insert_text((50, 70 + i * 28), t, fontname="china-s", fontsize=12)
d.save(PDF)

with sync_playwright() as p:
    b = p.chromium.launch()
    # ① 云端问答
    pg = b.new_page(viewport={"width": 1500, "height": 1150})
    pg.goto("http://localhost:8501"); pg.get_by_text("API http").wait_for(timeout=120000)
    pg.get_by_role("combobox", name="LLM 提供方").click()
    pg.get_by_role("option", name="硅基流动 · DeepSeek-V3").click(); time.sleep(1.5)
    pg.get_by_test_id("stChatInputTextArea").fill(Q); pg.keyboard.press("Enter")
    pg.wait_for_selector("text=/📎 出处/", timeout=300000); time.sleep(1)
    pg.locator("text=/📎 出处/").last.click(); time.sleep(2)
    print(pg.get_by_test_id("stChatMessage").last.inner_text()[:500])
    pg.screenshot(path=f"{IMG}/ui_qa_cloud.png", full_page=True)
    # ② 上传入库
    pg2 = b.new_page(viewport={"width": 1500, "height": 950})
    pg2.goto("http://localhost:8501"); pg2.get_by_text("API http").wait_for(timeout=120000)
    pg2.locator("input[type=file]").set_input_files(PDF); time.sleep(2)
    pg2.get_by_role("button", name="入库 1 个文件").click()
    try:
        pg2.wait_for_selector("[data-testid=stProgress]", timeout=20000); time.sleep(1.5)
        pg2.screenshot(path=f"{IMG}/ui_ingest_progress.png")
    except Exception as e:
        print("progress not captured", e)
    pg2.wait_for_selector("text=/演示_开关柜巡视作业指导书.pdf：/", timeout=300000); time.sleep(1)
    pg2.locator("text=/库中文档：/").click(); time.sleep(1.5)
    pg2.screenshot(path=f"{IMG}/ui_ingest.png", full_page=True)
    # ③ /docs
    pg3 = b.new_page(viewport={"width": 1400, "height": 1300})
    pg3.goto("http://127.0.0.1:8000/docs"); pg3.wait_for_selector("text=PowerKB API", timeout=60000); time.sleep(2)
    pg3.screenshot(path=f"{IMG}/api_docs.png", full_page=False)
    b.close()
# 清理演示文档
for doc in httpx.get("http://127.0.0.1:8000/documents").json():
    if doc["source"].startswith("演示_开关柜") and doc["deletable"]:
        print("delete", httpx.delete(f"http://127.0.0.1:8000/documents/{doc['id']}", timeout=120).json()["message"])
