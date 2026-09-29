# 发布 evo_agent_pack（工牌）

**仅首次**（尚无 `evo_agent_pack.json` / 尚无 remote / 需改 `name`·`origin`·`depends_on`）时跑本篇。**日常发版不要从本篇进门**，改走 [cut-release-tag.md](./cut-release-tag.md)。合同字段偶发变更时仍可用本篇核对；打 tag / Release 一律交给 cut-release-tag。

为**当前仓**生成或核对根目录 `evo_agent_pack.json`，确认后按 [cut-release-tag.md](./cut-release-tag.md) 写 `upgrades/`、打 `v{version}` tag 并建 GitHub Release。人读兄弟关系仍以 `AGENTS.md` 为准；机器只认这份 JSON。安装器以后读它；本工作流**不**写安装器、不空盘拉兄妹、不改花名册。

一次只雇**当前这一个仓**。叶子（无 `depends_on`）先于编排者。依赖只抄 `AGENTS.md` 里 `depends_on` 的行；`learns_from` / `fork_of` 禁止写入 `dependencies`。缺字段就停下来问，**禁止编造 origin**。**禁止**无 `upgrades/v{version}.md` 直接打 tag。

## 入口

```text
1. 打开当前工作区（本工作流对「正在打开的仓」跑，不要一次雇两个仓）
   若已有完整 evo_agent_pack.json 且本轮只是升版发版 → 停，改走 cut-release-tag.md
2. 阅读本篇全文
3. 按「日常步骤」检查表顺序执行；任一步缺信息 → 停，按「失败排查」问询
4. 验收：工牌 JSON 字段齐全后，按 cut-release-tag 完成 tag + Release；另一块空目录只拿 origin + v{version} 能 clone 出带该 JSON 的提交
```

本工作流由 Agent 对话驱动；第一刀用手工 git + 检查表。不提供 Python CLI。

## 参数

对话输入（非 CLI）：

| 输入 | 说明 |
|---|---|
| 当前仓路径 | 默认即打开的工作区根目录 |
| `name` | 英文 slug，小写加横线；**问用户**，禁止从中文文件夹名瞎翻译后直接 push |
| `dirname` | 默认当前文件夹名；须与兄妹布局一致。用户要改名时提醒：依赖方可能按文件夹名找人，第一刀建议不改 |
| `version` | semver，不含 `v`；默认建议 `0.1.0`；git tag = `v` + 此数 |
| `origin` | 可 clone 的 git URL（SSH 或 HTTPS）；必须与 `git remote get-url origin` 一致；**禁止编造** |
| 远程托管 | GitHub / Bitbucket / 其他；无 origin 时问 workspace/org + slug，协助建空仓后再填真实 URL |
| 依赖对方 | 要写入 `dependencies` 的对方仓路径 / `dirname`（可多条）；见「如何增加 / 变更依赖」 |

## 合同：`evo_agent_pack.json`

根目录，与 `AGENTS.md` 平级。两份都入库。publish 以 JSON 为准打 tag；JSON 里的依赖必须能在 `AGENTS.md` 的 `depends_on` 里找到，对不上就失败并问。

### 叶子示例（无运行时依赖）

`origin` 必须是真实 URL；文档占位仅说明形状，**禁止**把占位写进仓库。

```json
{
  "schema_version": 1,
  "name": "<英文 slug，问用户>",
  "dirname": "<当前文件夹名>",
  "version": "0.1.0",
  "origin": "<与 git remote get-url origin 一致，禁止编造>",
  "dependencies": {}
}
```

### 编排者示例（有 `depends_on`）

```json
{
  "schema_version": 1,
  "name": "<英文 slug，问用户>",
  "dirname": "<当前文件夹名>",
  "version": "0.1.0",
  "origin": "<与 git remote get-url origin 一致，禁止编造>",
  "dependencies": {
    "<对方 dirname>": {
      "origin": "<对方已发布的 origin>",
      "version": "<对方已打 tag 的 version，不含 v>"
    }
  }
}
```

依赖对象只要 `origin` + `version`。不要 git URL 碎片、不要 `latest`、不要 semver 范围。对方 tag 就是 `v` + `version`。

### 字段铁律

