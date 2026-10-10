# 漫剧操作台

本机页面：用飞书链接或上传脚本读入正文，再逐段选择「分镜演绎」或「只配音」。出镜名单由勾选锁定。DeepSeek 只写外貌、场景和运镜。完成后按人物、场景、分镜逐条复制提示词，并把 MP3 打开或打包给后期。

业务仍是提示词生成与整集配音。操作台只是壳，不改画风，不给空镜再写一套无人分镜。

## 入口

```bash
cd /Users/peng.zhi/Documents/Codex/AI漫剧大师
.venv/bin/python scripts/run_studio.py --open
```

浏览器打开 `http://127.0.0.1:8767/`。只绑定本机。

同一套页面也可以作为 Dex Buddy 插件打开。仓库根上的 `plugin.manifest.json` 指向 `index.js` 和这份页面。列表和详情的图标、简介来自清单里的 `icon` 与 `description`。插件里按钮优先走 `window.dex.call`，没有再退回 `window.hub.call`；浏览器里两者都没有则仍走本机 HTTP。业务还是 Python，不在 Node 里重写。

开发时不要把源码拷进 Dex Buddy 的 `plugins/`。任选一种：

```bash
ln -s "/Users/peng.zhi/Documents/Codex/AI漫剧大师" "/绝对路径/DexBuddy/plugins/manju-studio"
```

或在 Dex Buddy 仓库根把 `config.dev.example.json` 复制为 `config.dev.json`，写入：

```json
{
  "extraPluginPaths": [
    "/Users/peng.zhi/Documents/Codex/AI漫剧大师"
  ]
}
```

`config.dev.json` 只在未打包的开发版里生效。改 `index.js` 或页面后重启 Dex Buddy。侧边栏名字是「漫剧操作台」。

本仓里有 `.venv/bin/python` 时，插件用它跑源码，改 Python 不用先重打包。发给别人的包不带 `.venv`，也不带 `.env`。没有虚拟环境时，按当前系统启动 `bin/darwin/manju-studio-worker`、`bin/win32/manju-studio-worker.exe` 或 `bin/linux/manju-studio-worker`。当前系统那份不在时，仍报「安装包不完整」。

开发、软链接或 `config.dev.json` 挂进来时，`temp/` 和 `output/` 仍写在本仓。从插件中心或拖放装进 Dex Buddy 之后，这两项目录改写到用户数据目录 `plugin-data/manju-studio/`，覆盖安装不会把成片和 `temp/studio_facts` 清掉。`assets/` 仍从安装目录读。卸载插件时 Dex Buddy 不删这份数据。`dispose` 只结束配音进程。

插件中心发版只改 `plugin.manifest.json` 的 `version`（`X.Y.Z`，不要前导 0），提交并推送，再打 tag `vX.Y.Z` 并推送。`v` 后面必须和清单版本相同。把仓库 `0x00pluto/evo_agent_team_manju-master` 和这个 tag 告诉 Dex Buddy 维护者，由他在 Actions 里运行 Publish Plugin。同事在插件中心安装，不要把下载地址发给他们。

根上的 `dex-buddy-plugin-pack.json` 指向 `scripts/dex-buddy-plugin-pack.sh`。Action 在 `macos-latest`、`windows-latest`、`ubuntu-latest` 各跑一次，并用 `DEX_BUDDY_OS` 标明 `darwin`、`win32` 或 `linux`。脚本自己在 `temp/` 里建虚拟环境并安装 PyInstaller，把当前系统的 worker 写到扁平的 `bin/`，再用一条预览做冒烟。不上传，不打 zip。Action 再把三端收进同一份 zip 的 `bin/darwin`、`bin/win32`、`bin/linux`。Mac 产物是这台 Apple Silicon 编译机的架构，不是通用二进制。密钥只在 Dex Buddy 设置页填写，不写进仓库，不打进包。不要把编好的二进制提交进 git，也不要在本仓加调用 Dex Buddy 的工作流。

在 Dex Buddy 里从侧栏底部「设置」选「漫剧操作台」。设置页按「提示词」「飞书」「配音」三组显示：提示词里填 DeepSeek 密钥、模型和接口地址，飞书里填 App ID 与 App Secret，配音里填 MiniMax 密钥，然后点「保存」。改了 `plugin.manifest.json` 里的设置声明后要重启一次 Dex Buddy；之后只改设置不用重启。仓库里的 `.env` 只给本机命令行用，不进 zip。工作台注入的值优先，`.env` 不会盖掉它们。飞书文档用这两个应用凭证走开放平台读取。配音由本仓直接调用 MiniMax，发布包里的 Python 二进制已经带上这段调用。

