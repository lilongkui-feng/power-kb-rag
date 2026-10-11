# 前端经 API 问答截图：打开 http://localhost:8501（纯前端）→ 本地 ollama 提问 → 展开出处 → output/app_api_screenshot.png
import sys, time
from playwright.sync_api import sync_playwright
Q = sys.argv[1] if len(sys.argv) > 1 else "新安装的阀控蓄电池组多久做一次核对性放电试验？运行几年后要改为每年一次？"
OUT = "/workspace/power_kb/output/app_api_screenshot.png"
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1500, "height": 1250})
    pg.goto("http://localhost:8501"); pg.get_by_text("API http").wait_for(timeout=120000)
    pg.get_by_test_id("stChatInputTextArea").fill(Q); pg.keyboard.press("Enter")
    pg.wait_for_selector("text=/📎 出处/", timeout=300000)
    pg.locator("text=/📎 出处/").last.click(); time.sleep(2)
    print(pg.get_by_test_id("stChatMessage").last.inner_text()[:600])
    pg.screenshot(path=OUT, full_page=True); print("->", OUT); b.close()