| 字段 | 是什么 | 铁律 |
|---|---|---|
| `schema_version` | 合同格式号 | 现在写 `1` |
| `name` | 远程仓库名 / 机器 id | 英文 slug，小写加横线。问用户，不要从中文文件夹名瞎翻译后直接 push |
| `dirname` | 兄妹目录名 | **必须等于**现在代码里的文件夹名。改它可能打碎依赖方硬编码路径 |
| `version` | 本包版本 | semver，**不含** `v`。git tag 固定为 `v` + 这个数 |
| `origin` | 可 clone 的 git URL | SSH 或 HTTPS 一条。必须和 `git remote get-url origin` 一致 |
| `dependencies` | 运行时兄弟 | **只抄 `AGENTS.md` 里 `depends_on` 的行**。key 用对方 `dirname`。对方 `learns_from` / `fork_of` 不准进来 |

**不要写进 JSON：** owns、lifecycle、heartbeat、start、`.env`、文件清单、WikiIndex、Dagu。gitignore 已挡住 `.venv` / `.env` / `temp` / `output`；git 自己决定装什么。合同只管「我是谁、我要哪个兄妹的哪个 tag」。

## 如何增加 / 变更依赖

先改人读的 `AGENTS.md`，再改机器认的 JSON。三种情况：

### A. 首次发工牌就有依赖

1. 在当前仓 `AGENTS.md`「兄弟关系」表写入对方，关系列必须是 `depends_on`（不是 `learns_from` / `fork_of`）。
2. 打开对方仓根目录，读其 `evo_agent_pack.json` 的 `origin` 与 `version`。
3. 确认对方远程已有 tag `v` + 该 `version`。没有 JSON 或没有 tag → **停**，先给叶子发工牌。
4. 写入本仓 JSON：`dependencies.<对方 dirname> = { "origin": "…", "version": "…" }`。
5. 再走日常步骤其余项，最后改走 cut-release-tag。

### B. 已有工牌后追加依赖

1. **再进本篇**（不要从 cut-release-tag 进门改合同）。
2. 同 A：先改 `AGENTS.md` 为 `depends_on`，再读对方工牌写入 `dependencies`。
3. 对方未发工牌 → 停。
4. 合同改完后走 cut-release-tag 发本仓新版。

### C. 对方升版后改钉住的 version

1. 再进本篇（或人明确说本次一并改合同）。
2. 只更新 JSON 里该 key 的 `version`（及若对方换了 `origin` 则同步）；**不要**写 `latest` 或 semver 范围。
3. 确认新 `v{version}` 已在对方远程存在。
4. 改走 cut-release-tag 发本仓新版。

`cut-release-tag` **默认不改** `dependencies`，除非人明确要求本次一并改合同。

## 日常步骤

```text
读 AGENTS.md 兄弟关系
→ 读或新建 evo_agent_pack.json
→ 缺字段？停，按「失败排查」问，写进去
→ depends_on 的每个人：打开对方仓，必须已有 JSON，且 origin+version 已在远程存在对应 tag
   没有 → 停，告诉用户先去给叶子发工牌
→ working tree：pack.json 未提交或脏了 → 问：提交哪些文件 / 中止
→ 确认 origin remote 存在且 URL = JSON.origin
→ 改走 cut-release-tag.md：写 upgrades、对齐 version、打 tag、推送、建 Release
```

展开：

1. **读兄弟关系**  
   打开当前仓 `AGENTS.md`「兄弟关系」表。只收集关系列为 `depends_on` 的行；忽略 `learns_from` / `fork_of`。

2. **读或新建 JSON**  
   根目录若不存在 `evo_agent_pack.json`，按合同骨架新建；已存在则核对字段。缺字段或空值 → **停**，按问询表逐项问，写进去后再继续。禁止编造 `origin`。

3. **核依赖**  
   对每个 `depends_on` 兄弟：打开对方仓根目录，必须已有 `evo_agent_pack.json`；其 `origin` + `version` 对应的远程 tag `v{version}` 必须已存在。没有 JSON 或没有 tag → **停**，告诉用户先给对方发工牌。禁止把 `learns_from` 写进 `dependencies`，禁止写 `latest`，禁止改指对方 main。JSON 已有依赖 key 但 AGENTS 对应行不是 `depends_on` → **停**，先改 AGENTS。

4. **工作区与密钥**  
   `git status`。若 `evo_agent_pack.json`（及本次要入库的配套改动）未提交或 working tree 脏 → 列出拟提交文件，问用户：提交还是中止。**禁止**提交 `cache/`、`temp/`、`output/`、`.env`。staged 里出现 `.env` → **立刻中止**（比合同格式更重要）。

