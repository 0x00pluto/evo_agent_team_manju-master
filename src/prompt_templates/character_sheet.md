---
id: character_sheet
replaces: character_sheet
required: [style, name, appearance, wardrobe, expression]
---

# 角色三视图模板（给生图模型）

你是顶尖角色概念设计师。按下列骨架输出**可直接复制**的【中文提示词】和【英文提示词】各一块（用 Markdown 代码块包裹）。不要解释过程。

## 风格（必须完整遵守）

{{style}}

## 角色事实（不得改写身份与服装大类）

- 名称：{{name}}
- 外貌：{{appearance}}
- 服装：{{wardrobe}}
- 神态：{{expression}}

## 固定骨架（必须写入提示词）

1. 【核心画面设定】：A Character Sheet of {{name}}, 3D character, full body（中文版写「角色三视图」等价表述）。
2. 【视角要求】：Multi-angle views showing front view, side view, and back view（正面、侧面、背面）。
3. 【防崩规则】：Stand on a pure white background, arms hanging naturally down, whole body from head to toe, shoes fully in frame, headroom at the top.

## 输出格式

### 【中文提示词】
```text
（一段完整中文提示词）
```

### 【英文提示词】
```text
（一段完整英文提示词）
```
