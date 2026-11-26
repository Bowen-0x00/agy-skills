# agy-skills

**专为 Google Antigravity (`agy`) 打造的 Agent Skills 查看、检索、诊断与管理工具（支持 CLI 命令行、终端交互 TUI 与本地网页控制台）。**

[English](./README.md) | 简体中文

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![零外部依赖](https://img.shields.io/badge/dependencies-zero%20(stdlib)-brightgreen.svg)](#安装方式)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

---

## 为什么需要 `agy-skills`？

当你在 Antigravity (`agy`) 中同时安装了全局 skill、插件（Plugin）、`skills.json` 引入的外部目录（如 `.omp` 或团队共享目录）以及项目工作区 `.agents/skills/` 时，往往很难一眼看清：

1. **当前到底装了哪些 skill？** 哪些生效、哪些被同名高优先级覆盖、哪些被 `skills.json` 排除了？
2. **哪些 skill 必须显式 `/skill-name` 调用**（配置了 `disable-model-invocation: true`），哪些会在每轮对话中自动触发？
3. **每个 skill 具体有什么功能？** 附带了哪些脚本/参考文档？自动触发的 skill 大约占用多少常驻上下文 token？
4. **是否存在隐蔽的配置坑？** 例如写成驼峰 `disableModelInvocation: true` 时，`agy` 实际并不识别，导致原本想显式调用的 skill 仍在悄悄自动触发。

`agy-skills` 基于 **Python 纯标准库** 实现（零第三方依赖），严格复现 `agy` 的多层级发现与优先级覆盖规则，帮你一站式看清并管好所有 skill。

---

## 核心特性

- **精准还原 `agy` 多层发现与优先级规则**：
  1. 工作区逐级向上发现（`.agents/skills`、`.agent/skills`、`_agents/skills`、`_agent/skills`，向上追溯至 `.git` 根目录）
  2. 工作区声明式配置（`.agents/skills.json`、`.agent/skills.json`）
  3. 全局原生目录（`~/.gemini/config/skills/` 及 CLI/IDE 历史全局目录）
  4. 已安装插件（`~/.gemini/config/plugins/*/skills/`，自动识别已禁用插件）
  5. `agy` 内置技能（`~/.gemini/antigravity-cli/builtin/skills/`）
  6. 全局声明式配置（`~/.gemini/config/skills.json`，完整支持 `inherits`、`include_only`、`exclude` 正则/精确过滤）
- **一目了然的调用方式标签**：清晰区分 `自动 + /cmd`、`仅显式 /cmd`（`disable-model-invocation: true`）、`仅自动触发`（`disable-slash-command: true`）、`已覆盖` 与 `已排除`。
- **一键切换显式 / 自动触发**：原子写入 `SKILL.md` 的 YAML frontmatter（完整保留前置 HTML 注释、原有排版与正文），改完在 `agy` 中运行 `/skills reload` 即可生效。
- **配置体检 (`doctor`)**：自动排查同名覆盖、`skills.json` 排除项、驼峰 `disableModelInvocation` 写法告警、损坏符号链接，以及估算常驻上下文 token 预算。
- **三种交互方式**：
  - **CLI 表格**：完美对齐中英文宽度的彩色终端表格，并支持 `--json` 供脚本调用。
  - **终端交互 TUI (`agy-skills tui`)**：纯标准库 `curses` 双栏浏览器，支持实时搜索、按模式筛选、滚动阅读 `SKILL.md` 全文及按键切换调用方式（SSH 远端直接可用）。
  - **本地 Web 看板 (`agy-skills web`)**：仅监听 `127.0.0.1` 的加固单页控制台，支持实时检索、按来源/模式筛选、全文预览、中英文一键切换及带 CSRF 校验的一键切换调用模式。
- **中英双语界面**：支持通过 `--lang zh|en`、`export AGY_SKILLS_LANG=zh` 或 Web 顶部按钮随时切换。

---

## 安装方式

仅需 **Python 3.10+**，无任何第三方依赖。

### 方式一：一键脚本安装（Linux / macOS 推荐）

```bash
curl -fsSL https://raw.githubusercontent.com/Bowen-0x00/agy-skills/main/install.sh | bash
```

自定义安装目录或卸载：

```bash
# 安装到指定目录
curl -fsSL https://raw.githubusercontent.com/Bowen-0x00/agy-skills/main/install.sh | bash -s -- --prefix "$HOME/bin"

# 一键卸载
curl -fsSL https://raw.githubusercontent.com/Bowen-0x00/agy-skills/main/install.sh | bash -s -- --uninstall
```

### 方式二：通过 `pipx` / `uv tool` / `pip` 安装

```bash
# pipx
pipx install git+https://github.com/Bowen-0x00/agy-skills.git

# uv
uv tool install git+https://github.com/Bowen-0x00/agy-skills.git

# pip（用户级安装）
pip install --user git+https://github.com/Bowen-0x00/agy-skills.git
```

### 方式三：克隆源码安装或直接运行

```bash
git clone https://github.com/Bowen-0x00/agy-skills.git
cd agy-skills
pip install -e .
# 或者不安装直接运行单文件：
python3 src/agy_skills/cli.py --lang zh
```

> **提示**：如果想让命令行默认以中文显示，可以在 `~/.bashrc` 或 `~/.zshrc` 中加入：
> ```bash
> export AGY_SKILLS_LANG=zh
> ```

---

## 快速上手

```bash
# 列出当前所有生效的用户/插件 skill（默认隐藏内置 skill）
agy-skills --lang zh

# 仅查看需要显式 /cmd 调用的 skill
agy-skills -e
agy-skills list --explicit

# 仅查看支持自动触发的 skill
agy-skills -a

# 显示内置 skill，或查看全部（含被覆盖、被 skills.json 排除的项）
agy-skills --builtin
agy-skills --all

# 完整换行显示功能说明，或输出 JSON
agy-skills --full
agy-skills list --all --json

# 按来源筛选（global | plugin | declared | workspace | builtin | omp）
agy-skills list --source plugin

# 按关键词搜索名称与功能说明（加 --body 可同时检索 SKILL.md 正文）
agy-skills search 引用
agy-skills search latex --body

# 查看单个 skill 详情（路径、软链目标、附带脚本与参考文档列表、告警）
agy-skills show citation-grounding-checker
agy-skills show citation-grounding-checker --body

# 一键切换调用模式（explicit 仅显式 / auto 自动触发 / toggle 翻转）
# 修改后请在 agy 中运行 /skills reload 使其生效
agy-skills mode citation-grounding-checker auto
agy-skills mode paper-review-polisher explicit
agy-skills mode paper-review-polisher toggle

# 运行健康诊断（同名覆盖、frontmatter 告警、常驻 token 估算）
agy-skills doctor

# 打开终端交互式 TUI 面板
agy-skills tui

# 启动本地 Web 控制台（默认端口 8765，仅监听 127.0.0.1）
agy-skills web
agy-skills web --port 9000
```

> **SSH 远端访问 Web 面板提示**：在远程 Linux 主机运行 `agy-skills web` 后，在本地执行端口转发即可通过浏览器安全访问：
> ```bash
> ssh -L 8765:127.0.0.1:8765 user@your-host
> ```
> 然后在本地浏览器打开 `http://127.0.0.1:8765`。

### 终端 TUI 快捷键 (`agy-skills tui`)

| 按键 | 功能 |
| :--- | :--- |
| `↑` / `↓` 或 `j` / `k` | 上下选择 skill |
| `/` | 实时关键词搜索（`Enter` 确认，`Esc` 清空） |
| `e` / `t` / `a` | 筛选：仅显式 `/cmd` / 仅自动触发 / 全部模式 |
| `b` / `x` | 切换显示：内置 skill / 被覆盖与排除项 |
| `v` 或 `Enter` | 弹出可滚动的 `SKILL.md` 全文阅读视图 |
| `m` | 切换 `disable-model-invocation`（带 `y`/`n` 确认） |
| `r` | 重新扫描磁盘 |
| `q` | 退出 |

---

## 安全设计（`agy-skills web`）

- **严格本地回环绑定**：仅监听 `127.0.0.1`，绝不暴露公网/局域网端口。
- **严格安全响应头**：每请求随机生成 CSP `nonce`（禁用 `unsafe-inline` / `unsafe-eval`），同时配置 `X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`、`Cache-Control: no-store`。
- **写操作防护**：`POST /api/mode` 强制校验 `Origin`、每会话随机生成的 CSRF Token、速率限制与 HTTP 方法白名单（仅允许 `GET`/`POST`）。
- **防路径穿越与防 XSS**：服务端只允许通过已发现 skill 注册表 ID 定位文件并校验目录边界；前端完全使用 `document.createElement` + `textContent` 渲染（零 `innerHTML`、零原生弹窗）。

---

## 本地测试

```bash
python3 -m unittest discover -s tests -v
```

---

## 开源协议

基于 [MIT License](./LICENSE) 开源。

---

🌐 Looking for English documentation? See [README.md](./README.md).
