# MiniMax 学新声 + 用已有音色配音

学新音色在本仓完成：操作台用插槽样音或上传的 MP4，调用国际站上传、克隆，再用同步合成激活，得到本账号 `voice_id`。结果写在插件数据 `voice-slots.json`，不写回 `assets/voices/*/voice.json`，也不进兄弟仓，不查飞书人物。

## 入口

操作台查看结果里的「角色声音」。命令行整集配音仍见 [`episode-voiceover.md`](./episode-voiceover.md)，那条路径不克隆。

密钥：国际站 `https://api.minimax.io` 的 `MINIMAX_API_KEY`。填本仓 `.env` 或 Dex Buddy 设置。缺密钥时提示词仍可复制，克隆和配音会要求先填写。

## 参数

| 参数 / 字段 | 说明 |
|---|---|
| `assets/voices/<slug>/voice.json` | 本仓音色资源清单（入库）；必含 `voice_id`、`model`、`sample` |
| `assets/voices/<slug>/voice.mp3` | 两枚默认插槽的样音，随安装包分发。`voice.json` 里的 `voice_id` 只是制作账号档案 |
| `voice-slots.json` | 本账号 `voice_id`、状态、失败原因。覆盖安装不删除 |
| `model` | 默认 `speech-2.8-hd` |

## 日常步骤

### A. 操作台生成可用音色

1. 生成提示词后打开查看结果里的「角色声音」。默认两个声音「AI企业主」「女招商主管」指向安装目录里的 `voice.mp3`。
2. 点「生成可用音色」。程序先用本机 `ffmpeg` / `ffprobe` 检查时长和大小，再上传、克隆、用短句激活。`voice_id` 由本机生成，请求里不含 `voice.json` 的包内 id。模型 `speech-2.8-hd`。
3. 要换声音时上传 MP4。短于 10 秒、长于 5 分钟、大于 20MB、或抽不出音轨，都不会发起上传。本机没有 ffmpeg 时页面说明需要安装。
4. 成功后这一声音只保留这一个本账号 `voice_id`。失败且从未成功则停在失败；曾经可用的声音，替换失败后回到可用并留下这次原因。

### B. 命令行用已入库音色配音

按 [`episode-voiceover.md`](./episode-voiceover.md) 写清单并运行 `scripts/synthesize_episode_voiceover.py`。这条路径读取 `voice.json` 的 `voice_id`，在本仓调用 MiniMax 同步合成，把 MP3 写到 `output/<主题>/voiceover/`。操作台配音不走这条读法。

## 产物

- 本账号音色：`voice-slots.json`，替换样音在 `voice-slots/<id>/sample.mp3`
- 默认样音：`assets/voices/ai-enterprise-owner/voice.mp3`、`assets/voices/female-zhao-shang-lead/voice.mp3`
- 配音：`output/<主题>/…mp3`（gitignore，不入库）

## 失败排查

| 现象 | 处理 |
|---|---|
| 音频短于 10 秒、长于 5 分钟或大于 20MB | 换一段符合限制的音轨后再克隆 |
| MP4 抽不出音轨 | 换有人声的文件；本机需已安装 ffmpeg |
| `status_code=2038` | 账号未开通克隆 / 未验证 |
| 槽位满 | Voice slots 为订阅配额；升档或删闲置音色 |
| 缺少 `MINIMAX_API_KEY` | 填本仓 `.env` 或操作台设置后再克隆、再配音；提示词不用重跑 |
| 克隆音色听感不对 | 确认短句激活已成功；模型用 `speech-2.8-hd`；换更长真实口播再克隆 |

## 测试

```bash
# 本仓：资源清单含 voice_id，合成请求不依赖兄弟仓
test -f assets/voices/ai-enterprise-owner/voice.json
grep -q '"voice_id"' assets/voices/ai-enterprise-owner/voice.json
.venv/bin/python -m unittest tests.test_minimax_tts tests.test_voiceover_manifest -v
```
