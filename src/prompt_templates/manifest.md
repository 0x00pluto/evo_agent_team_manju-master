# Prompt template modules

可替换提示词骨架。生成脚本把本集 `episode.yaml` 事实 + 模块注入 DeepSeek，由 DeepSeek 写出可复制正文。

## Current style pointer

style_id: cinematic-photoreal-short-drama

换风格：新增 `style/<id>.md`，再改本行 `style_id`。

## Modules

| id | path | purpose |
|---|---|---|
| style | `style/<style_id>.md` | 统一画风句（中英）与禁止项 |
| duration | `duration.md` | 字数控时、对手戏合并、不换场 |
| blocking | `blocking.md` | 分镜先空间再运镜/表演；禁止无路径换阵 |
| character_sheet | `character_sheet.md` | 三视图生图骨架 |
| character_closeup | `character_closeup.md` | 面部特写骨架 |
| scene | `scene.md` | 场景贴图骨架 |
| shot_libtv | `shot_libtv.md` | LibTV 九要素分镜骨架 |
| script_normalize | `script_normalize.md` | 读取脚本时把原稿收成标准分段 |

## Placeholders

| name | meaning |
|---|---|
| `{{style}}` | 注入当前风格模块全文 |
| `{{duration_rules}}` | 注入时长规则模块全文 |
| `{{blocking_rules}}` | 注入空间站位规则模块全文（仅分镜） |
| `{{name}}` | 角色名 |
| `{{appearance}}` | 外貌 |
| `{{wardrobe}}` | 服装 |
| `{{expression}}` | 神态 |
| `{{time_of_day}}` | 时段/天气感 |
| `{{space}}` | 空间描述 |
| `{{light}}` | 光影 |
| `{{props}}` | 道具与氛围细节 |
| `{{shot_id}}` | 分镜编号 |
| `{{duration_hint}}` | 建议秒数 |
| `{{shot_type}}` | 景别 |
| `{{camera}}` | 运镜 |
| `{{protagonist}}` | 主角与参考图挂载说明 |
| `{{action}}` | 动作（可留空由模型补全时写「待生成」） |
| `{{dialogue}}` | 台词原文（一字不改） |
| `{{sfx}}` | 音效（可留空） |
| `{{lighting}}` | 本镜光影（可留空） |
| `{{scene_ref}}` | 场景与参考图 |
| `{{ref_images}}` | LibTV 挂图清单 |
