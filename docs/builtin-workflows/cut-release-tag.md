# 打发版 tag（upgrades 说明 + tag + GitHub Release）

**日常发版唯一入口**：已有工牌与 remote 后，每次升版只雇本篇。仅首次建仓 / 改合同字段时才去 [publish-evo-agent-pack.md](./publish-evo-agent-pack.md)。

可复跑：从上一 Git tag 到当前 HEAD 汇总变更 → 写 `upgrades/` 发版页 → 对齐 `evo_agent_pack.json` 的 `version` → 本地提交并打 tag → 推送 → 用发版页全文创建 GitHub Release。

与 [publish-evo-agent-pack.md](./publish-evo-agent-pack.md) 分工：工牌流只负责合同 JSON（仅首次 / 偶发核对）；**禁止**无 `upgrades/` 页直接打 tag——一律走本篇。

本仓无便携包 CI；Release 优先用 `gh release create`，正文读 `upgrades/vX.Y.Z.md`。无 `gh` / 未登录时用下方网页短路径。不做 zip / Actions / install CLI。

## 入口

```text
1. 打开当前工作区（一次只雇本仓）
2. 阅读本篇全文
3. 按「日常步骤」执行；缺信息或需升 major → 停，按失败排查问询
4. 验收：远程有 tag；GitHub Release 正文 = upgrades 全文；clone 该 tag 可见 evo_agent_pack.json
```

### 无 gh / 未登录时（网页短路径）

`gh release create` 走不通时，**仍先** `git push` 分支与 tag，再用网页建 Release（正文必须来自 `upgrades/$TAG.md`）：

```text
1. git push origin <默认分支>
2. git push origin $TAG
3. 打开 https://github.com/<owner>/<repo>/releases/new?tag=$TAG
4. 正文粘贴 upgrades/$TAG.md 全文 → Publish release
```

本工作流由 Agent 对话驱动；第一刀用手工 git + `gh`（或网页）。不提供 Python CLI。

## 参数

| 输入 | 说明 |
|---|---|
| 当前仓路径 | 默认即打开的工作区根目录 |
| `$TAG` | `vX.Y.Z`；可由 SemVer 规则算出，或人显式覆盖 |
| 是否代推 | 默认**只输出**推送 / Release 命令；**仅当用户本轮明确要求代推**时 Agent 才执行 `git push` / `gh release create` |

## 分工

| 角色 | 职责 |
|---|---|
| Agent | 查上一 tag..HEAD；按 SemVer 定版号（major 除外）；写 `upgrades/$TAG.md`；更新 `upgrades/README.md`；对齐 pack `version`；本地 `git commit` + `git tag`；默认只给出推送与 `gh` 命令 |
| 人 | major（及跳号 / 覆盖版号）时**显式指定**；自行推送，或本轮明确授权 Agent 代推 |

## 版号规则（SemVer · 铁律）

相对上一 tag `vMAJOR.MINOR.PATCH`：

| 变更类型 | 怎么升 | 谁决定 |
|---|---|---|
| 小补丁 / 修复 / 与发版无关的小改 | `PATCH +1` | Agent 按 SemVer 自动取下一号 |
| 功能变更 / 向后兼容的新能力 | `MINOR +1`，`PATCH` 归零 | Agent 按 SemVer 自动取下一号 |
| 不兼容 / 重大跃迁 | `MAJOR +1`，`MINOR` / `PATCH` 归零 | **必须人显式指定**；Agent **禁止**自行升 major |

细则：

- 尚无任何 `v*` tag（首发）→ 默认 `$TAG=v0.1.0`（或人指定）；发版页写「首发：本仓首个工牌发版」而非「相对上一 tag」。
- Agent 根据「上一 tag..HEAD」判定 patch 或 minor，直接采用算出的 `$TAG`。
- 若可能涉及 **breaking / major**：Agent **停住**，说明理由并请人给出目标 major；未确认前不得打 major tag。
- 人可随时覆盖：显式说出目标 tag 时，以指定为准。
- 跳号须人显式指定；默认不跳号。
- `$TAG` 去掉 `v` 后必须等于将写入的 `evo_agent_pack.json` → `version`。
- **默认不改** `dependencies` / `name` / `dirname` / `origin`；合同字段变更走 publish-evo-agent-pack，除非人明确说本次一并改。

## 日常步骤

```text
查上一 tag 与 PREV..HEAD 变更
→ 定版号 $TAG（major/跳号 → 等人口头确认）
→ 写 upgrades/$TAG.md + 更新 upgrades/README.md 索引
→ 对齐 evo_agent_pack.json 的 version（= $TAG 去 v）
→ 本地 commit（默认仅 upgrades + pack.json）+ git tag $TAG
→ 输出（或经授权执行）push + gh release create
→ 验收：远程 tag、Release 正文、clone 核对
```

展开：

### 0. 前置

- 功能改动已提交到默认分支（或即将随本流程一并提交的仅限 upgrades / pack 相关文件）。
- 工作区干净，或仅剩即将写入的 `upgrades/` 与 `evo_agent_pack.json`。
- `git remote get-url origin` 等于 `evo_agent_pack.json` 的 `origin`（GitHub）。不一致 → 停。

