# -*- coding: utf-8 -*-
"""浏览器自测：headless chromium 打开 http://localhost:8501 → 上传文档入库 → 提问 → 展开出处 → 截图 output/app_screenshot.png"""
import sys, time
from playwright.sync_api import sync_playwright

URL = "http://localhost:8501"
PDF = sys.argv[1]
Q = sys.argv[2] if len(sys.argv) > 2 else "SF6气体泄漏在线监测报警装置的报警值应如何设置？"
OUT = "/workspace/power_kb/output/app_screenshot.png"

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1500, "height": 1300})
    t = time.time()
    pg.goto(URL); pg.get_by_text("电力运维知识库问答").first.wait_for(timeout=180000)
    pg.get_by_text("模型已加载").wait_for(timeout=240000)
    print(f"页面就绪 {time.time() - t:.0f}s", flush=True)
    pg.locator("input[type=file]").set_input_files(PDF)
    pg.get_by_role("button", name="入库 1 个文件").click()
    pg.wait_for_selector("text=/块（\\d+ 页|已跳过/", timeout=600000)   # 成功或去重提示
    print(f"入库完成 {time.time() - t:.0f}s：", pg.locator("text=/块（\\d+ 页|已跳过/").first.inner_text(), flush=True)
    pg.get_by_test_id("stChatInputTextArea").fill(Q)
    pg.keyboard.press("Enter")
    pg.wait_for_selector("text=/📎 出处/", timeout=600000)
    print(f"回答完成 {time.time() - t:.0f}s", flush=True)
    pg.locator("text=/📎 出处/").last.click()
    time.sleep(2)
    msgs = pg.get_by_test_id("stChatMessage")
    print("回答：", msgs.last.inner_text()[:600])
    pg.screenshot(path=OUT, full_page=True)
    print("截图 ->", OUT)
    b.close()
