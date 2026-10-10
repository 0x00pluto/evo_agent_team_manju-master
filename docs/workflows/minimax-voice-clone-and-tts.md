# MiniMax 学新声 + 用已有音色配音

学新音色（克隆样音 → 得 `voice_id`）并登记到 `assets/voices/<slug>/`；之后用已有 `voice_id` 配口播 MP3。学新声仍在兄弟仓「IP数字人项目」做一次。日常配音由本仓直接调用国际站 MiniMax，不再进入兄弟仓。本仓不回写飞书。

## 入口

日常整集配音见 [`episode-voiceover.md`](./episode-voiceover.md)。学新声仍在兄弟仓里对样音做克隆。

密钥：国际站 `https://api.minimax.io` 的 `MINIMAX_API_KEY`。日常配音填本仓 `.env` 或 Dex Buddy 设置。学新声那一次在兄弟仓进程里提供同一把密钥。

## 参数

| 参数 / 字段 | 说明 |
|---|---|
| `assets/voices/<slug>/voice.json` | 本仓音色资源清单（入库）；必含 `voice_id`、`model`、`sample` |
| `assets/voices/<slug>/voice.mp3` | 克隆用样音（本地；`assets/**/*.mp3` 已 gitignore） |
| `voice_id` | MiniMax 音色 ID（学新声后写入 `voice.json`） |
| `model` | 默认 `speech-2.8-hd` |

## 日常步骤

### A. 学新声（一次性）

1. 准备清晰人声源（WAV/MP3）。MiniMax 要求 **≥10s、≤5min、≤20MB**。不足 10s 时循环拼到约 20s：

```bash
cd /Users/peng.zhi/Documents/Codex/AI漫剧大师
mkdir -p assets/voices/<slug>
ffmpeg -y -stream_loop 5 -i /path/to/source.wav \
  -t 20 -vn -acodec libmp3lame -ar 44100 -ac 1 -b:a 192k \
  assets/voices/<slug>/voice.mp3
```

2. 在兄弟仓用模块克隆（**不要**跑 `run-dh-voice-clone.mjs`——会先查飞书人物）。`voice_id` 须字母开头、8–256 字符、仅 `A-Za-z0-9_-`：

```bash
cd /Users/peng.zhi/Documents/Codex/IP数字人项目
# applyRepoDotenv + cloneAndActivateVoice；降噪开、音量归一化关
# 详见本仓复盘：样音 → purpose=voice_clone → voice_clone → T2A 激活
```

3. 写 `assets/voices/<slug>/voice.json`（`voice_id`、`model`、`sample` 等），样音放同目录 `voice.mp3`。

现成示例：`assets/voices/ai-enterprise-owner/`（`voice_id=AiEnterpriseOwner`）。

### B. 用已有声配音

按 [`episode-voiceover.md`](./episode-voiceover.md) 写清单并运行 `scripts/synthesize_episode_voiceover.py`。程序读取 `voice.json` 的 `voice_id`，在本仓调用 MiniMax 同步合成，把 MP3 写到 `output/<主题>/voiceover/`。

## 产物

- 学新声：`assets/voices/<slug>/voice.mp3` + `voice.json`
- 配音：`output/<主题>/…mp3`（gitignore，不入库）

## 失败排查

| 现象 | 处理 |
|---|---|
| 音频 &lt;10s | 循环拼到 ≥10s（建议约 20s）；同句重复会伤音色质量 |
| `status_code=2038` | 账号未开通克隆 / 未验证 |
| 槽位满 | Voice slots 为订阅配额，无加 slot API；升档或删闲置音色 |
| 缺少 `MINIMAX_API_KEY` | 日常配音填本仓 `.env` 或操作台设置；学新声填兄弟仓进程环境 |
| `run-dh-voice-clone` 找不到人物 | 漫剧角色不在飞书 1.2；改用 `cloneAndActivateVoice` 直调 |
| 克隆音色听感不对 | 确认已 T2A 激活；模型用 `speech-2.8-hd`；换更长真实口播重训 |

## 测试

```bash
# 本仓：资源清单含 voice_id，合成请求不依赖兄弟仓
test -f assets/voices/ai-enterprise-owner/voice.json
grep -q '"voice_id"' assets/voices/ai-enterprise-owner/voice.json
.venv/bin/python -m unittest tests.test_minimax_tts tests.test_voiceover_manifest -v
```
