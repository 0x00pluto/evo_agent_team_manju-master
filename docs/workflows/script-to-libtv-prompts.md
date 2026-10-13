# 脚本 → LibTV 可复制提示词（DeepSeek 生成）

输入本集事实 YAML，按可替换模板模块调用 DeepSeek，产出可复制到即梦 / ChatGPT / LibTV 的提示词包。Cursor/Grok **不**撰写提示词成品正文。

## 入口

```bash
cd /Users/peng.zhi/Documents/Codex/AI漫剧大师
uv pip install -r requirements.txt
.venv/bin/python scripts/generate_prompts.py --help
```

## 参数

| 参数 | 说明 |
|---|---|
| `--episode` | 本集事实 YAML/JSON（角色、场景、台词） |
| `--out` | 输出目录，建议 `output/<主题>/` |
| `--dry-run` | 只打印组装后的模板提示，不调 API |
| `--only-shot` | 只生成该镜 id，写入 `--out/03-分镜.md`（插在上一镜之后；不重生角色/场景） |

## 日常步骤

1. **配 Key**：复制 `.env.example` 为 `.env`，填写 `DEEPSEEK_API_KEY`（申请：https://platform.deepseek.com/api_keys ；文档：https://api-docs.deepseek.com/zh-cn/）。
2. **安装依赖**（本机手动）：`uv pip install -r requirements.txt`
3. **确认风格指针**：`src/prompt_templates/manifest.md` 中 `style_id`（默认 `cinematic-photoreal-short-drama` 电影级写实仿真人短剧）。
4. **准备或改本集事实**：`assets/episodes/hanyangzao-hook-cta.yaml`（或同目录 `.json`；未装 PyYAML 时请用 `.json`）（只含钩子 + 结尾 CTA）。
5. **生成**：

```bash
.venv/bin/python scripts/generate_prompts.py \
  --episode assets/episodes/hanyangzao-hook-cta.json \
  --out output/hanyangzao-hook-cta
```

6. 打开 `output/hanyangzao-hook-cta/`，按 `00-使用说明.md` 复制：三视图 → 特写 → 场景 → LibTV 分镜。
7. **只补一镜**（例如中间痛点接在钩子后，不重跑整包）：

```bash
.venv/bin/python scripts/generate_prompts.py \
  --episode assets/episodes/hanyangzao-hook-cta.json \
  --out output/hanyangzao-hook-cta \
  --only-shot V01b-mid-pain
```

## 产物

- `output/<主题>/00-使用说明.md`
- `output/<主题>/01-角色-*.md`
- `output/<主题>/02-场景.md`
- `output/<主题>/03-分镜.md`

模板模块（可替换，入库）：`src/prompt_templates/`。

分镜生成注入 `blocking.md`：**先想空间站位，再写运镜与表演**；允许走、转、手势，禁止无路径换阵（起幅/收幅像两套摆拍）。不把人钉成站桩，也不在本模块锁死运镜花样。运镜总表在 `src/prompt_templates/camera_moves.md`，写明什么时候用什么手法，不整份注入。园区短剧只用其中一组基本手法，按这一拍的情绪挑。场景贴图是主位空镜，主桌和主位座椅不要坐着主角，远处虚化路人可以有。

## 失败排查

| 现象 | 处理 |
|---|---|
| 缺少 DEEPSEEK_API_KEY | 检查 `.env`；进程环境优先于文件 |
| 未安装 openai / PyYAML | `uv pip install -r requirements.txt` |
| 想换画风 | 新增 `src/prompt_templates/style/<id>.md`，改 `manifest.md` 的 `style_id` 后重跑 |
| dry-run 正常、真跑空 content | 查 DeepSeek 配额 / 模型名 `DEEPSEEK_MODEL` |

## 测试

```bash
.venv/bin/python -m unittest tests.test_prompt_fill -v
```
