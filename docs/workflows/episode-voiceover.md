# 成片第二步：整集口播配音

成片链路里，在分镜提示词（[`script-to-libtv-prompts.md`](./script-to-libtv-prompts.md)）之后：**按口播全稿批量 TTS**，产出可按文件名顺序贴片的 MP3。命令行清单仍用已入库的 `voice_slug`，本命令不克隆。操作台配音改走本账号音色插槽，克隆见 [`minimax-voice-clone-and-tts.md`](./minimax-voice-clone-and-tts.md)。

清单独立于分镜 `episode` YAML。视频包可以只做钩子+CTA 镜，**口播必须跟全稿时间线**（钩子 → 中间痛点 → 规格 VO → 升华 → CTA），不能按 LibTV 镜号 V01→V02→V03 去排配音。

## 入口

```bash
cd /Users/peng.zhi/Documents/Codex/AI漫剧大师
.venv/bin/python scripts/synthesize_episode_voiceover.py --help
```

密钥：本仓 `.env` 或环境变量 `MINIMAX_API_KEY`（国际站 `https://api.minimax.io`）。合成在本仓完成。

## 参数

| 参数 | 说明 |
|---|---|
| `--manifest` | 配音清单 JSON，如 `assets/episodes/hanyangzao-hook-cta-voiceover.json` |
| `--out-dir` | 产物目录，默认 `output/hanyangzao-hook-cta/voiceover` |
| `--dry-run` | 只写 `.txt` 与清单草稿，不调 API |
| `--only` | 只配指定 `id`，可重复（如 `--only 06`） |

### 清单硬规则（写 `*-voiceover.json` 时）

| 规则 | 说明 |
|---|---|
| `id` | 两位序号 `01`…`NN`，与 `lines` 数组顺序一致；**禁止** `H01`/`M01`/`C01` 这类前缀（字典序 ≠ 剧本序） |
| 文件名 | `{id}_{owner\|advisor}.mp3`，排序即播放序 |
| `segment` | 仅标注段落（hook / mid-pain / mid-spec / sublime / cta），**不参与排序** |
| 切条 | 换说话人即新一条；同说话人超长 VO 可整段一条 |
| 引号 | ASCII `"…"` **原封不动**进 `text` 与 `.txt`（读法修正；引擎不读出引号）。禁止剥引号 |
| 表演括号 | 「叹气」等不进 `text` |
| 音色 | 命令行：`voice_slug` → `assets/voices/<slug>/voice.json` 的 `voice_id`。操作台：绑定的插槽上的本账号 `voice_id`，不用包内 id |

## 日常步骤

1. **前置**：命令行清单要求 `assets/voices/<slug>/voice.json` 已有 `voice_id`（汉阳造：`ai-enterprise-owner`、`female-zhao-shang-lead`）。操作台不读这个包内 id，要先点「生成可用音色」。
2. **对口播全稿排清单**：新建或改 `assets/episodes/<主题>-voiceover.json`。先按剧本念一遍顺序，再填 `01`…；不要从分镜 YAML 的 shots 顺序抄。
3. **dry-run（可选）**：确认会写出的 stem 与引号文本。

```bash
.venv/bin/python scripts/synthesize_episode_voiceover.py \
  --manifest assets/episodes/hanyangzao-hook-cta-voiceover.json \
  --out-dir output/hanyangzao-hook-cta/voiceover \
  --dry-run
```

4. **配音**：

```bash
export MINIMAX_API_KEY='你的国际站 Key'   # 若进程里还没有
.venv/bin/python scripts/synthesize_episode_voiceover.py \
  --manifest assets/episodes/hanyangzao-hook-cta-voiceover.json \
  --out-dir output/hanyangzao-hook-cta/voiceover
```

5. **验收**：在 `output/<主题>/voiceover/` 按文件名排序听 `01`→`NN`；对照同 stem `.txt` 与 `manifest-out.json`。

### 改清单但不想重配全部

- **只改顺序 / 重编号**：先改 JSON，再按旧→新映射**改名**已有 mp3/txt，更新 `manifest-out.json`；勿无必要重打 TTS。
- **只改某句文案**：改 JSON 后 `--only <id>` 重配该句。已有的 `manifest-out.json` 按 id 合并，其它条的记录留下。操作台查看结果里也可以改字后点「重新配音」。

## 产物

- `output/<主题>/voiceover/{id}_{owner|advisor}.mp3`
- 同 stem 的 `.txt`（与清单 `text` 字节级一致，含引号）
- `output/<主题>/voiceover/manifest-out.json`

## 失败排查

| 现象 | 处理 |
|---|---|
| 缺少 `MINIMAX_API_KEY` | 写入本仓 `.env`，或 `export MINIMAX_API_KEY=...` |
| 单句超过 5000 字 | 拆短后再配；当前只走同步合成 |
| 找不到 `voice.json` | 先跑学新声工作流入库 |
| 单句失败 | `--only <id>` 重跑（如 `--only 06`） |
| 数字读法不对 | 检查清单引号是否被改掉；见 [`docs/faqs/配音文案里的引号能否去掉.md`](../faqs/配音文案里的引号能否去掉.md) |
| 文件名对不上剧本 / 难找 | id 须两位序号且按**全稿**排；见 [`docs/faqs/配音产物如何按脚本顺序找.md`](../faqs/配音产物如何按脚本顺序找.md) |

## 测试

```bash
.venv/bin/python -m unittest tests.test_voiceover_manifest -v
.venv/bin/python scripts/synthesize_episode_voiceover.py \
  --manifest assets/episodes/hanyangzao-hook-cta-voiceover.json \
  --dry-run
test -f assets/voices/ai-enterprise-owner/voice.json
test -f assets/voices/female-zhao-shang-lead/voice.json
.venv/bin/python -m unittest tests.test_minimax_tts tests.test_feishu_doc -v
```
