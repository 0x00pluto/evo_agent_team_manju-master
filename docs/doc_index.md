# Document index

## Index

- `docs/builtin-workflows/post-task-reflect.md`: 任务后反思（白痴指数 → 删 → 程序化 → 鲁棒 → 加速）；用户明确要求时触发，不自动跑
- `docs/builtin-workflows/extract-experience.md`: 提取经验 → 项目无关最佳实践；用户明确要求时触发；落盘须问或读 experience_target，默认本仓 docs/best-practices/
- `docs/builtin-workflows/consolidate-memory.md`: 记忆巩固与遗忘（冲突消解 → 情景提纯 → 剪枝）；仅用户显式触发；与反思 / 提取经验互不串联
- `docs/builtin-workflows/publish-evo-agent-pack.md`: 仅首次 / 改合同时发布或核对 evo_agent_pack.json 工牌；日常发版勿进门；打 tag 改走 cut-release-tag；不做安装器
- `docs/builtin-workflows/cut-release-tag.md`: 日常发版唯一入口；汇总变更 → upgrades → 对齐 version → tag → 推送 → gh 或网页建 Release；major 须人指定
- `docs/workflows/script-to-libtv-prompts.md`: 模板模块 + DeepSeek 生成本集可复制提示词（配 DEEPSEEK_API_KEY、钩子+CTA 示例；分镜先空间后运镜/表演；运镜总表不注入，园区只用其中一组；场景主位空镜）
- `docs/workflows/libtv-studio.md`: 本机漫剧操作台；开发用 .venv；保存 src 下 Python 且空闲时进程自动重启；插件中心只推 tag，安装包按包含清单收窄，由 Dex Buddy 按 requirements.txt 准备 Python（飞书链接、上传文本或粘贴正文 → 加载后按标题或模型分段 → 两页核对段内口播全文 → 选生成分镜/只配音 → 下一页生成提示词 → 角色声音绑定声音 → 配音打开或打包；分镜参考图与场景行留 LibTV {{Mixed N}} 占位）
- `docs/workflows/episode-voiceover.md`: 成片第二步整集口播配音（全稿顺序 01…N → 本仓 MiniMax TTS；命令行用 voice_slug，操作台用本账号插槽）
- `docs/workflows/minimax-voice-clone-and-tts.md`: 操作台在本仓克隆本账号音色；命令行配音不克隆
- `docs/best-practices/minimax-voice-slots.md`: 同一 MiniMax 账号上克隆音色的编号与删除规范；新 voice_id 写成项目-是谁-时间，旧编号继续复用，删除只走接口
- `docs/workflows/_TEMPLATE.md`: 业务 workflow 六段骨架；新建业务工作流时复制并改名，写完后删掉本行或改成真实条目
- `docs/DESIGN.md`: 操作台视觉以 src/studio/static/index.html 的 data-theme="studio" 与 daisyUI 为准；改外观前先读，不另起组件库
- `specs/prds/prd-wiki-index.md`: PRD 索引，不计入序号；产品经理追加一行，工程验收官回写文末状态
- `.cursor/commands/team/`: 团队命令（产品经理、工程验收官、Python 开发工程师、测试工程师、自主交付工程师）；母版在 Vibecoding 团队成员库，全文不抄进 AGENTS.md
- `docs/faqs/配音产物如何按脚本顺序找.md`: 配音 id 用 01…N 全稿时间线；禁止 H/M/C；不跟 LibTV 镜号排
- `docs/faqs/配音文案里的引号能否去掉.md`: 读法用 ASCII 引号须原样送 TTS，禁止剥引号
- `assets/voices/ai-enterprise-owner/voice.json`: AI企业主音色资源（voice_id=AiEnterpriseOwner；样音 voice.mp3 本地）
- `assets/voices/female-zhao-shang-lead/voice.json`: 女招商主管音色资源（voice_id=FemaleZhaoShangLead；样音 voice.mp3 本地）
- `assets/episodes/hanyangzao-hook-cta-voiceover.json`: 汉阳造整集配音清单（脚本顺序 01…09；引号原样送 TTS）
