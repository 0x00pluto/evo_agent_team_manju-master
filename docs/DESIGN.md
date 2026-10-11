# 操作台视觉

漫剧操作台的页面是 [`src/studio/static/index.html`](../src/studio/static/index.html)。控件用 daisyUI 5，布局用 Tailwind 浏览器版，状态用 Alpine。不另起组件库，不上构建链。

颜色只在这一页的 `[data-theme="studio"]`：纸白、墨色、成功绿和危险色沿用原来的色值。字体仍是 Noto Sans SC、Noto Serif SC 和 JetBrains Mono。

页面由 `.venv/bin/python scripts/run_studio.py` 在 `http://127.0.0.1:8767/` 提供。