5. **对齐 remote**  
   确认 `origin` remote 存在，且 `git remote get-url origin` **等于** JSON 的 `origin`。不一致 → 停，问以哪个为准；禁止静默改 remote。

6. **发版（改走 cut-release-tag）**  
   合同 JSON 就绪后，**不要**在本篇直接 `git tag`。打开 [cut-release-tag.md](./cut-release-tag.md)：写 `upgrades/v{version}.md`、更新索引、确认 pack `version`、本地 commit + tag、推送、`gh release create`（正文=upgrades）。缺发版页禁止打 tag。

7. **验收**  
   远程有 tag 与 GitHub Release；另一台机器或空目录只拿 `origin` + `v{version}`，能 clone 出带这份 JSON 与 `upgrades/v{version}.md` 的提交。依赖不自动拉（那是下一刀 install）。

## 产物

- 根目录 `evo_agent_pack.json`（与 `AGENTS.md` 平级，入库）
- `upgrades/v{version}.md`（须有；由 cut-release-tag 写入，作 Release 正文）
- 远程 tag `v{version}`（例如 version `0.1.0` → tag `v0.1.0`），tag 指向的提交内含该 JSON 与发版页
- GitHub Release（正文 = upgrades 全文）

## 失败排查

| 缺什么 / 现象 | 怎么问 / 处理 | 禁止 |
|---|---|---|
| 没有 git | 「这个目录还不是 git 仓。现在 `git init` 并做首次提交吗？」 | 静默 init 后直接 push |
| 没有 `origin` remote | 「远程托管是 GitHub、Bitbucket 还是其他？workspace/org 是哪个？仓库 slug 用哪个？（建议用 JSON 的 `name`）」→ 协助按用户选定的托管建**空仓**（网页或对应 CLI）→ `git remote add origin <用户给出的真实 URL>` | 猜 org、猜 URL、把中文文件夹名当 slug |
| JSON 没有 / 字段空 | 逐项问：`name`、`dirname`（默认当前文件夹名，请确认）、`version`（默认 `0.1.0`）、`origin` | 编造远程地址 |
| `depends_on` 对方没有 JSON 或没有 tag | 「先给「\<对方 dirname\>」发工牌。它的 origin / version 是什么？」 | 把 `learns_from` 写进 dependencies；写 `latest` |
| JSON 有依赖但 AGENTS 不是 `depends_on` | 「先把兄弟关系改成 depends_on，再写 JSON」 | 只改 JSON 不改 AGENTS |
| 对方 JSON 有，但远程还没有那个 tag | 「对方 version 写了 X，远程没有 `vX`。先去那边 push tag。」 | 改指对方 main |
| working tree 脏 | 「要写进本次工牌的是这些文件。提交还是中止？」 | 把 cache/temp/output/.env 提交 |
| staged 含 `.env` | 立刻中止，从暂存区移除并确认不会入库 | 带着密钥 push |
| tag 已存在 | 「`v{version}` 已在。升到下一 patch，还是你确认要移动旧 tag？」 | 默认 `--force` 改 tag |
| 无 upgrades 页却要打 tag | 「先走 cut-release-tag 写 `upgrades/v{version}.md`」 | 无记录直接 tag |
| remote URL ≠ JSON.origin | 「git origin 是 A，JSON 写的是 B。以哪个为准？」 | 静默改 remote |
| 用户要改 `dirname` | 提醒：依赖方可能按文件夹名找人，两边都要改；第一刀建议不改名 | 只改 JSON 不改对方硬编码 |

## 测试

手工验收（无自动化单测）：

```bash
# 在空目录，用用户确认过的 origin 与 version：
git clone --branch v0.1.0 <origin-url> /tmp/evo-pack-check
test -f /tmp/evo-pack-check/evo_agent_pack.json
test -f /tmp/evo-pack-check/upgrades/v0.1.0.md
# 打开该文件：schema_version、name、dirname、version、origin、dependencies 齐全；
# dependencies 的 key 仅来自 AGENTS.md 的 depends_on
```

本流不做：install CLI、空盘自动拉兄妹、WikiIndex、脚手架升级、把 Dagu YAML 打进包。打 tag / Release 细节见 [cut-release-tag.md](./cut-release-tag.md)。