本机拖进工作台仍用下面这条。它打的是当前机器的单平台 zip，不代替给 Action 调用的脚本。

```bash
sh scripts/build_plugin_worker.sh
```

脚本会先检查 PyInstaller。没有就停下来，并提示 `uv pip install pyinstaller`。打完后用一条预览请求做冒烟，再把发布目录收成 zip：`temp/plugin-dist/manju-studio-v<版本>.zip`。对方把 zip 拖进欢迎页，或点「安装插件」。这种来源不参与插件中心的更新。窗口要能访问外网，页面上的字体和 Alpine 来自 CDN。

## 参数

| 参数 | 说明 |
|---|---|
| `--host` | 默认 `127.0.0.1`；其它地址拒绝启动 |
| `--port` | 默认 `8767` |
| `--open` | 启动后打开浏览器 |

页上不填密钥。提示词用本仓 `DEEPSEEK_API_KEY`。飞书读取用 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`。配音用 `MINIMAX_API_KEY`。本机命令行把这几项写在 `.env`。

## 日常步骤

1. 启动操作台。
2. 在「飞书文档」里粘贴 wiki 或 docx 链接，点「读取」。或点「上传脚本」选 `.md` / `.txt`。两者只留后选的一个，程序不再从一段说明里搜链接。
3. 读到正文后，按脚本里的 `【…】` 逐段选择「分镜演绎」或「只配音」。标题外面包了加粗星号也认。有「某人：台词」的段默认分镜，纯旁白默认只配音。`【】` 之前的角色说明，以及后面的「口播要点」表，不进列表。本地切不出两段、正文又像有多段时，DeepSeek 只标每段在原文里的起点。没有段落就不能开始。
4. 点「开始」。勾了分镜的段才生成分镜；一段对白超过约 72 字就按句拆镜。所有段的口播都进配音清单。DeepSeek 不决定出镜名单。
5. 完成后是场记单：人物三视图与特写、场景、分镜，每块单独「复制」，按这个顺序贴进即梦 / LibTV。
6. 配音按 `01`… 试听。改某一句的字，点该条「重新配音」，只重配这一条。单条下载，或「下载全部」成 zip。「打开所在文件夹」只打开这一集的 `voiceover` 文件夹。Mac 走访达，Windows 走资源管理器。
7. 勾选不对就回到对话框重跑。已生成过的集在右上角「历史记录」里，不必重跑。

同一时刻只跑一集。上传落在 `temp/studio_uploads/`。

## 产物

- `temp/studio_facts/<年月日-时分秒-名称>.json`
- `temp/studio_facts/<年月日-时分秒-名称>-voiceover.json`
- `output/<年月日-时分秒-名称>/` 提示词与 `voiceover/*.mp3`，例如 `output/20260929-095800-four-demo/`

这两份 JSON 是这一稿的临时事实，脚本不要了就可以连 `temp/studio_facts/` 一起删。汉阳造、光谷生物城的参考稿仍在 `assets/episodes/`。分镜里的参考图由程序写成「图1角色三视图；图2场景贴图；可选面部特写」，不交给模型填「无」。

同一脚本再跑会新开一个目录，不覆盖上一次。配音文件仍是 `01_owner.mp3` 这种序号。

## 失败排查

| 现象 | 处理 |
|---|---|
| 已有任务进行中 | 等当前集结束，或重启操作台 |
| 飞书读取失败 | 设置里填写飞书 App ID 和 App Secret；应用开通「查看新版文档」「查看知识库」，并被加进这篇文档或知识空间；链接是 wiki 或 docx |
| 脚本里没有【】段落 | 给每一段加上 `【标题】` 后再读取 |
| 台词不在脚本原文里 | 出镜句必须来自勾了分镜的段；只配音的句子不能进分镜 |
| 超过 12 秒上限 | 单句超过约 72 字且没有句号时无法再拆，缩短这句后重跑 |
| 提示词有了但没有 MP3 | 在设置或 `.env` 里填写 `MINIMAX_API_KEY` 后重跑 |
| 文件夹打不开 | 确认该集 `output/<主题>/voiceover/` 里已有文件 |

## 明确不做

公网、登录、页内嵌 LibTV、空镜的无人分镜、换画风。

## 测试

```bash
.venv/bin/python -m unittest tests.test_studio tests.test_feishu_doc -v
```
