# README 截图：打开 http://localhost:8501 → 侧栏选“硅基流动 · DeepSeek-V3” → 提问 → 展开出处 → docs/images/app_siliconflow.png
import sys, time
from playwright.sync_api import sync_playwright
Q = sys.argv[1] if len(sys.argv) > 1 else "断路器灭弧气室 SO2、H2S 检测值多大时需要跟踪？对应的复测要求和诊断结论是什么？"
OUT = "/workspace/power_kb/docs/images/app_siliconflow.png"
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1500, "height": 1250})
    pg.goto("http://localhost:8501"); pg.get_by_text("模型已加载").wait_for(timeout=300000)
    sb = pg.get_by_test_id("stSelectbox").filter(has_text="LLM 提供方"); sb.scroll_into_view_if_needed(); sb.get_by_role("combobox").click()
    pg.get_by_role("option", name="硅基流动 · DeepSeek-V3（SILICONFLOW_API_KEY）").click()
    time.sleep(1)
    pg.get_by_test_id("stChatInputTextArea").fill(Q); pg.keyboard.press("Enter")
    pg.wait_for_selector("text=/📎 出处/", timeout=300000)
    pg.locator("text=/📎 出处/").last.click(); time.sleep(2)
    print(pg.get_by_test_id("stChatMessage").last.inner_text()[:500])
    pg.screenshot(path=OUT, full_page=True); print("->", OUT); b.close()
