# RepoWiki 增量同步方案：让代码文档持续跟踪代码变更

> 状态：设计稿（2026-06-11）
> 目标：把当前一次性的 `REPOWIKI.md` 全量生成，升级为「持续跟踪代码与文档变更」的能力，借鉴通义灵码 Repo Wiki 的架构，适配本项目的 Claude Code + `repowiki` 工具链。

---

## 1. 背景与问题

当前用 [`repowiki`](https://github.com/zzzhizhia/repowiki)（CLI 调用 `claude --model opus --print`）生成的 `REPOWIKI.md` 有两个硬伤：

1. **不自动更新**：代码改了，文档不会变，必须手动重跑 `repowiki`。
2. **全量覆盖**：每次都从头分析整个仓库、整文件覆盖，慢、贵，且会冲掉人工修订。

通义灵码（[Qoder CN](https://help.aliyun.com/zh/lingma/qoder-cn/user-guide/repo-wiki) / [Qoder](https://docs.qoder.com/user-guide/repo-wiki)）的 Repo Wiki 已经解决了这个问题，核心是三件事：**按模块拆多文件**、**文档自带依赖声明**、**独立同步状态文件**。本方案把这三件事搬到本项目。

---

## 2. 目标架构：三支柱

```
┌──────────────────────────────────────────────────────────────┐
│  支柱 A：分模块多文件      docs/wiki/<module>.md 一模块一文件  │
│  支柱 B：依赖声明 (cite)   每个文件声明引用哪些源文件           │
│  支柱 C：同步状态 (meta)   记录 lastSync / 文件指纹 / 生成元数据│
└──────────────────────────────────────────────────────────────┘
         ↑
   三种触发：① 初次全量  ② 代码增量  ③ 文档手动编辑同步
```

**核心思想**：把「模块」作为一等公民——一个模块 = 一个 `.md` 文件 = 一份 cite 依赖声明。增量、定位、回滚全部围绕模块做，而不是围绕单文件里的章节做。

---

## 3. 目录结构（落地后）

```
docs/wiki/
├── _overview.md              # 项目总览 + 架构图（跨模块，特殊）
├── service-worker.md         # 扩展后台
├── content-script.md         # 内容脚本 + zhipin DOM
├── popup-ui.md               # 扩展弹窗
├── panel-ui.md               # 浮动面板
├── shared.md                 # 共享层（类型/存储/API/加密）
├── backend-api.md            # FastAPI 后端
├── web-app.md                # Next.js 官网
├── python-prototype.md       # boss_apply.py 原型
└── .wiki-meta.json           # 同步状态（支柱 C）
```

> 旧的 `REPOWIKI.md` 在迁移完成后可保留为「合并只读快照」或删除。

---

## 4. 核心机制详细设计

### 4.1 模块怎么自动切分

#### 切分原则
- **以子系统为顶层边界**，子系统内按职责目录切。
- **单模块规模上限**：源码 ≈ 2000 行 或 ≈ 15 个文件，超出则下钻一层再切。
- **跨模块关系**单独记录（依赖图），不靠把多个模块塞进一个文件来表达。

#### 自动切分算法（分层）

```
L1 子系统识别（按标志文件）
├─ manifest.json + src/background/        → 扩展子系统
├─ app/main.py + requirements.txt (FastAPI)→ 后端子系统
├─ next.config.* + package.json           → Web 子系统
└─ 顶层独立脚本 *.py                       → 独立模块

L2 子系统内切分（按约定目录 / 入口）
├─ 扩展 → background / content(+zhipin) / popup / panel / shared
├─ 后端 → 默认整体；若 routers/ + services/ 行数超阈，按 router 切
└─ Web  → 默认整体；若 app/ 路由很多，按 route group 切

L3 规模控制
└─ 估算每个候选模块的源码行数，超 2000 行 → 按 L2 的下一级目录再拆
```

#### 本项目的切分结果（已用 REPOWIKI Module Inventory 校验）

| 模块 ID | 文档文件 | 源码根 | 来源 |
|---------|---------|--------|------|
| `service-worker` | service-worker.md | `bossbot/extension/src/background/` | REPOWIKI L132 |
| `content-script` | content-script.md | `bossbot/extension/src/content/`（含 `zhipin/`） | L133-134 |
| `popup-ui` | popup-ui.md | `bossbot/extension/src/popup/` | L135 |
| `panel-ui` | panel-ui.md | `bossbot/extension/src/panel/` | L136 |
| `shared` | shared.md | `bossbot/extension/src/shared/` | L137 |
| `backend-api` | backend-api.md | `bossbot/backend/app/` | L138 |
| `web-app` | web-app.md | `bossbot/web/src/` | L139 |
| `python-prototype` | python-prototype.md | `boss_apply.py` | 顶层 |
| `_overview` | _overview.md | （跨模块聚合） | 新增 |

#### 重切分策略
- 切分配置（模块 ID → 源码根的映射）存进 `.wiki-meta.json` 的 `moduleMap`。
- 若后续 L3 触发再拆，新增模块 ID 时**保留旧 ID 的文档**（重命名而非删除），避免历史丢失。
- 切分变化本身要在 `_overview.md` 里记一笔变更说明。

---

### 4.2 cite 依赖声明的精确格式

cite 解决「源文件变了 → 找到该更新哪些文档」。两种范式，二选一：

#### 范式 A：YAML front matter 一体化（**推荐**）

把 cite + 该模块的生成元数据合并进每个 `.md` 顶部的 front matter。单一数据源、自包含、不污染正文（front matter 不渲染）。

```markdown
---
module: service-worker
title: "Service Worker（后台任务编排）"
cite:                          # 依赖声明：本模块文档引用的源文件
  - path: bossbot/extension/src/background/task-queue.ts
    blob: a1b2c3d4             # git blob hash，内容变才触发更新
    role: core                 # core=主线 / support=辅助
  - path: bossbot/extension/src/background/subscription.ts
    blob: e5f6g7h8
    role: support
generated:                     # 该文档上次怎么生成的
  model: opus
  commit: 01d0cd5
  at: 2026-06-11T18:06:00+08:00
  tool: repowiki-sync@0.1.0
---

# Service Worker（后台任务编排）

正文……（人可读，机器不碰）
```

**字段语义**
| 字段 | 作用 |
|------|------|
| `cite[].path` | 依赖的源文件（=影响定位的反向索引键） |
| `cite[].blob` | 该源文件的 git blob hash；`git cat-file` 可取，变了即「内容级变更」 |
| `cite[].role` | core 的文件改动必触发更新；support 的改动可降级为 sonnet 轻更新 |
| `generated.*` | 复现/审计用：哪个 commit、什么模型生成的 |

#### 范式 B：灵码式（文档内 cite 块 + 外部 meta）

与通义灵码完全一致，便于互操作。文档正文顶部放可见块，状态进单独 meta 文件：

```markdown
<cite>
**本文档引用的文件**
- [background/task-queue.ts](file://bossbot/extension/src/background/task-queue.ts)
- [background/subscription.ts](file://bossbot/extension/src/background/subscription.ts)
</cite>
```

#### 取舍

| 维度 | 范式 A（front matter，推荐） | 范式 B（灵码式） |
|------|----------------------------|-----------------|
| 数据源 | 单一（自包含） | 两处（cite 在文档、指纹在 meta） |
| 可读性 | front matter 不渲染，正文干净 | cite 块可见，对人友好 |
| 解析 | 标准 YAML | 需正则解析 `<cite>` |
| 互操作 | 自定义 | 与通义灵码 `.lingma/repowiki` 结构一致 |
| 人工编辑正文 | 不碰 front matter 即可 | 不碰 cite 块即可 |

> **本项目默认选范式 A**：个人/小团队项目，自包含优先。若未来要和灵码共享同一套 wiki 目录，再切范式 B。

#### 解析方式
- 范式 A：任意 YAML 解析器（`js-yaml`）读 front matter。
- 影响定位查询：「`task-queue.ts` 改了 → 哪些文档 cite 了它？」= 遍历 `docs/wiki/*.md` 的 front matter，匹配 `cite[].path`。一条 shell 即可：
  ```bash
  grep -rl "task-queue.ts" docs/wiki/*.md   # 粗匹配；精确用 front matter 解析
  ```

---

### 4.3 meta 文件存什么（`.wiki-meta.json`）

存「跨模块的全局同步状态」。即使选范式 A（每文件 front matter 存自己的 cite/blob），仍需要一个全局文件记录「上次同步到哪个 commit」。范式 B 下它还额外承载每文件的指纹。

#### 精确 Schema

```json
{
  "version": 1,
  "lastSyncCommit": "01d0cd5",
  "lastSyncAt": "2026-06-11T18:06:00+08:00",
  "generator": { "tool": "repowiki-sync", "version": "0.1.0" },
  "moduleMap": {
    "service-worker": "bossbot/extension/src/background/",
    "content-script": "bossbot/extension/src/content/",
    "popup-ui":      "bossbot/extension/src/popup/",
    "panel-ui":      "bossbot/extension/src/panel/",
    "shared":        "bossbot/extension/src/shared/",
    "backend-api":   "bossbot/backend/app/",
    "web-app":       "bossbot/web/src/",
    "python-prototype": "boss_apply.py",
    "_overview":     null
  },
  "modules": {
    "service-worker": {
      "doc": "docs/wiki/service-worker.md",
      "docChecksum": "sha256:9f2c...",
      "sources": [
        { "path": "bossbot/extension/src/background/task-queue.ts", "blob": "a1b2c3d4" },
        { "path": "bossbot/extension/src/background/subscription.ts", "blob": "e5f6g7h8" }
      ],
      "generatedWith": { "model": "opus", "commit": "01d0cd5" }
    }
  }
}
```

#### 字段语义与用途

| 字段 | 用途 |
|------|------|
| `lastSyncCommit` | 下次增量基准：`git diff <lastSyncCommit>..HEAD` |
| `lastSyncAt` | 审计/展示「文档新鲜度」 |
| `moduleMap` | 模块 ID → 源码根（4.1 切分结果），增量定位的第一步 |
| `modules[m].sources[].blob` | 每个源文件的 git blob hash；范式 A 下与 front matter 冗余，作权威副本 |
| `modules[m].docChecksum` | 文档自身的 sha256；检测「人手动改过文档」（触发③ Git 同步场景） |
| `modules[m].generatedWith` | 该模块上次用什么模型生成 → 决定下次增量路由（见 §5） |

#### 为什么单独文件（不全部塞进每个 .md）
- `lastSyncCommit`、`moduleMap` 是**全局**状态，不属于任何单模块。
- 范式 B 下还要集中存所有 blob，便于一次性 `git diff` 比对，而不必遍历每个 .md。
- 与通义灵码的 `repowiki/…/meta` 对齐：**机器管 meta，人管正文**。

---

## 5. 三种触发的工作流

| # | 触发 | 输入 | 动作 | 模型路由 |
|---|------|------|------|---------|
| ① | 初次生成 | 空仓库 / 无 wiki | 跑 §4.1 切分 → 对每个模块调 claude 生成 → 写 front matter + meta | **opus**（全量） |
| ② | 代码增量 | `git diff <lastSync>..HEAD` | diff 路径 → 查 `moduleMap` → 命中模块 → 反查 cite 确认 → **只重写命中模块的 .md** → 更新其 front matter + meta 的 lastSync | core 改动→**opus**；support 小改→**sonnet** |
| ③ | 文档手动编辑 | `docChecksum` 与磁盘不符 | 读改动 → 让 claude 基于改动重生成或合并 → 重算 checksum | sonnet |

#### 增量模型路由（成本/质量平衡）
```
diff 触及模块的 cite.role=core 文件？
  ├─ 是 → opus 重写该模块文档
  └─ 否 → sonnet 轻量更新该模块文档
每累计 N 次增量（如 10 次）→ 跑一次 opus 全量校准，消除累积漂移
```

#### 关键护栏
- 单次增量 diff > 10,000 行 → 降级提示「变更过大，建议手动全量」（对齐灵码红线）。
- 每次文档更新 = **独立 git commit**（`docs(wiki): sync service-worker after task-queue refactor`），便于 `git revert` 回滚，不与代码改动混淆。
- `docs/wiki/` 与 `.wiki-meta.json` 都纳入 git，团队 `git pull` 即享。

---

## 6. 落地步骤（分阶段）

1. **P0 手摇增量**：写 `scripts/wiki-sync/sync.mjs`（≈150 行），实现 ②：`git diff` + `moduleMap` + 反查 cite + 调 `claude --print` 重写命中模块。范式 A front matter。先不接 hook，`npm run wiki:sync` 手动跑。
2. **P1 自动化**：加 husky `post-commit` 或 GitHub Actions，commit/push 后自动跑 P0 的 sync。
3. **P2 漂移检测**：`scripts/wiki-sync/drift.mjs`——从代码提取结构事实（FastAPI 端点 `@router.*`、manifest、`constants.ts` tier）与文档表格对账，CI 里 PR 评论标注过时章节。

---

## 7. 待决策点 / 风险

| 决策 | 选项 | 倾向 |
|------|------|------|
| cite 范式 | A front matter / B 灵码式 | **A** |
| 模块切分配置 | 纯自动 / 自动+人工覆盖 | 自动 + `.wiki-meta.json` 可手改覆盖 |
| 旧 `REPOWIKI.md` 去留 | 保留为快照 / 删除 | 保留一个合并快照，标「generated, see docs/wiki/」 |
| 增量触发 | 手动 / hook / CI | 先手动（P0），再加 CI（P1） |
| CI 文档更新方式 | 自动提交 / PR 评论 | **PR 评论**（文档改动值得 review） |

**风险**
- **增量漂移**：每次小改可能丢一点上下文 → 靠 §5 的「N 次后 opus 全量校准」对冲。
- **blob 是内容级而非语义级**：改注释也会触发更新。可接受；若太吵，后续引入 AST 级 diff（详见 §7.1）。
- **cite 维护**：新增源文件没进 cite 就会漏更新 → 首次生成时让 claude 尽量列全 + 漂移检测兜底。

### 7.1 变更检测粒度：blob → strip → AST

cite 的 `blob` 字段用 git blob hash 做**内容级**变更检测。三档粒度：

| 档位 | 比的是什么 | 实现 | 改注释会触发？ |
|------|-----------|------|--------------|
| **blob（内容级）** | 文件字节内容 | `git hash-object <file>` | ✅ 会（误报） |
| strip comments | 去注释/空白后的内容 | 正则剥注释再 hash | ❌ 不会 |
| **AST（语义级）** | 代码结构（签名/导出） | 语言 parser 提取签名指纹 | ❌ 不会 |

**为什么先用 blob**：漏报（代码真变、文档没更新）危险，误报（只改注释、白更新一次）无害——blob 是"宁错杀不放过"，且一行命令、零依赖、全语言通用。

**什么时候嫌吵**：全仓库 `prettier` / `eslint --fix` 格式化、大规模 rename、批量加版权头等无语义改动，会让几乎所有文件 blob 都变，触发一堆没必要的文档更新。

**AST 升级示意**（TS，提取签名指纹而非比字节）：

```ts
function signatureHash(file: SourceFile): string {
  const sigs = file.getFunctions().map(f => ({
    name: f.getName(),
    params: f.getParameters().map(p => p.getType().getText()),
    exports: f.isExported(),
  })); // + 类、接口、导出常量签名
  return sha256(JSON.stringify(sigs));
}
```

TS/JS 用 `ts-morph`，Python 用标准库 `ast` 或 `libcst`。

**本项目建议**：P0/P1 先用 blob；等真碰到一次"格式化刷爆 blob、文档疯狂重生"，再在 P2 漂移检测层加 AST 指纹——届时已有 `moduleMap` 和源文件清单，加一个 `signatureHash` 顺理成章。不要一开始就上 AST，属没遇到噪声就过早优化。

---

## 8. 对照表

| 维度 | repowiki（现状） | 通义灵码 Repo Wiki | 本方案 |
|------|-----------------|-------------------|--------|
| 文档结构 | 单文件 | 分模块多文件 | **分模块多文件** |
| 依赖定位 | 无 | 文档内 `<cite>` | front matter `cite`（范式 A） |
| 同步状态 | 无 | 外部 `meta` | `.wiki-meta.json` |
| 更新方式 | 全量覆盖 | 三场景增量 | **三场景增量** |
| 触发 | 手动命令 | IDE 持续监控 | 手动 → CI（P1） |
| 漂移检测 | 无 | 无 | **有**（P2） |
| 成本控制 | 固定 opus | 消耗 Credits | core→opus / support→sonnet 路由 |

---

## 9. 参考来源

- [Repo Wiki – 通义灵码（Qoder CN）阿里云文档](https://help.aliyun.com/zh/lingma/qoder-cn/user-guide/repo-wiki)
- [Repo Wiki – Qoder 官方文档（国际版）](https://docs.qoder.com/user-guide/repo-wiki)
- [配置代码库索引（增量索引机制）– 通义灵码](https://help.aliyun.com/zh/lingma/qoder-cn/user-guide/index)
- [repowiki CLI – GitHub](https://github.com/zzzhizhia/repowiki)