### 1. 查上一 tag 与变更

```bash
PREV=$(git tag -l 'v*' --sort=-v:refname | head -1)
echo "prev=$PREV"
# 无 PREV 时跳过 log/diff，按首发处理
git log "${PREV}..HEAD" --oneline
git diff "${PREV}..HEAD" --stat
```

把用户可见变更整理成「相对 `$PREV`」的要点（供发版页正文）。

### 2. 定版号 `$TAG`

1. 有 `$PREV`：解析 → `MAJOR.MINOR.PATCH`，按上表取下一号。
2. 无 `$PREV`：默认 `v0.1.0`（或人指定）。
3. 若需 major、跳号或人已指定覆盖 → **等人口头确认** `$TAG`（须 `vX.Y.Z`）。
4. 确认本地尚无同名 tag：`git rev-parse "$TAG" 2>/dev/null` 应失败。已存在且指向别的 commit → 停，问升 version 还是挪 tag；**禁止**默认 `--force`。

### 3. 写发版页并登记索引

- 新建 `upgrades/$TAG.md`（文件名与 tag **完全一致**，含 `v`）。若尚无 `upgrades/`，本步创建目录与 `upgrades/README.md`。
- 在 `upgrades/README.md` 表格增加一行。
- **不要**把单篇 upgrades 登记进 `docs/doc_index.md`（发版说明不是开发文档）。

体例：

```markdown
# vX.Y.Z

相对 `vA.B.C`：一句话说明本版相对上一 tag 的主题。
（首发：本仓首个工牌发版。）

## 变更

- …

## 升级注意

- clone / 切换到本 tag：`git clone --branch vX.Y.Z <origin>`
- 核对根目录 `evo_agent_pack.json` 的 `version` 为 `X.Y.Z`（不含 v）
```

缺 `upgrades/$TAG.md` 时 **禁止** `gh release create`。

### 4. 对齐工牌 version

编辑根目录 `evo_agent_pack.json`：把 `version` 设为 `$TAG` 去掉前缀 `v` 后的字符串。其余字段（`name` / `dirname` / `origin` / `dependencies`）本步不改，除非人另有要求。

### 5. 本地提交并打 tag

```bash
git add "upgrades/${TAG}.md" upgrades/README.md evo_agent_pack.json
git commit -m "$(cat <<EOF
docs(upgrades): 增加 ${TAG} 发版说明

EOF
)"
git tag "$TAG"
```

仅当还有未提交的功能代码且人要求一并入库时，才额外 `git add` 那些路径；默认本步只提交 upgrades + pack.json。

### 6. 推送与创建 Release

默认只把下列命令交给用户执行。**仅当用户本轮明确要求代推**时 Agent 才执行。

```bash
git push origin main
git push origin "$TAG"
gh release create "$TAG" --title "$TAG" --notes-file "upgrades/${TAG}.md"
```

分支名若非 `main`，换成当前默认分支。`gh` 须已登录且对 `origin` 仓库有 `contents: write`。无 `gh` / 未登录 → 见文首「网页短路径」，勿阻塞 tag 推送。Release 已存在 → 停，问是否改用 `gh release edit`；禁止静默覆盖。

### 7. 验收

- 远程存在 tag `$TAG`
- GitHub Releases 页正文与 `upgrades/$TAG.md` 一致
- 空目录：`git clone --branch "$TAG" <origin-url> /tmp/evo-pack-check`，存在 `evo_agent_pack.json` 且 `version` 正确

## 产物

- `upgrades/$TAG.md` + `upgrades/README.md` 索引行（入库）
- 更新后的 `evo_agent_pack.json`（`version` 与 tag 对齐）
- 本地与远程 lightweight tag `$TAG`
- GitHub Release（标题 = `$TAG`，正文 = upgrades 全文）

## 失败排查

| 现象 | 处理 | 禁止 |
|---|---|---|
| 可能升 major | 「是否 breaking？目标 major tag 是？」 | Agent 自行打 `v1.0.0` / `v2.0.0` |
| 跳号 | 等人显式指定目标 `$TAG` | 默认跳号 |
| 缺 `upgrades/$TAG.md` | 先写再 tag / Release | 空正文建 Release |
| tag 已存在且指向别的 commit | 问升版还是挪 tag | 默认 `--force` |
| remote ≠ JSON.origin | 问以哪个为准 | 静默改 remote |
| staged 含 `.env` | 立刻中止 | 带着密钥 push |
| `gh` 未登录 / 无权限 | 见文首「网页短路径」；或请人 `gh auth login` 后再 `gh release create` | 编造 Release；因无 gh 而跳过 Release |
| 用户未授权代推 | 只输出命令并停 | 静默 push |

## 测试

手工验收（无自动化单测）：

```bash
TAG=v0.1.0   # 换成本版
test -f "upgrades/${TAG}.md"
git rev-parse "$TAG"
gh release view "$TAG"
git clone --branch "$TAG" "$(git remote get-url origin)" /tmp/evo-pack-check
python3 -c "import json; p=json.load(open('/tmp/evo-pack-check/evo_agent_pack.json')); assert p['version']=='${TAG#v}'"
```
