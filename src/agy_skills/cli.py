#!/usr/bin/env python3
"""agy-skills: Skill inspector and manager for Google Antigravity (agy).

Pure Python standard-library tool (zero external dependencies) that mirrors
Antigravity's customization discovery and precedence rules:
  1. Workspace hierarchical (.agents/skills, .agent/skills, _agents/skills, _agent/skills)
  2. Workspace declared (skills.json)
  3. Global native (~/.gemini/config/skills and legacy CLI/IDE locations)
  4. Installed plugins (~/.gemini/config/plugins/*/skills)
  5. Built-in skills (~/.gemini/antigravity-cli/builtin/skills)
  6. Global declared (~/.gemini/config/skills.json with inherits/include_only/exclude)
"""

from __future__ import annotations

import argparse
import dataclasses
import html
import http.server
import json
import locale
import os
import pathlib
import re
import secrets
import shutil
import socketserver
import sys
import tempfile
import time
import unicodedata
import urllib.parse
from typing import Any


VERSION = "1.0.0"

WORKSPACE_DOT_DIRS = (".agents", ".agent", "_agents", "_agent")

SOURCE_ORDER = {
    "workspace": 1,
    "workspace-json": 2,
    "global": 3,
    "global-cli": 3,
    "global-legacy": 3,
    "global-ide": 3,
    "plugin": 4,
    "builtin": 5,
    "declared": 6,
}

SOURCE_LABELS = {
    "workspace": "Workspace",
    "workspace-json": "Workspace JSON",
    "global": "Global",
    "global-cli": "Global (CLI)",
    "global-legacy": "Global (Legacy)",
    "global-ide": "Global (IDE)",
    "plugin": "Plugin",
    "builtin": "Built-in",
    "declared": "skills.json",
}

I18N: dict[str, dict[str, str]] = {
    "en": {
        "mode_auto_slash": "auto + /cmd",
        "mode_explicit": "explicit /cmd",
        "mode_auto_only": "auto-only",
        "mode_disabled": "disabled",
        "status_shadowed": "shadowed",
        "status_excluded": "excluded",
        "status_plugin_disabled": "plugin-off",
        "hdr_overview": "Antigravity Skills | Shown: {shown} | Auto: {auto} | Explicit /cmd: {explicit} | Est. resident: ~{tokens} tokens",
        "no_match": "  (no skills matched the current filters)",
        "col_name": "SKILL NAME",
        "col_mode": "INVOCATION",
        "col_source": "SOURCE",
        "col_res": "ASSETS",
        "col_desc": "DESCRIPTION",
        "no_desc": "(no description)",
        "shadowed_tag": "shadowed by",
        "hint_builtin": "{n} built-in skills hidden (use --builtin to include)",
        "hint_inactive": "{n} shadowed/excluded entries (use --all to include)",
        "hint_cmds": "Details: agy-skills show <name> | Toggle: agy-skills mode <name> explicit|auto | Interactive: agy-skills tui / web",
        "hint_prefix": "Tip: ",
        "not_found": "Skill '{name}' not found.",
        "not_active": "No active skill named '{name}' found.",
        "readonly_err": "'{name}' belongs to a read-only source ({source}). Pass --force to override.",
        "mode_updated": "[OK] Updated '{name}' -> {mode}",
        "mode_file": "     File: {path}",
        "mode_reload": "     Tip: Run /skills reload in agy (or start a new session) to apply.",
        "mode_noop": "[NO-OP] '{name}' is already set to '{mode}'.",
        "show_mode": "Invocation",
        "show_slash": "Slash cmd",
        "show_slash_off": "(slash command disabled)",
        "show_status": "Status",
        "show_source": "Source",
        "show_real": "Resolved",
        "show_tokens": "Est. cost",
        "show_tokens_note": "~{tokens} tokens (injected only when auto-triggered)",
        "show_desc": "Description",
        "show_scripts": "Scripts",
        "show_refs": "References",
        "show_warns": "Warnings",
        "show_dups": "Other copies with same name",
        "show_body": "--- SKILL.md full content ---",
        "doc_title": "=== agy-skills Diagnostics ===",
        "doc_total": "Active skills    : {total} (user/plugin: {user}, built-in: {builtin})",
        "doc_auto": "Auto-triggered   : {n} (est. ~{tokens} resident tokens/turn)",
        "doc_explicit": "Explicit (/cmd)  : {n} (0 resident prompt cost)",
        "doc_inactive": "Shadowed/Excl.   : {shadowed} shadowed, {excluded} excluded by skills.json",
        "doc_warn_hdr": "\n[Warnings] Frontmatter or configuration issues:",
        "doc_warn_path": "    Path: {path}",
        "doc_ok": "\n[OK] All active skills have clean, valid frontmatter.",
        "doc_shadow_hdr": "\n[Info] Shadowed duplicates (higher priority active):",
        "doc_excl_hdr": "\n[Info] Excluded by skills.json:",
        "warn_missing_fm": "Missing standard YAML frontmatter (--- ... ---)",
        "warn_missing_desc": "Frontmatter is missing the 'description' field",
        "warn_camel_dmi": "Uses camelCase 'disableModelInvocation: true'; agy only recognizes kebab-case 'disable-model-invocation: true' (still auto-triggered in agy)",
        "warn_broken_link": "Broken symlink -> {target}",
        "warn_excluded": "Excluded by {file} include_only/exclude rules",
        "broken_link_desc": "(broken symlink; target does not exist)",
        "tui_no_curses": "Error: Python 'curses' is unavailable on this platform. Use `agy-skills list` or `agy-skills web` instead.",
        "tui_no_tty": "Error: `agy-skills tui` requires an interactive terminal.",
        "web_started": "agy-skills local dashboard running at: {url}",
        "web_hint": "Bound strictly to 127.0.0.1 (over SSH, forward with: ssh -L {port}:127.0.0.1:{port} <host>). Press Ctrl+C to stop.",
        "web_stopped": "\nStopped agy-skills web dashboard.",
    },
    "zh": {
        "mode_auto_slash": "自动 + /cmd",
        "mode_explicit": "仅显式 /cmd",
        "mode_auto_only": "仅自动触发",
        "mode_disabled": "已禁用",
        "status_shadowed": "已覆盖",
        "status_excluded": "已排除",
        "status_plugin_disabled": "插件禁用",
        "hdr_overview": "Antigravity Skills 概览 | 当前展示: {shown} | 自动触发: {auto} | 仅显式 /cmd: {explicit} | 常驻元数据估算: ~{tokens} tokens",
        "no_match": "  (没有符合筛选条件的 skill)",
        "col_name": "SKILL 名称",
        "col_mode": "调用方式",
        "col_source": "来源",
        "col_res": "资源",
        "col_desc": "功能说明",
        "no_desc": "(无说明)",
        "shadowed_tag": "被覆盖",
        "hint_builtin": "另有 {n} 个 agy 内置 skill（加 --builtin 查看）",
        "hint_inactive": "{n} 个被覆盖/排除项（加 --all 查看）",
        "hint_cmds": "查看详情: agy-skills show <名称> | 切换模式: agy-skills mode <名称> explicit|auto | 交互界面: agy-skills tui / web",
        "hint_prefix": "提示: ",
        "not_found": "未找到名为 '{name}' 的 skill。",
        "not_active": "未找到处于生效状态的 skill '{name}'。",
        "readonly_err": "'{name}' 属于只读来源 ({source})，默认拒绝修改（如确需修改请加 --force）。",
        "mode_updated": "[OK] 已将 '{name}' 切换为：{mode}",
        "mode_file": "     文件: {path}",
        "mode_reload": "     提示: 请在 agy 中运行 /skills reload（或新开会话）使其生效。",
        "mode_noop": "[NO-OP] '{name}' 已经是「{mode}」。",
        "show_mode": "调用方式",
        "show_slash": "斜杠命令",
        "show_slash_off": "(已禁用斜杠命令)",
        "show_status": "生效状态",
        "show_source": "来源路径",
        "show_real": "真实目标",
        "show_tokens": "常驻估算",
        "show_tokens_note": "~{tokens} tokens (仅自动触发时注入系统提示)",
        "show_desc": "功能说明",
        "show_scripts": "附带脚本",
        "show_refs": "参考资料",
        "show_warns": "诊断提醒",
        "show_dups": "同名其他副本",
        "show_body": "--- SKILL.md 全文 ---",
        "doc_title": "=== agy-skills 健康诊断 ===",
        "doc_total": "生效 Skill 总数  : {total} (用户/插件: {user}, 内置: {builtin})",
        "doc_auto": "自动触发 (常驻)  : {n} 个 (估算常驻元数据约 ~{tokens} tokens/轮)",
        "doc_explicit": "仅显式调用(/cmd) : {n} 个 (0 常驻上下文开销)",
        "doc_inactive": "被覆盖 / 已排除  : {shadowed} 被覆盖, {excluded} 被 skills.json 排除",
        "doc_warn_hdr": "\n[警告] 需关注的 frontmatter / 配置问题:",
        "doc_warn_path": "    路径: {path}",
        "doc_ok": "\n[OK] 所有生效 skill 的 frontmatter 均规范无告警。",
        "doc_shadow_hdr": "\n[信息] 同名覆盖列表 (高优先级已生效):",
        "doc_excl_hdr": "\n[信息] 被 skills.json 排除列表:",
        "warn_missing_fm": "缺少标准 YAML frontmatter (--- ... ---)",
        "warn_missing_desc": "frontmatter 缺少 description 字段",
        "warn_camel_dmi": "检测到驼峰字段 disableModelInvocation: true，agy 仅识别连字符 disable-model-invocation: true（当前实际仍会自动触发）",
        "warn_broken_link": "损坏的符号链接 -> {target}",
        "warn_excluded": "已被 {file} exclude/include_only 规则过滤",
        "broken_link_desc": "(损坏的符号链接，目标不存在)",
        "tui_no_curses": "错误: 当前平台未内置 Python curses 模块，请改用 `agy-skills list` 或 `agy-skills web`。",
        "tui_no_tty": "错误: `agy-skills tui` 需要在交互式终端中运行。",
        "web_started": "agy-skills 本地控制台已启动: {url}",
        "web_hint": "仅监听 127.0.0.1（如通过 SSH 连接，可做端口转发: ssh -L {port}:127.0.0.1:{port} <host>），按 Ctrl+C 停止。",
        "web_stopped": "\n已停止 agy-skills Web 控制台。",
    },
}


def resolve_lang(cli_lang: str | None = None) -> str:
    if cli_lang in ("en", "zh"):
        return cli_lang
    env_lang = (os.environ.get("AGY_SKILLS_LANG") or "").strip().lower()
    if env_lang.startswith("zh"):
        return "zh"
    if env_lang.startswith("en"):
        return "en"
    sys_locale = (os.environ.get("LC_ALL") or os.environ.get("LANG") or "").lower()
    if sys_locale.startswith("zh"):
        return "zh"
    return "en"


def tr(lang: str, key: str, **kwargs: Any) -> str:
    table = I18N.get(lang, I18N["en"])
    tmpl = table.get(key, I18N["en"].get(key, key))
    return tmpl.format(**kwargs) if kwargs else tmpl


@dataclasses.dataclass
class SkillRecord:
    id: str
    name: str
    folder_name: str
    description: str
    invocation_mode: str  # auto+slash | explicit | auto-only | disabled
    disable_model_invocation: bool
    disable_slash_command: bool
    source_kind: str  # workspace | workspace-json | global | plugin | builtin | declared
    source_detail: str
    priority: int
    status: str  # active | shadowed | excluded | plugin-disabled
    shadowed_by: str | None
    skill_md_path: str
    resolved_path: str
    is_symlink: bool
    editable: bool
    scripts: list[str]
    references: list[str]
    warnings: list[str]
    metadata: dict[str, Any]
    est_resident_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Frontmatter Parser & Atomic Editor (pure stdlib, handles leading comments)
# ---------------------------------------------------------------------------

def _unquote_yaml_scalar(val: str) -> str:
    s = val.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        inner = s[1:-1]
        return (
            inner.replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("\\\\", "\\")
        )
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


def _parse_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "yes", "on", "1")
    return False


def locate_frontmatter_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Return (start_idx, end_idx) of '---' delimiters, skipping leading HTML comments."""
    idx = 0
    n = len(lines)
    while idx < n:
        stripped = lines[idx].strip()
        if not stripped:
            idx += 1
            continue
        if stripped.startswith("<!--"):
            while idx < n and "-->" not in lines[idx]:
                idx += 1
            idx += 1
            continue
        break
    if idx >= n or lines[idx].strip() != "---":
        return None
    end = idx + 1
    while end < n:
        if lines[end].strip() in ("---", "..."):
            return (idx, end)
        end += 1
    return None


def parse_frontmatter(text: str, lang: str = "en") -> tuple[dict[str, Any], str, list[str]]:
    """Parse YAML frontmatter from SKILL.md using Python stdlib only."""
    lines = text.splitlines()
    bounds = locate_frontmatter_bounds(lines)
    warnings: list[str] = []
    if bounds is None:
        warnings.append(tr(lang, "warn_missing_fm"))
        return {}, text, warnings

    start, end = bounds
    fm_lines = lines[start + 1 : end]
    body = "\n".join(lines[end + 1 :]).lstrip("\n")

    data: dict[str, Any] = {}
    i = 0
    total = len(fm_lines)
    while i < total:
        raw = fm_lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", raw)
        if not m:
            i += 1
            continue
        key = m.group(1)
        rest = m.group(2).strip()

        if rest in (">", ">-", ">+", "|", "|-", "|+"):
            is_folded = rest.startswith(">")
            block_lines: list[str] = []
            i += 1
            base_indent: int | None = None
            while i < total:
                nxt = fm_lines[i]
                if not nxt.strip():
                    block_lines.append("")
                    i += 1
                    continue
                indent = len(nxt) - len(nxt.lstrip(" "))
                if indent == 0:
                    break
                if base_indent is None:
                    base_indent = indent
                block_lines.append(nxt[min(indent, base_indent) :])
                i += 1
            while block_lines and block_lines[-1] == "":
                block_lines.pop()
            if is_folded:
                paragraphs: list[str] = []
                buf: list[str] = []
                for bl in block_lines:
                    if bl == "":
                        if buf:
                            paragraphs.append(" ".join(buf))
                            buf = []
                    else:
                        buf.append(bl.strip())
                if buf:
                    paragraphs.append(" ".join(buf))
                data[key] = "\n".join(paragraphs).strip()
            else:
                data[key] = "\n".join(block_lines).strip()
            continue

        if rest == "":
            nested: dict[str, str] = {}
            i += 1
            while i < total:
                nxt = fm_lines[i]
                if not nxt.strip():
                    i += 1
                    continue
                if not nxt.startswith(" ") and not nxt.startswith("\t"):
                    break
                nm = re.match(r"^\s+([A-Za-z0-9_-]+)\s*:\s*(.*)$", nxt)
                if nm:
                    nested[nm.group(1)] = _unquote_yaml_scalar(nm.group(2))
                i += 1
            data[key] = nested
            continue

        if rest[0] in ('"', "'") and not (len(rest) >= 2 and rest[-1] == rest[0] and not rest.endswith("\\" + rest[0])):
            quote_char = rest[0]
            acc = [rest]
            i += 1
            while i < total:
                acc.append(fm_lines[i].strip())
                if fm_lines[i].rstrip().endswith(quote_char):
                    i += 1
                    break
                i += 1
            data[key] = _unquote_yaml_scalar(" ".join(acc))
            continue

        val_str = _unquote_yaml_scalar(rest)
        if rest.lower() in ("true", "false"):
            data[key] = rest.lower() == "true"
        else:
            data[key] = val_str
        i += 1

    return data, body, warnings


def update_disable_model_invocation(skill_md: pathlib.Path, explicit: bool) -> bool:
    """Atomically toggle `disable-model-invocation: true` in SKILL.md frontmatter."""
    raw = skill_md.read_text(encoding="utf-8")
    had_trailing_nl = raw.endswith("\n")
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    bounds = locate_frontmatter_bounds(lines)
    if bounds is None:
        raise ValueError("Missing standard YAML frontmatter (--- ... ---).")

    start, end = bounds
    fm_lines = lines[start + 1 : end]
    key_re = re.compile(r"^disable-model-invocation\s*:\s*.*$")
    camel_re = re.compile(r"^disableModelInvocation\s*:\s*.*$")

    existing_indices = [idx for idx, ln in enumerate(fm_lines) if key_re.match(ln)]
    camel_indices = [idx for idx, ln in enumerate(fm_lines) if camel_re.match(ln)]

    new_fm = list(fm_lines)
    changed = False

    if explicit:
        if existing_indices:
            first_i = existing_indices[0]
            if new_fm[first_i].strip() != "disable-model-invocation: true":
                new_fm[first_i] = "disable-model-invocation: true"
                changed = True
            for dup_i in reversed(existing_indices[1:]):
                new_fm.pop(dup_i)
                changed = True
        else:
            insert_at = 0
            for idx, ln in enumerate(new_fm):
                if re.match(r"^name\s*:", ln):
                    insert_at = idx + 1
                    break
            new_fm.insert(insert_at, "disable-model-invocation: true")
            changed = True
    else:
        for idx in reversed(existing_indices):
            new_fm.pop(idx)
            changed = True
        for idx in reversed(camel_indices):
            new_fm.pop(idx)
            changed = True

    if not changed:
        return False

    new_lines = lines[: start + 1] + new_fm + lines[end:]
    new_text = newline.join(new_lines) + (newline if had_trailing_nl else "")

    real_target = skill_md.resolve()
    fd, tmp_name = tempfile.mkstemp(prefix=".skill_tmp_", dir=str(real_target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        try:
            shutil.copymode(real_target, tmp_name)
        except OSError:
            pass
        os.replace(tmp_name, real_target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return True


# ---------------------------------------------------------------------------
# Discovery Engine (mirrors Antigravity customization rules)
# ---------------------------------------------------------------------------

def _find_repo_root(start: pathlib.Path) -> pathlib.Path | None:
    cur = start.resolve()
    while True:
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent


def _resolve_config_path(
    raw_path: str,
    base_dir: pathlib.Path,
    repo_root: pathlib.Path | None,
    home: pathlib.Path,
) -> pathlib.Path:
    if raw_path == "~":
        return home
    if raw_path.startswith("~/"):
        return home / raw_path[2:]
    p = pathlib.Path(raw_path)
    if p.is_absolute():
        return p
    cand = base_dir / p
    if cand.exists():
        return cand
    if repo_root is not None:
        return repo_root / p
    return cand


def _matches_any_pattern(name: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if not pat:
            continue
        if name == pat:
            return True
        try:
            if re.fullmatch(pat, name) or re.search(pat, name):
                return True
        except re.error:
            if pat in name:
                return True
    return False


def _load_disabled_plugins(config_json: pathlib.Path) -> set[str]:
    disabled: set[str] = set()
    if config_json.is_file():
        try:
            cfg = json.loads(config_json.read_text(encoding="utf-8"))
            for pname, pval in (cfg.get("plugins") or {}).items():
                if isinstance(pval, dict) and pval.get("enabled") is False:
                    disabled.add(pname)
        except Exception:
            pass
    return disabled


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, int(cjk * 1.5 + other / 4.0))


def _scan_skill_folder(
    skill_dir: pathlib.Path,
    source_kind: str,
    source_detail: str,
    priority: int,
    lang: str = "en",
    forced_status: str | None = None,
) -> SkillRecord | None:
    if skill_dir.is_symlink() and not skill_dir.exists():
        folder = skill_dir.name
        return SkillRecord(
            id=f"{source_kind}:{source_detail}:{folder}",
            name=folder,
            folder_name=folder,
            description=tr(lang, "broken_link_desc"),
            invocation_mode="disabled",
            disable_model_invocation=False,
            disable_slash_command=False,
            source_kind=source_kind,
            source_detail=source_detail,
            priority=priority,
            status=forced_status or "excluded",
            shadowed_by=None,
            skill_md_path=str(skill_dir / "SKILL.md"),
            resolved_path=str(skill_dir),
            is_symlink=True,
            editable=False,
            scripts=[],
            references=[],
            warnings=[tr(lang, "warn_broken_link", target=os.readlink(skill_dir))],
            metadata={},
            est_resident_tokens=0,
        )

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None

    try:
        raw_text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    fm, _body, warnings = parse_frontmatter(raw_text, lang=lang)
    folder_name = skill_dir.name
    name = str(fm.get("name") or folder_name).strip()
    description = re.sub(r"\s+", " ", str(fm.get("description") or "")).strip()
    if not description:
        warnings.append(tr(lang, "warn_missing_desc"))

    dmi = _parse_bool(fm.get("disable-model-invocation", False))
    dsc = _parse_bool(fm.get("disable-slash-command", False))

    if "disableModelInvocation" in fm and _parse_bool(fm.get("disableModelInvocation")) and not dmi:
        warnings.append(tr(lang, "warn_camel_dmi"))

    if forced_status in ("excluded", "plugin-disabled"):
        inv_mode = "disabled"
    elif dmi and dsc:
        inv_mode = "disabled"
    elif dmi:
        inv_mode = "explicit"
    elif dsc:
        inv_mode = "auto-only"
    else:
        inv_mode = "auto+slash"

    resolved_dir = skill_dir.resolve()
    scripts: list[str] = []
    scripts_dir = resolved_dir / "scripts"
    if scripts_dir.is_dir():
        scripts = sorted(
            str(p.relative_to(resolved_dir))
            for p in scripts_dir.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        )

    references: list[str] = []
    for sub in ("references", "docs", "examples", "resources"):
        sdir = resolved_dir / sub
        if sdir.is_dir():
            references.extend(
                sorted(
                    str(p.relative_to(resolved_dir))
                    for p in sdir.rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts
                )
            )

    est_tokens = _estimate_tokens(f"{name}: {description}") if (inv_mode in ("auto+slash", "auto-only") and not forced_status) else 0
    editable = source_kind != "builtin" and forced_status not in ("excluded", "plugin-disabled")

    return SkillRecord(
        id=f"{source_kind}:{source_detail}:{name}",
        name=name,
        folder_name=folder_name,
        description=description,
        invocation_mode=inv_mode,
        disable_model_invocation=dmi,
        disable_slash_command=dsc,
        source_kind=source_kind,
        source_detail=source_detail,
        priority=priority,
        status=forced_status or "active",
        shadowed_by=None,
        skill_md_path=str(skill_md),
        resolved_path=str(skill_md.resolve()),
        is_symlink=skill_dir.is_symlink() or skill_md.is_symlink(),
        editable=editable,
        scripts=scripts,
        references=references,
        warnings=warnings,
        metadata=fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {},
        est_resident_tokens=est_tokens,
    )


def _expand_skills_json(
    json_path: pathlib.Path,
    source_kind: str,
    priority: int,
    repo_root: pathlib.Path | None,
    home: pathlib.Path,
    visited: set[pathlib.Path],
    lang: str = "en",
    inherited_include: list[str] | None = None,
    inherited_exclude: list[str] | None = None,
) -> list[SkillRecord]:
    records: list[SkillRecord] = []
    real_json = json_path.resolve()
    if real_json in visited or not real_json.is_file():
        return records
    visited.add(real_json)

    try:
        cfg = json.loads(real_json.read_text(encoding="utf-8"))
    except Exception:
        return records

    base_dir = real_json.parent.parent if real_json.parent.name in WORKSPACE_DOT_DIRS else real_json.parent
    inc_outer = list(inherited_include or [])
    exc_outer = list(inherited_exclude or [])

    for inh in cfg.get("inherits") or []:
        if not isinstance(inh, dict) or not inh.get("path"):
            continue
        target = _resolve_config_path(str(inh["path"]), base_dir, repo_root, home)
        records.extend(
            _expand_skills_json(
                target,
                source_kind,
                priority,
                repo_root,
                home,
                visited,
                lang=lang,
                inherited_include=inc_outer + list(inh.get("include_only") or []),
                inherited_exclude=exc_outer + list(inh.get("exclude") or []),
            )
        )

    for entry in cfg.get("entries") or []:
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        entry_dir = _resolve_config_path(str(entry["path"]), base_dir, repo_root, home)
        if not entry_dir.is_dir():
            continue
        inc = inc_outer + list(entry.get("include_only") or [])
        exc = exc_outer + list(entry.get("exclude") or [])
        short_origin = str(entry_dir).replace(str(home), "~")
        for child in sorted(entry_dir.iterdir(), key=lambda p: p.name.lower()):
            if not (child.is_dir() or child.is_symlink()):
                continue
            excluded = False
            if inc and not _matches_any_pattern(child.name, inc):
                excluded = True
            if exc and _matches_any_pattern(child.name, exc):
                excluded = True
            rec = _scan_skill_folder(
                child,
                source_kind=source_kind,
                source_detail=short_origin,
                priority=priority,
                lang=lang,
                forced_status="excluded" if excluded else None,
            )
            if rec is not None:
                if excluded:
                    rec.warnings.append(tr(lang, "warn_excluded", file=json_path.name))
                records.append(rec)

    return records


def discover_all_skills(
    cwd: pathlib.Path | None = None,
    home: pathlib.Path | None = None,
    lang: str = "en",
) -> list[SkillRecord]:
    """Discover all skills visible to agy from `cwd`, applying Antigravity precedence rules."""
    home_dir = (home or pathlib.Path.home()).resolve()
    work_dir = (cwd or pathlib.Path.cwd()).resolve()
    repo_root = _find_repo_root(work_dir)

    gemini_config = home_dir / ".gemini" / "config"
    global_skills_dirs = [
        (gemini_config / "skills", "global"),
        (home_dir / ".gemini" / "antigravity-cli" / "skills", "global-cli"),
        (home_dir / ".gemini" / "skills", "global-legacy"),
        (home_dir / ".gemini" / "antigravity" / "skills", "global-ide"),
    ]
    plugins_dir = gemini_config / "plugins"
    builtin_dir = home_dir / ".gemini" / "antigravity-cli" / "builtin" / "skills"
    global_skills_json = gemini_config / "skills.json"
    global_config_json = gemini_config / "config.json"

    raw_records: list[SkillRecord] = []

    # Build ancestor chain from cwd up to repo_root (or cwd itself if outside git repo)
    ancestors: list[pathlib.Path] = []
    cur = work_dir
    while True:
        ancestors.append(cur)
        if repo_root is None or cur == repo_root or cur.parent == cur:
            break
        cur = cur.parent

    # 1. Workspace hierarchical discovery (.agents/skills, .agent/skills, ...)
    for anc in ancestors:
        short_anc = str(anc).replace(str(home_dir), "~")
        for dot in WORKSPACE_DOT_DIRS:
            sdir = anc / dot / "skills"
            if sdir.is_dir():
                for child in sorted(sdir.iterdir(), key=lambda p: p.name.lower()):
                    if child.is_dir() or child.is_symlink():
                        rec = _scan_skill_folder(
                            child,
                            source_kind="workspace",
                            source_detail=f"{short_anc}/{dot}/skills",
                            priority=SOURCE_ORDER["workspace"],
                            lang=lang,
                        )
                        if rec:
                            raw_records.append(rec)

    # 2. Workspace declared (skills.json in ancestor dot dirs)
    visited_json: set[pathlib.Path] = set()
    for anc in ancestors:
        for dot in WORKSPACE_DOT_DIRS:
            sj = anc / dot / "skills.json"
            if sj.is_file():
                raw_records.extend(
                    _expand_skills_json(
                        sj,
                        source_kind="workspace-json",
                        priority=SOURCE_ORDER["workspace-json"],
                        repo_root=repo_root,
                        home=home_dir,
                        visited=visited_json,
                        lang=lang,
                    )
                )

    # 3. Global native discovery
    for gdir, gkind in global_skills_dirs:
        if gdir.is_dir():
            short_g = str(gdir).replace(str(home_dir), "~")
            for child in sorted(gdir.iterdir(), key=lambda p: p.name.lower()):
                if child.is_dir() or child.is_symlink():
                    rec = _scan_skill_folder(
                        child,
                        source_kind=gkind,
                        source_detail=short_g,
                        priority=SOURCE_ORDER[gkind],
                        lang=lang,
                    )
                    if rec:
                        raw_records.append(rec)

    # 4. Plugins (~/.gemini/config/plugins/*/skills/*)
    disabled_plugins = _load_disabled_plugins(global_config_json)
    if plugins_dir.is_dir():
        for pdir in sorted(plugins_dir.iterdir(), key=lambda p: p.name.lower()):
            if not pdir.is_dir():
                continue
            pname = pdir.name
            p_disabled = pname in disabled_plugins
            pjson = pdir / "plugin.json"
            if pjson.is_file():
                try:
                    pm = json.loads(pjson.read_text(encoding="utf-8"))
                    if pm.get("disabled") is True:
                        p_disabled = True
                except Exception:
                    pass
            pskills = pdir / "skills"
            if pskills.is_dir():
                for child in sorted(pskills.iterdir(), key=lambda p: p.name.lower()):
                    if child.is_dir() or child.is_symlink():
                        rec = _scan_skill_folder(
                            child,
                            source_kind="plugin",
                            source_detail=pname,
                            priority=SOURCE_ORDER["plugin"],
                            lang=lang,
                            forced_status="plugin-disabled" if p_disabled else None,
                        )
                        if rec:
                            raw_records.append(rec)

    # 5. Built-in skills
    if builtin_dir.is_dir():
        for child in sorted(builtin_dir.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir() or child.is_symlink():
                rec = _scan_skill_folder(
                    child,
                    source_kind="builtin",
                    source_detail="builtin",
                    priority=SOURCE_ORDER["builtin"],
                    lang=lang,
                )
                if rec:
                    raw_records.append(rec)

    # 6. Global declared (~/.gemini/config/skills.json)
    if global_skills_json.is_file():
        raw_records.extend(
            _expand_skills_json(
                global_skills_json,
                source_kind="declared",
                priority=SOURCE_ORDER["declared"],
                repo_root=repo_root,
                home=home_dir,
                visited=visited_json,
                lang=lang,
            )
        )

    # Resolve precedence & shadowing (lower priority number wins)
    seen_active: dict[str, SkillRecord] = {}
    seen_resolved: set[str] = set()
    final_records: list[SkillRecord] = []

    for rec in raw_records:
        if rec.status in ("excluded", "plugin-disabled"):
            final_records.append(rec)
            continue

        if rec.resolved_path in seen_resolved:
            winner = seen_active.get(rec.name)
            rec.status = "shadowed"
            rec.shadowed_by = f"{winner.source_kind} ({winner.skill_md_path})" if winner else "higher-priority duplicate"
            rec.est_resident_tokens = 0
            final_records.append(rec)
            continue

        if rec.name in seen_active:
            winner = seen_active[rec.name]
            rec.status = "shadowed"
            rec.shadowed_by = f"{winner.source_kind} ({winner.skill_md_path})"
            rec.est_resident_tokens = 0
            final_records.append(rec)
            continue

        seen_active[rec.name] = rec
        seen_resolved.add(rec.resolved_path)
        final_records.append(rec)

    id_counts: dict[str, int] = {}
    for rec in final_records:
        base_id = rec.id
        cnt = id_counts.get(base_id, 0)
        id_counts[base_id] = cnt + 1
        if cnt > 0:
            rec.id = f"{base_id}#{cnt + 1}"

    return final_records


# ---------------------------------------------------------------------------
# Terminal Formatting Helpers (CJK display width aware)
# ---------------------------------------------------------------------------

def use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    BLUE = "\033[34m"
    GRAY = "\033[90m"


def paint(text: str, code: str) -> str:
    if not use_color() or not code:
        return text
    return f"{code}{text}{Ansi.RESET}"


def display_width(text: str) -> int:
    w = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        ea = unicodedata.east_asian_width(ch)
        w += 2 if ea in ("W", "F") else 1
    return w


def truncate_width(text: str, max_w: int) -> str:
    if max_w <= 0:
        return ""
    if display_width(text) <= max_w:
        return text
    if max_w <= 1:
        return "…"
    out: list[str] = []
    cur = 0
    for ch in text:
        cw = 0 if unicodedata.combining(ch) else (2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1)
        if cur + cw > max_w - 1:
            break
        out.append(ch)
        cur += cw
    return "".join(out) + "…"


def pad_width(text: str, width: int) -> str:
    cur = display_width(text)
    if cur >= width:
        return text
    return text + (" " * (width - cur))


def wrap_width(text: str, max_w: int) -> list[str]:
    if max_w <= 4 or display_width(text) <= max_w:
        return [text]
    lines: list[str] = []
    cur = ""
    cur_w = 0
    tokens = re.findall(r"[A-Za-z0-9_./:-]+|\s+|.", text)
    for tok in tokens:
        tw = display_width(tok)
        if not cur and tok.isspace():
            continue
        if cur_w + tw <= max_w:
            cur += tok
            cur_w += tw
        elif tw > max_w:
            for ch in tok:
                cw = display_width(ch)
                if cur_w + cw > max_w and cur:
                    lines.append(cur.rstrip())
                    cur = ch
                    cur_w = cw
                else:
                    cur += ch
                    cur_w += cw
        else:
            if cur:
                lines.append(cur.rstrip())
            if tok.isspace():
                cur = ""
                cur_w = 0
            else:
                cur = tok
                cur_w = tw
    if cur:
        lines.append(cur.rstrip())
    return lines or [""]


def mode_badge_plain(rec: SkillRecord, lang: str = "en") -> str:
    if rec.status == "shadowed":
        return tr(lang, "status_shadowed")
    if rec.status == "excluded":
        return tr(lang, "status_excluded")
    if rec.status == "plugin-disabled":
        return tr(lang, "status_plugin_disabled")
    mapping = {
        "auto+slash": "mode_auto_slash",
        "explicit": "mode_explicit",
        "auto-only": "mode_auto_only",
        "disabled": "mode_disabled",
    }
    return tr(lang, mapping.get(rec.invocation_mode, "mode_disabled"))


def mode_badge_color(rec: SkillRecord) -> str:
    if rec.status != "active":
        return Ansi.GRAY
    if rec.invocation_mode == "explicit":
        return Ansi.YELLOW
    if rec.invocation_mode == "auto+slash":
        return Ansi.GREEN
    if rec.invocation_mode == "auto-only":
        return Ansi.CYAN
    return Ansi.RED


def source_badge(rec: SkillRecord) -> str:
    if rec.source_kind == "plugin":
        short_p = rec.source_detail
        if short_p.startswith("Google.securecoder"):
            short_p = "securecoder"
        return f"plugin:{short_p}"
    if rec.source_kind == "declared":
        if ".omp" in rec.source_detail:
            return "skills.json(omp)"
        return "skills.json"
    return SOURCE_LABELS.get(rec.source_kind, rec.source_kind)


# ---------------------------------------------------------------------------
# CLI Subcommands
# ---------------------------------------------------------------------------

def filter_records(
    records: list[SkillRecord],
    *,
    include_builtin: bool = False,
    include_inactive: bool = False,
    only_explicit: bool = False,
    only_auto: bool = False,
    source_filter: str | None = None,
    query: str | None = None,
    search_body: bool = False,
) -> list[SkillRecord]:
    out: list[SkillRecord] = []
    q_terms = [t.lower() for t in (query or "").split() if t.strip()]

    for rec in records:
        if not include_inactive and rec.status != "active":
            continue
        if not include_builtin and rec.source_kind == "builtin":
            continue
        if only_explicit and rec.invocation_mode != "explicit":
            continue
        if only_auto and rec.invocation_mode not in ("auto+slash", "auto-only"):
            continue
        if source_filter:
            sf = source_filter.lower()
            if sf not in rec.source_kind.lower() and sf not in rec.source_detail.lower() and sf not in source_badge(rec).lower():
                continue
        if q_terms:
            haystack = f"{rec.name} {rec.description} {rec.source_kind} {rec.source_detail}".lower()
            if search_body:
                try:
                    haystack += " " + pathlib.Path(rec.skill_md_path).read_text(encoding="utf-8", errors="replace").lower()
                except OSError:
                    pass
            if not all(t in haystack for t in q_terms):
                continue
        out.append(rec)
    return out


def render_table(
    shown: list[SkillRecord],
    all_records: list[SkillRecord],
    *,
    lang: str = "en",
    full: bool = False,
    include_builtin: bool = False,
    include_inactive: bool = False,
) -> None:
    active_all = [r for r in all_records if r.status == "active"]
    active_user = [r for r in active_all if r.source_kind != "builtin"]
    active_builtin = [r for r in active_all if r.source_kind == "builtin"]
    inactive_all = [r for r in all_records if r.status != "active"]

    scope_pool = active_all if include_builtin else active_user
    n_auto = sum(1 for r in scope_pool if r.invocation_mode in ("auto+slash", "auto-only"))
    n_explicit = sum(1 for r in scope_pool if r.invocation_mode == "explicit")
    est_tok = sum(r.est_resident_tokens for r in active_all)

    header = tr(lang, "hdr_overview", shown=len(shown), auto=n_auto, explicit=n_explicit, tokens=est_tok)
    print(paint(header, Ansi.BOLD + Ansi.CYAN))

    if not shown:
        print(paint(tr(lang, "no_match"), Ansi.DIM))
        return

    term_w = shutil.get_terminal_size((120, 30)).columns
    name_w = min(36, max(16, max(display_width(r.name) for r in shown)))
    mode_w = max(13, max(display_width(mode_badge_plain(r, lang)) for r in shown))
    src_w = min(22, max(10, max(display_width(source_badge(r)) for r in shown)))
    res_w = max(8, max(display_width(f"S:{len(r.scripts)} R:{len(r.references)}") for r in shown))
    desc_w = max(24, term_w - (name_w + mode_w + src_w + res_w + 10))

    sep = "─" * min(term_w, name_w + mode_w + src_w + res_w + desc_w + 8)
    print(paint(sep, Ansi.GRAY))
    hdr_row = (
        f"{pad_width(tr(lang, 'col_name'), name_w)}  "
        f"{pad_width(tr(lang, 'col_mode'), mode_w)}  "
        f"{pad_width(tr(lang, 'col_source'), src_w)}  "
        f"{pad_width(tr(lang, 'col_res'), res_w)}  "
        f"{tr(lang, 'col_desc')}"
    )
    print(paint(hdr_row, Ansi.BOLD))
    print(paint(sep, Ansi.GRAY))

    for rec in shown:
        name_txt = pad_width(truncate_width(rec.name, name_w), name_w)
        if rec.status != "active":
            name_cell = paint(name_txt, Ansi.GRAY)
        elif rec.invocation_mode == "explicit":
            name_cell = paint(name_txt, Ansi.BOLD + Ansi.YELLOW)
        else:
            name_cell = paint(name_txt, Ansi.BOLD)

        mode_cell = paint(pad_width(mode_badge_plain(rec, lang), mode_w), mode_badge_color(rec))
        src_cell = paint(pad_width(truncate_width(source_badge(rec), src_w), src_w), Ansi.BLUE if rec.status == "active" else Ansi.GRAY)
        res_cell = paint(pad_width(f"S:{len(rec.scripts)} R:{len(rec.references)}", res_w), Ansi.DIM)

        desc_text = rec.description or tr(lang, "no_desc")
        if rec.warnings:
            desc_text += "  [!] " + "; ".join(rec.warnings)
        if rec.shadowed_by:
            desc_text += f"  [{tr(lang, 'shadowed_tag')}: {rec.shadowed_by}]"

        if full:
            wrapped = wrap_width(desc_text, desc_w)
            print(f"{name_cell}  {mode_cell}  {src_cell}  {res_cell}  {wrapped[0]}")
            indent = " " * (name_w + mode_w + src_w + res_w + 8)
            for extra in wrapped[1:]:
                print(f"{indent}{extra}")
        else:
            print(f"{name_cell}  {mode_cell}  {src_cell}  {res_cell}  {truncate_width(desc_text, desc_w)}")

    print(paint(sep, Ansi.GRAY))
    hints: list[str] = []
    if not include_builtin and active_builtin:
        hints.append(tr(lang, "hint_builtin", n=len(active_builtin)))
    if not include_inactive and inactive_all:
        hints.append(tr(lang, "hint_inactive", n=len(inactive_all)))
    hints.append(tr(lang, "hint_cmds"))
    sep_char = "；" if lang == "zh" else "; "
    print(paint(tr(lang, "hint_prefix") + sep_char.join(hints), Ansi.DIM))


def cmd_list(args: argparse.Namespace, lang: str) -> int:
    cwd = pathlib.Path(args.cwd) if args.cwd else None
    all_records = discover_all_skills(cwd=cwd, lang=lang)
    include_builtin = args.builtin or args.all
    include_inactive = args.all
    shown = filter_records(
        all_records,
        include_builtin=include_builtin,
        include_inactive=include_inactive,
        only_explicit=args.explicit,
        only_auto=args.auto,
        source_filter=args.source,
        query=args.query,
    )
    if args.json:
        print(json.dumps([r.to_dict() for r in shown], indent=2, ensure_ascii=False))
        return 0
    render_table(shown, all_records, lang=lang, full=args.full, include_builtin=include_builtin, include_inactive=include_inactive)
    return 0


def cmd_search(args: argparse.Namespace, lang: str) -> int:
    cwd = pathlib.Path(args.cwd) if args.cwd else None
    all_records = discover_all_skills(cwd=cwd, lang=lang)
    query = " ".join(args.keywords)
    shown = filter_records(
        all_records,
        include_builtin=True,
        include_inactive=args.all,
        query=query,
        search_body=args.body,
    )
    if args.json:
        print(json.dumps([r.to_dict() for r in shown], indent=2, ensure_ascii=False))
        return 0
    render_table(shown, all_records, lang=lang, full=True, include_builtin=True, include_inactive=args.all)
    return 0


def _find_skill_by_name(records: list[SkillRecord], name: str) -> list[SkillRecord]:
    exact = [r for r in records if r.name == name]
    if exact:
        return exact
    return [r for r in records if r.name.lower() == name.lower() or r.folder_name.lower() == name.lower()]


def cmd_show(args: argparse.Namespace, lang: str) -> int:
    cwd = pathlib.Path(args.cwd) if args.cwd else None
    records = discover_all_skills(cwd=cwd, lang=lang)
    matches = _find_skill_by_name(records, args.name)
    if not matches:
        print(paint(tr(lang, "not_found", name=args.name), Ansi.RED), file=sys.stderr)
        return 1

    matches.sort(key=lambda r: (0 if r.status == "active" else 1, r.priority))
    rec = matches[0]
    if args.json:
        print(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False))
        return 0

    slash = f"/{rec.name}" if not rec.disable_slash_command else tr(lang, "show_slash_off")
    print(paint(f"=== {rec.name} ===", Ansi.BOLD + Ansi.CYAN))
    print(f"{tr(lang, 'show_mode')}: {paint(mode_badge_plain(rec, lang), mode_badge_color(rec))}  ({tr(lang, 'show_slash')}: {slash})")
    print(f"{tr(lang, 'show_status')}: {rec.status}" + (f" ({tr(lang, 'shadowed_tag')}: {rec.shadowed_by})" if rec.shadowed_by else ""))
    print(f"{tr(lang, 'show_source')}: {source_badge(rec)} -> {rec.skill_md_path}")
    if rec.is_symlink:
        print(f"{tr(lang, 'show_real')}: {rec.resolved_path}")
    print(f"{tr(lang, 'show_tokens')}: {tr(lang, 'show_tokens_note', tokens=rec.est_resident_tokens)}")
    print(f"{tr(lang, 'show_desc')}:\n  {rec.description or tr(lang, 'no_desc')}")
    if rec.scripts:
        print(f"{tr(lang, 'show_scripts')}:")
        for s in rec.scripts:
            print(f"  - {s}")
    if rec.references:
        print(f"{tr(lang, 'show_refs')}:")
        for r in rec.references:
            print(f"  - {r}")
    if rec.warnings:
        print(paint(f"{tr(lang, 'show_warns')}:", Ansi.YELLOW))
        for w in rec.warnings:
            print(paint(f"  [!] {w}", Ansi.YELLOW))
    if len(matches) > 1:
        print(paint(f"{tr(lang, 'show_dups')}:", Ansi.DIM))
        for other in matches[1:]:
            print(paint(f"  - [{other.status}] {source_badge(other)}: {other.skill_md_path}", Ansi.DIM))

    if args.body:
        print(paint("\n" + tr(lang, "show_body"), Ansi.BOLD))
        print(pathlib.Path(rec.skill_md_path).read_text(encoding="utf-8", errors="replace"))
    return 0


def cmd_mode(args: argparse.Namespace, lang: str) -> int:
    cwd = pathlib.Path(args.cwd) if args.cwd else None
    records = discover_all_skills(cwd=cwd, lang=lang)
    matches = [r for r in _find_skill_by_name(records, args.name) if r.status == "active"]
    if not matches:
        print(paint(tr(lang, "not_active", name=args.name), Ansi.RED), file=sys.stderr)
        return 1
    rec = matches[0]
    if not rec.editable and not args.force:
        print(paint(tr(lang, "readonly_err", name=rec.name, source=source_badge(rec)), Ansi.RED), file=sys.stderr)
        return 1

    want_explicit = args.target_mode == "explicit"
    if args.target_mode == "toggle":
        want_explicit = not rec.disable_model_invocation

    changed = update_disable_model_invocation(pathlib.Path(rec.skill_md_path), explicit=want_explicit)
    new_label = tr(lang, "mode_explicit" if want_explicit else "mode_auto_slash")
    if changed:
        print(paint(tr(lang, "mode_updated", name=rec.name, mode=new_label), Ansi.GREEN))
        print(tr(lang, "mode_file", path=rec.resolved_path))
        print(paint(tr(lang, "mode_reload"), Ansi.DIM))
    else:
        print(tr(lang, "mode_noop", name=rec.name, mode=new_label))
    return 0


def cmd_doctor(args: argparse.Namespace, lang: str) -> int:
    cwd = pathlib.Path(args.cwd) if args.cwd else None
    records = discover_all_skills(cwd=cwd, lang=lang)
    active = [r for r in records if r.status == "active"]
    auto_skills = [r for r in active if r.invocation_mode in ("auto+slash", "auto-only")]
    explicit_skills = [r for r in active if r.invocation_mode == "explicit"]
    shadowed = [r for r in records if r.status == "shadowed"]
    excluded = [r for r in records if r.status == "excluded"]
    warned = [r for r in active if r.warnings]

    est_tokens = sum(r.est_resident_tokens for r in auto_skills)
    print(paint(tr(lang, "doc_title"), Ansi.BOLD + Ansi.CYAN))
    print(
        tr(
            lang,
            "doc_total",
            total=len(active),
            user=sum(1 for r in active if r.source_kind != "builtin"),
            builtin=sum(1 for r in active if r.source_kind == "builtin"),
        )
    )
    print(tr(lang, "doc_auto", n=len(auto_skills), tokens=est_tokens))
    print(tr(lang, "doc_explicit", n=len(explicit_skills)))
    print(tr(lang, "doc_inactive", shadowed=len(shadowed), excluded=len(excluded)))

    if warned:
        print(paint(tr(lang, "doc_warn_hdr"), Ansi.YELLOW + Ansi.BOLD))
        for r in warned:
            for w in r.warnings:
                print(paint(f"  - {r.name} ({source_badge(r)}): {w}", Ansi.YELLOW))
                print(paint(tr(lang, "doc_warn_path", path=r.skill_md_path), Ansi.DIM))
    else:
        print(paint(tr(lang, "doc_ok"), Ansi.GREEN))

    if shadowed:
        print(paint(tr(lang, "doc_shadow_hdr"), Ansi.BLUE + Ansi.BOLD))
        for r in shadowed:
            print(f"  - {r.name}: {r.skill_md_path}  <- {r.shadowed_by}")

    if excluded:
        print(paint(tr(lang, "doc_excl_hdr"), Ansi.DIM))
        for r in excluded:
            print(f"  - {r.name}: {r.skill_md_path}")

    return 0


# ---------------------------------------------------------------------------
# Interactive Terminal TUI (pure stdlib curses, lazy import for portability)
# ---------------------------------------------------------------------------

def run_tui(cwd: pathlib.Path | None, lang: str = "en") -> int:
    try:
        import curses
    except ImportError:
        print(tr(lang, "tui_no_curses"), file=sys.stderr)
        return 1

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(tr(lang, "tui_no_tty"), file=sys.stderr)
        return 1

    default_status = (
        "↑↓ move | / search | e explicit | t auto | a all | b built-in | x shadowed | m toggle mode | v view | r reload | q quit"
        if lang == "en"
        else "↑↓移动 | /搜索 | e仅显式 | t自动 | a全部 | b切换内置 | x已覆盖 | m改调用方式 | v看全文 | r刷新 | q退出"
    )

    state: dict[str, Any] = {
        "records": discover_all_skills(cwd=cwd, lang=lang),
        "idx": 0,
        "scroll": 0,
        "mode_filter": "all",
        "show_builtin": False,
        "show_inactive": False,
        "search": "",
        "searching": False,
        "confirm_toggle": None,
        "status_msg": default_status,
        "viewing_body": False,
        "body_scroll": 0,
    }

    def get_filtered() -> list[SkillRecord]:
        return filter_records(
            state["records"],
            include_builtin=state["show_builtin"],
            include_inactive=state["show_inactive"],
            only_explicit=(state["mode_filter"] == "explicit"),
            only_auto=(state["mode_filter"] == "auto"),
            query=state["search"],
        )

    def draw(stdscr: Any) -> None:
        curses.curs_set(0)
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_BLUE, -1)
        curses.init_pair(5, curses.COLOR_RED, -1)
        curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_CYAN)

        while True:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            if h < 10 or w < 40:
                stdscr.addstr(0, 0, "Terminal too small (press q to quit)")
                stdscr.refresh()
                if stdscr.getch() in (ord("q"), 27):
                    return
                continue

            items = get_filtered()
            state["idx"] = max(0, min(state["idx"], len(items) - 1)) if items else 0

            if state["viewing_body"] and items:
                rec = items[state["idx"]]
                try:
                    raw_lines = pathlib.Path(rec.skill_md_path).read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    raw_lines = ["(failed to read file)"]
                wrapped: list[str] = []
                for rl in raw_lines:
                    wrapped.extend(wrap_width(rl, max(20, w - 2)))
                max_scroll = max(0, len(wrapped) - (h - 3))
                state["body_scroll"] = max(0, min(state["body_scroll"], max_scroll))

                title = f" {rec.name} — {rec.skill_md_path}  (↑↓/PgUp/PgDn scroll, Esc/v/q back) "
                stdscr.addnstr(0, 0, truncate_width(title, w - 1), w - 1, curses.color_pair(6) | curses.A_BOLD)
                for row_i, line in enumerate(wrapped[state["body_scroll"] : state["body_scroll"] + h - 2], start=1):
                    stdscr.addnstr(row_i, 1, truncate_width(line, w - 2), w - 2)
                stdscr.refresh()
                ch = stdscr.getch()
                if ch in (27, ord("v"), ord("q")):
                    state["viewing_body"] = False
                elif ch in (curses.KEY_DOWN, ord("j")):
                    state["body_scroll"] += 1
                elif ch in (curses.KEY_UP, ord("k")):
                    state["body_scroll"] -= 1
                elif ch == curses.KEY_NPAGE:
                    state["body_scroll"] += max(1, h - 4)
                elif ch == curses.KEY_PPAGE:
                    state["body_scroll"] -= max(1, h - 4)
                continue

            filt_tag = state["mode_filter"]
            b_tag = "+builtin" if state["show_builtin"] else "no-builtin"
            x_tag = "+inactive" if state["show_inactive"] else "active"
            hdr = f" agy-skills TUI | {len(items)} shown | [{filt_tag}] [{b_tag}] [{x_tag}]"
            if state["search"]:
                hdr += f" | search: {state['search']}"
            stdscr.addnstr(0, 0, pad_width(truncate_width(hdr, w - 1), w - 1), w - 1, curses.color_pair(6) | curses.A_BOLD)

            detail_h = min(10, max(6, h // 3))
            list_h = max(3, h - detail_h - 3)

            if state["idx"] < state["scroll"]:
                state["scroll"] = state["idx"]
            elif state["idx"] >= state["scroll"] + list_h:
                state["scroll"] = state["idx"] - list_h + 1

            name_w = min(32, max(16, w // 4))
            mode_w = 14
            src_w = 18
            desc_w = max(12, w - name_w - mode_w - src_w - 8)
            col_hdr = f"  {pad_width(tr(lang, 'col_name'), name_w)}  {pad_width(tr(lang, 'col_mode'), mode_w)}  {pad_width(tr(lang, 'col_source'), src_w)}  {tr(lang, 'col_desc')}"
            stdscr.addnstr(1, 0, truncate_width(col_hdr, w - 1), w - 1, curses.A_BOLD | curses.color_pair(1))

            for row_offset in range(list_h):
                item_i = state["scroll"] + row_offset
                y = 2 + row_offset
                if item_i >= len(items):
                    break
                rec = items[item_i]
                is_sel = item_i == state["idx"]
                prefix = "▸ " if is_sel else "  "
                line = (
                    f"{prefix}{pad_width(truncate_width(rec.name, name_w), name_w)}  "
                    f"{pad_width(mode_badge_plain(rec, lang), mode_w)}  "
                    f"{pad_width(truncate_width(source_badge(rec), src_w), src_w)}  "
                    f"{truncate_width(rec.description, desc_w)}"
                )
                attr = curses.A_REVERSE | curses.A_BOLD if is_sel else (
                    curses.color_pair(3) if rec.invocation_mode == "explicit" else (
                        curses.A_DIM if rec.status != "active" else curses.A_NORMAL
                    )
                )
                stdscr.addnstr(y, 0, truncate_width(line, w - 1), w - 1, attr)

            sep_y = 2 + list_h
            stdscr.addnstr(sep_y, 0, "─" * (w - 1), w - 1, curses.A_DIM)
            if items:
                rec = items[state["idx"]]
                dy = sep_y + 1
                slash = f"/{rec.name}" if not rec.disable_slash_command else tr(lang, "show_slash_off")
                meta_line = f"{rec.name}  [{mode_badge_plain(rec, lang)} | {slash}]  {source_badge(rec)}  S:{len(rec.scripts)} R:{len(rec.references)}"
                stdscr.addnstr(dy, 1, truncate_width(meta_line, w - 2), w - 2, curses.A_BOLD | curses.color_pair(1))
                dy += 1
                if dy < h - 1:
                    stdscr.addnstr(dy, 1, truncate_width(rec.skill_md_path, w - 2), w - 2, curses.A_DIM)
                    dy += 1
                for dl in wrap_width(rec.description or tr(lang, "no_desc"), max(20, w - 3)):
                    if dy >= h - 1:
                        break
                    stdscr.addnstr(dy, 1, truncate_width(dl, w - 2), w - 2)
                    dy += 1
                if rec.warnings and dy < h - 1:
                    stdscr.addnstr(dy, 1, truncate_width("[!] " + "; ".join(rec.warnings), w - 2), w - 2, curses.color_pair(3))
            else:
                stdscr.addnstr(sep_y + 1, 1, tr(lang, "no_match"), w - 2, curses.A_DIM)

            if state["searching"]:
                bar = f" / {state['search']}_"
                stdscr.addnstr(h - 1, 0, pad_width(truncate_width(bar, w - 1), w - 1), w - 1, curses.color_pair(6))
            elif state["confirm_toggle"] is not None:
                trec, want_exp = state["confirm_toggle"]
                tgt = tr(lang, "mode_explicit" if want_exp else "mode_auto_slash")
                bar = f" Toggle '{trec.name}' -> [{tgt}]? (y/n)"
                stdscr.addnstr(h - 1, 0, pad_width(truncate_width(bar, w - 1), w - 1), w - 1, curses.color_pair(3) | curses.A_REVERSE)
            else:
                stdscr.addnstr(h - 1, 0, truncate_width(" " + state["status_msg"], w - 1), w - 1, curses.A_DIM)

            stdscr.refresh()
            ch = stdscr.getch()

            if state["confirm_toggle"] is not None:
                trec, want_exp = state["confirm_toggle"]
                state["confirm_toggle"] = None
                if ch in (ord("y"), ord("Y")):
                    try:
                        update_disable_model_invocation(pathlib.Path(trec.skill_md_path), explicit=want_exp)
                        state["records"] = discover_all_skills(cwd=cwd, lang=lang)
                        state["status_msg"] = f"Updated '{trec.name}'. Run /skills reload in agy."
                    except Exception as exc:
                        state["status_msg"] = f"Error: {exc}"
                else:
                    state["status_msg"] = "Cancelled."
                continue

            if state["searching"]:
                if ch in (10, 13, curses.KEY_ENTER):
                    state["searching"] = False
                elif ch == 27:
                    state["search"] = ""
                    state["searching"] = False
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    state["search"] = state["search"][:-1]
                    state["idx"] = 0
                elif 32 <= ch <= 126:
                    state["search"] += chr(ch)
                    state["idx"] = 0
                continue

            if ch in (ord("q"), ord("Q")):
                return
            elif ch in (curses.KEY_DOWN, ord("j")):
                state["idx"] += 1
            elif ch in (curses.KEY_UP, ord("k")):
                state["idx"] -= 1
            elif ch == curses.KEY_NPAGE:
                state["idx"] += list_h
            elif ch == curses.KEY_PPAGE:
                state["idx"] -= list_h
            elif ch == ord("/"):
                state["searching"] = True
            elif ch == 27:
                state["search"] = ""
            elif ch == ord("a"):
                state["mode_filter"] = "all"
                state["idx"] = 0
            elif ch == ord("e"):
                state["mode_filter"] = "explicit"
                state["idx"] = 0
            elif ch == ord("t"):
                state["mode_filter"] = "auto"
                state["idx"] = 0
            elif ch == ord("b"):
                state["show_builtin"] = not state["show_builtin"]
                state["idx"] = 0
            elif ch == ord("x"):
                state["show_inactive"] = not state["show_inactive"]
                state["idx"] = 0
            elif ch in (ord("v"), 10, 13, curses.KEY_ENTER):
                if items:
                    state["viewing_body"] = True
                    state["body_scroll"] = 0
            elif ch == ord("r"):
                state["records"] = discover_all_skills(cwd=cwd, lang=lang)
                state["status_msg"] = "Reloaded from disk."
            elif ch == ord("m"):
                if items:
                    rec = items[state["idx"]]
                    if not rec.editable:
                        state["status_msg"] = f"'{rec.name}' is read-only ({source_badge(rec)})."
                    else:
                        state["confirm_toggle"] = (rec, not rec.disable_model_invocation)

    curses.wrapper(draw)
    return 0


# ---------------------------------------------------------------------------
# Hardened Localhost-Only Web Dashboard (`agy-skills web`)
# ---------------------------------------------------------------------------

WEB_CSS = """
:root {
  --bg: #0f172a;
  --panel: #1e293b;
  --panel-alt: #162032;
  --border: #334155;
  --text: #e2e8f0;
  --muted: #94a3b8;
  --accent: #38bdf8;
  --green: #22c55e;
  --yellow: #f59e0b;
  --red: #ef4444;
  --purple: #a78bfa;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
}
header {
  padding: 18px 24px;
  border-bottom: 1px solid var(--border);
  background: var(--panel-alt);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
header h1 { margin: 0; font-size: 20px; color: var(--accent); }
.header-actions { display: flex; gap: 8px; align-items: center; }
.subtitle { font-size: 13px; color: var(--muted); }
.container { max-width: 1400px; margin: 0 auto; padding: 18px 24px 40px; }
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.stat-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 16px;
}
.stat-label { font-size: 12px; color: var(--muted); }
.stat-value { font-size: 24px; font-weight: 700; margin-top: 2px; }
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 16px;
}
input[type="search"], select {
  background: var(--panel);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 14px;
}
input[type="search"] { flex: 1 1 260px; }
button {
  background: var(--panel);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 7px 12px;
  font-size: 13px;
  cursor: pointer;
}
button:hover { border-color: var(--accent); }
button.active { background: var(--accent); color: #0b1120; border-color: var(--accent); font-weight: 600; }
button.primary { background: var(--accent); color: #0b1120; border-color: var(--accent); font-weight: 600; }
button:disabled { opacity: 0.45; cursor: not-allowed; }
.layout { display: grid; grid-template-columns: 1.55fr 1fr; gap: 18px; align-items: start; }
@media (max-width: 980px) { .layout { grid-template-columns: 1fr; } }
.skill-list { display: flex; flex-direction: column; gap: 10px; }
.skill-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 13px 16px;
  cursor: pointer;
  transition: border-color 0.12s ease;
}
.skill-card:hover, .skill-card.selected { border-color: var(--accent); }
.skill-card.inactive { opacity: 0.62; }
.card-top { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; }
.skill-name { font-weight: 700; font-size: 15px; color: #f8fafc; }
.slash-cmd { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--accent); margin-left: 8px; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; }
.badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 600;
  border: 1px solid transparent;
}
.badge-auto { background: rgba(34,197,94,0.16); color: #86efac; border-color: rgba(34,197,94,0.35); }
.badge-explicit { background: rgba(245,158,11,0.16); color: #fcd34d; border-color: rgba(245,158,11,0.35); }
.badge-auto-only { background: rgba(56,189,248,0.16); color: #7dd3fc; border-color: rgba(56,189,248,0.35); }
.badge-muted { background: rgba(148,163,184,0.14); color: #cbd5e1; border-color: rgba(148,163,184,0.3); }
.badge-src { background: rgba(167,139,250,0.14); color: #ddd6fe; border-color: rgba(167,139,250,0.32); }
.badge-warn { background: rgba(239,68,68,0.16); color: #fca5a5; border-color: rgba(239,68,68,0.35); }
.card-desc { margin-top: 8px; font-size: 13px; color: #cbd5e1; }
.card-meta { margin-top: 8px; font-size: 12px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 12px; }
.detail-pane {
  position: sticky;
  top: 16px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
  max-height: calc(100vh - 36px);
  overflow-y: auto;
}
.detail-pane h2 { margin: 0 0 8px; font-size: 18px; color: #f8fafc; }
.meta-row { font-size: 13px; margin: 5px 0; color: #cbd5e1; word-break: break-all; }
.meta-key { color: var(--muted); font-weight: 600; margin-right: 6px; }
.actions-bar { margin: 14px 0; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.confirm-box {
  background: rgba(245,158,11,0.12);
  border: 1px solid rgba(245,158,11,0.45);
  border-radius: 8px;
  padding: 10px 12px;
  margin: 10px 0;
  font-size: 13px;
}
.confirm-actions { margin-top: 8px; display: flex; gap: 8px; }
pre.md-preview {
  background: var(--panel-alt);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-x: auto;
  max-height: 420px;
}
.toast {
  position: fixed;
  bottom: 20px;
  right: 20px;
  background: #0f172a;
  color: #f8fafc;
  border: 1px solid var(--accent);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  display: none;
  z-index: 99;
}
.toast.show { display: block; }
"""

WEB_JS = """
(() => {
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const langMeta = document.querySelector('meta[name="ui-lang"]');
  const CSRF_TOKEN = csrfMeta ? csrfMeta.getAttribute('content') : '';

  const STR = {
    en: {
      title: 'agy-skills Dashboard',
      reload: 'Rescan Disk',
      langBtn: '中文',
      searchPlaceholder: 'Search by name, description, or source (e.g. latex, plugin)...',
      srcAll: 'All Sources',
      btnAll: 'All Modes',
      btnAuto: 'Auto-Trigger',
      btnExplicit: 'Explicit /cmd',
      btnBuiltin: 'Show Built-in',
      btnInactive: 'Show Shadowed/Excl.',
      statActive: 'Active Skills',
      statAuto: 'Auto-Trigger + /cmd',
      statExplicit: 'Explicit /cmd Only',
      statTok: 'Est. Resident Cost',
      statWarn: 'Warnings',
      noMatch: 'No skills matched your filters.',
      emptyTitle: 'Select a skill to inspect',
      emptySub: 'Inspect description, scripts, references, warnings, full SKILL.md preview, and toggle invocation mode.',
      modeAuto: 'auto + /cmd',
      modeExplicit: 'explicit /cmd',
      modeAutoOnly: 'auto-only',
      modeDisabled: 'disabled',
      stShadowed: 'shadowed',
      stExcluded: 'excluded',
      stPluginOff: 'plugin-off',
      scripts: 'Scripts',
      refs: 'References',
      resident: 'Resident',
      shadowedBy: 'Shadowed by',
      slashCmd: 'Slash Cmd',
      slashOff: '(disabled)',
      status: 'Status',
      filePath: 'Path',
      resolved: 'Resolved',
      desc: 'Description',
      toAuto: 'Switch to Auto + /cmd',
      toExplicit: 'Switch to Explicit /cmd',
      readOnly: '(read-only built-in or inactive)',
      confirmMsg: 'Write frontmatter change for ',
      confirmWrite: 'Confirm Write',
      cancel: 'Cancel',
      previewHdr: 'SKILL.md Preview:',
      loading: 'Loading SKILL.md...',
      updatedToast: 'Updated! Run /skills reload in agy to apply.',
      failedToast: 'Update failed: ',
      warnBadge: 'Warnings ',
    },
    zh: {
      title: 'agy-skills 控制台',
      reload: '重新扫描磁盘',
      langBtn: 'EN',
      searchPlaceholder: '搜索名称、功能说明、来源（如：引用 / LaTeX / plugin）...',
      srcAll: '全部来源',
      btnAll: '全部模式',
      btnAuto: '自动触发',
      btnExplicit: '仅显式 /cmd',
      btnBuiltin: '显示内置',
      btnInactive: '显示已覆盖/排除',
      statActive: '生效技能',
      statAuto: '自动触发 + /cmd',
      statExplicit: '仅显式调用 (/cmd)',
      statTok: '常驻上下文估算',
      statWarn: '配置告警',
      noMatch: '没有匹配的 skill。',
      emptyTitle: '点击左侧任意 Skill 查看详情',
      emptySub: '可查看完整功能说明、脚本与参考文件、路径来源、告警诊断，以及一键切换「自动触发 / 仅显式调用」。',
      modeAuto: '自动 + /cmd',
      modeExplicit: '仅显式 /cmd',
      modeAutoOnly: '仅自动触发',
      modeDisabled: '已禁用',
      stShadowed: '已覆盖',
      stExcluded: '已排除',
      stPluginOff: '插件禁用',
      scripts: '脚本',
      refs: '参考文档',
      resident: '常驻',
      shadowedBy: '被覆盖',
      slashCmd: '斜杠命令',
      slashOff: '(已禁用)',
      status: '生效状态',
      filePath: '文件路径',
      resolved: '真实目标',
      desc: '功能说明',
      toAuto: '改为「自动触发 + /cmd」',
      toExplicit: '改为「仅显式 /cmd」',
      readOnly: '(内置或未生效项只读)',
      confirmMsg: '确认修改 frontmatter：',
      confirmWrite: '确认写入',
      cancel: '取消',
      previewHdr: 'SKILL.md 全文预览:',
      loading: '正在加载 SKILL.md...',
      updatedToast: '已更新，请在 agy 中运行 /skills reload 生效',
      failedToast: '切换失败: ',
      warnBadge: '告警 ',
    },
  };

  const state = {
    lang: (langMeta && langMeta.getAttribute('content') === 'zh') ? 'zh' : 'en',
    skills: [],
    selectedId: null,
    modeFilter: 'all',
    sourceFilter: 'all',
    showBuiltin: false,
    showInactive: false,
    query: '',
    pendingToggle: null,
  };

  const t = (k) => (STR[state.lang] && STR[state.lang][k]) || STR.en[k] || k;

  const els = {
    title: document.getElementById('page-title'),
    stats: document.getElementById('stats'),
    search: document.getElementById('search-input'),
    sourceSelect: document.getElementById('source-select'),
    optAll: document.getElementById('opt-src-all'),
    list: document.getElementById('skill-list'),
    detail: document.getElementById('detail-pane'),
    toast: document.getElementById('toast'),
    btnAll: document.getElementById('f-all'),
    btnAuto: document.getElementById('f-auto'),
    btnExplicit: document.getElementById('f-explicit'),
    btnBuiltin: document.getElementById('f-builtin'),
    btnInactive: document.getElementById('f-inactive'),
    btnReload: document.getElementById('btn-reload'),
    btnLang: document.getElementById('btn-lang'),
  };

  let toastTimer = null;
  function showToast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => els.toast.classList.remove('show'), 3600);
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function modeLabel(s) {
    if (s.status === 'shadowed') return t('stShadowed');
    if (s.status === 'excluded') return t('stExcluded');
    if (s.status === 'plugin-disabled') return t('stPluginOff');
    if (s.invocation_mode === 'explicit') return t('modeExplicit');
    if (s.invocation_mode === 'auto+slash') return t('modeAuto');
    if (s.invocation_mode === 'auto-only') return t('modeAutoOnly');
    return t('modeDisabled');
  }

  function modeBadgeClass(s) {
    if (s.status !== 'active') return 'badge badge-muted';
    if (s.invocation_mode === 'explicit') return 'badge badge-explicit';
    if (s.invocation_mode === 'auto+slash') return 'badge badge-auto';
    if (s.invocation_mode === 'auto-only') return 'badge badge-auto-only';
    return 'badge badge-warn';
  }

  function sourceLabel(s) {
    if (s.source_kind === 'plugin') return 'plugin:' + s.source_detail;
    if (s.source_kind === 'declared') return 'skills.json (' + s.source_detail + ')';
    return s.source_kind;
  }

  function syncChromeStrings() {
    els.title.textContent = t('title');
    els.btnReload.textContent = t('reload');
    els.btnLang.textContent = t('langBtn');
    els.search.setAttribute('placeholder', t('searchPlaceholder'));
    els.optAll.textContent = t('srcAll');
    els.btnAll.textContent = t('btnAll');
    els.btnAuto.textContent = t('btnAuto');
    els.btnExplicit.textContent = t('btnExplicit');
    els.btnBuiltin.textContent = t('btnBuiltin');
    els.btnInactive.textContent = t('btnInactive');
  }

  function getFiltered() {
    const terms = state.query.trim().toLowerCase().split(/\\s+/).filter(Boolean);
    return state.skills.filter((s) => {
      if (!state.showInactive && s.status !== 'active') return false;
      if (!state.showBuiltin && s.source_kind === 'builtin') return false;
      if (state.modeFilter === 'explicit' && s.invocation_mode !== 'explicit') return false;
      if (state.modeFilter === 'auto' && s.invocation_mode !== 'auto+slash' && s.invocation_mode !== 'auto-only') return false;
      if (state.sourceFilter !== 'all' && s.source_kind !== state.sourceFilter) return false;
      if (terms.length > 0) {
        const hay = (s.name + ' ' + s.description + ' ' + s.source_kind + ' ' + s.source_detail).toLowerCase();
        for (const term of terms) {
          if (!hay.includes(term)) return false;
        }
      }
      return true;
    });
  }

  function renderStats() {
    const active = state.skills.filter((s) => s.status === 'active');
    const pool = state.showBuiltin ? active : active.filter((s) => s.source_kind !== 'builtin');
    const autoCount = pool.filter((s) => s.invocation_mode === 'auto+slash' || s.invocation_mode === 'auto-only').length;
    const expCount = pool.filter((s) => s.invocation_mode === 'explicit').length;
    const warnCount = active.filter((s) => s.warnings && s.warnings.length > 0).length;
    const tokTotal = active.reduce((acc, s) => acc + (s.est_resident_tokens || 0), 0);

    const cards = [
      [t('statActive'), pool.length],
      [t('statAuto'), autoCount],
      [t('statExplicit'), expCount],
      [t('statTok'), '~' + tokTotal + ' tok'],
      [t('statWarn'), warnCount],
    ];
    els.stats.replaceChildren();
    for (const [label, val] of cards) {
      const card = el('div', 'stat-card');
      card.appendChild(el('div', 'stat-label', label));
      card.appendChild(el('div', 'stat-value', val));
      els.stats.appendChild(card);
    }
  }

  function renderFilterButtons() {
    els.btnAll.classList.toggle('active', state.modeFilter === 'all');
    els.btnAuto.classList.toggle('active', state.modeFilter === 'auto');
    els.btnExplicit.classList.toggle('active', state.modeFilter === 'explicit');
    els.btnBuiltin.classList.toggle('active', state.showBuiltin);
    els.btnInactive.classList.toggle('active', state.showInactive);
  }

  function renderList() {
    const items = getFiltered();
    els.list.replaceChildren();
    if (items.length === 0) {
      els.list.appendChild(el('div', 'skill-card', t('noMatch')));
      return;
    }
    for (const s of items) {
      const card = el('div', 'skill-card' + (s.id === state.selectedId ? ' selected' : '') + (s.status !== 'active' ? ' inactive' : ''));
      card.addEventListener('click', () => {
        state.selectedId = s.id;
        state.pendingToggle = null;
        renderList();
        renderDetail(s);
      });

      const top = el('div', 'card-top');
      const left = el('div');
      left.appendChild(el('span', 'skill-name', s.name));
      if (!s.disable_slash_command && s.status === 'active') {
        left.appendChild(el('span', 'slash-cmd', '/' + s.name));
      }
      top.appendChild(left);

      const badges = el('div', 'badges');
      badges.appendChild(el('span', modeBadgeClass(s), modeLabel(s)));
      badges.appendChild(el('span', 'badge badge-src', sourceLabel(s)));
      if (s.warnings && s.warnings.length > 0) {
        badges.appendChild(el('span', 'badge badge-warn', t('warnBadge') + s.warnings.length));
      }
      top.appendChild(badges);
      card.appendChild(top);

      card.appendChild(el('div', 'card-desc', s.description || ''));

      const meta = el('div', 'card-meta');
      meta.appendChild(el('span', '', t('scripts') + ': ' + s.scripts.length));
      meta.appendChild(el('span', '', t('refs') + ': ' + s.references.length));
      if (s.est_resident_tokens > 0) {
        meta.appendChild(el('span', '', t('resident') + ': ~' + s.est_resident_tokens + ' tok'));
      }
      if (s.shadowed_by) {
        meta.appendChild(el('span', '', t('shadowedBy') + ': ' + s.shadowed_by));
      }
      card.appendChild(meta);
      els.list.appendChild(card);
    }
  }

  async function fetchBody(skillId, preNode) {
    preNode.textContent = t('loading');
    try {
      const resp = await fetch('/api/body?id=' + encodeURIComponent(skillId), { cache: 'no-store' });
      const data = await resp.json();
      if (!resp.ok) {
        preNode.textContent = data.error || 'Error';
        return;
      }
      preNode.textContent = data.body || '';
    } catch (_err) {
      preNode.textContent = 'Request failed';
    }
  }

  async function applyModeChange(skill, targetMode) {
    try {
      const resp = await fetch('/api/mode', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': CSRF_TOKEN,
        },
        body: JSON.stringify({ id: skill.id, mode: targetMode }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        showToast(t('failedToast') + (data.error || resp.status));
        return;
      }
      state.pendingToggle = null;
      showToast(t('updatedToast'));
      await loadSkills(skill.id);
    } catch (_err) {
      showToast(t('failedToast') + 'network error');
    }
  }

  function renderDetail(s) {
    els.detail.replaceChildren();
    if (!s) {
      els.detail.appendChild(el('h2', '', t('emptyTitle')));
      els.detail.appendChild(el('div', 'subtitle', t('emptySub')));
      return;
    }

    els.detail.appendChild(el('h2', '', s.name));
    const badgeRow = el('div', 'badges');
    badgeRow.appendChild(el('span', modeBadgeClass(s), modeLabel(s)));
    badgeRow.appendChild(el('span', 'badge badge-src', sourceLabel(s)));
    els.detail.appendChild(badgeRow);

    function addMeta(k, v) {
      const row = el('div', 'meta-row');
      row.appendChild(el('span', 'meta-key', k + ':'));
      row.appendChild(el('span', '', v));
      els.detail.appendChild(row);
    }

    addMeta(t('slashCmd'), s.disable_slash_command ? t('slashOff') : '/' + s.name);
    addMeta(t('status'), s.status + (s.shadowed_by ? ' (' + t('shadowedBy') + ': ' + s.shadowed_by + ')' : ''));
    addMeta(t('filePath'), s.skill_md_path);
    if (s.is_symlink) addMeta(t('resolved'), s.resolved_path);
    addMeta(t('desc'), s.description || '');
    if (s.scripts.length > 0) addMeta(t('scripts'), s.scripts.join(', '));
    if (s.references.length > 0) addMeta(t('refs'), s.references.join(', '));

    if (s.warnings && s.warnings.length > 0) {
      for (const w of s.warnings) {
        els.detail.appendChild(el('div', 'confirm-box', '[!] ' + w));
      }
    }

    const actions = el('div', 'actions-bar');
    const toggleBtn = el('button', 'primary', s.disable_model_invocation ? t('toAuto') : t('toExplicit'));
    toggleBtn.disabled = !s.editable;
    toggleBtn.addEventListener('click', () => {
      state.pendingToggle = s.disable_model_invocation ? 'auto' : 'explicit';
      renderDetail(s);
    });
    actions.appendChild(toggleBtn);
    if (!s.editable) {
      actions.appendChild(el('span', 'subtitle', t('readOnly')));
    }
    els.detail.appendChild(actions);

    if (state.pendingToggle) {
      const box = el('div', 'confirm-box');
      const tgt = state.pendingToggle === 'explicit' ? t('modeExplicit') : t('modeAuto');
      box.appendChild(el('div', '', t('confirmMsg') + s.name + ' -> ' + tgt));
      const cActs = el('div', 'confirm-actions');
      const okBtn = el('button', 'primary', t('confirmWrite'));
      okBtn.addEventListener('click', () => applyModeChange(s, state.pendingToggle));
      const cancelBtn = el('button', '', t('cancel'));
      cancelBtn.addEventListener('click', () => {
        state.pendingToggle = null;
        renderDetail(s);
      });
      cActs.appendChild(okBtn);
      cActs.appendChild(cancelBtn);
      box.appendChild(cActs);
      els.detail.appendChild(box);
    }

    els.detail.appendChild(el('div', 'meta-key', t('previewHdr')));
    const pre = el('pre', 'md-preview', t('loading'));
    els.detail.appendChild(pre);
    fetchBody(s.id, pre);
  }

  function renderAll() {
    syncChromeStrings();
    renderStats();
    renderFilterButtons();
    renderList();
    const found = state.skills.find((x) => x.id === state.selectedId) || null;
    renderDetail(found);
  }

  async function loadSkills(keepSelectedId) {
    try {
      const resp = await fetch('/api/skills', { cache: 'no-store' });
      const data = await resp.json();
      state.skills = data.skills || [];
      if (keepSelectedId) state.selectedId = keepSelectedId;
      renderAll();
    } catch (_err) {
      showToast('Failed to load skills');
    }
  }

  els.search.addEventListener('input', (e) => { state.query = e.target.value; renderList(); });
  els.sourceSelect.addEventListener('change', (e) => { state.sourceFilter = e.target.value; renderList(); });
  els.btnAll.addEventListener('click', () => { state.modeFilter = 'all'; renderFilterButtons(); renderList(); });
  els.btnAuto.addEventListener('click', () => { state.modeFilter = 'auto'; renderFilterButtons(); renderList(); });
  els.btnExplicit.addEventListener('click', () => { state.modeFilter = 'explicit'; renderFilterButtons(); renderList(); });
  els.btnBuiltin.addEventListener('click', () => { state.showBuiltin = !state.showBuiltin; renderStats(); renderFilterButtons(); renderList(); });
  els.btnInactive.addEventListener('click', () => { state.showInactive = !state.showInactive; renderFilterButtons(); renderList(); });
  els.btnReload.addEventListener('click', () => loadSkills(state.selectedId));
  els.btnLang.addEventListener('click', () => {
    state.lang = state.lang === 'en' ? 'zh' : 'en';
    renderAll();
  });

  loadSkills(null);
})();
"""


def build_web_html(csrf_token: str, nonce: str, cwd_label: str, lang: str = "en") -> str:
    safe_csrf = html.escape(csrf_token, quote=True)
    safe_nonce = html.escape(nonce, quote=True)
    safe_cwd = html.escape(cwd_label, quote=True)
    safe_lang = "zh" if lang == "zh" else "en"
    return f"""<!DOCTYPE html>
<html lang="{safe_lang}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="csrf-token" content="{safe_csrf}" />
  <meta name="ui-lang" content="{safe_lang}" />
  <title>agy-skills</title>
  <style nonce="{safe_nonce}">{WEB_CSS}</style>
</head>
<body>
  <header>
    <div>
      <h1 id="page-title">agy-skills</h1>
      <div class="subtitle">Workspace: {safe_cwd} | 127.0.0.1 only</div>
    </div>
    <div class="header-actions">
      <button id="btn-lang" type="button">中文</button>
      <button id="btn-reload" type="button">Rescan Disk</button>
    </div>
  </header>
  <main class="container">
    <section id="stats" class="stats"></section>
    <section class="controls">
      <input id="search-input" type="search" placeholder="Search..." />
      <select id="source-select" aria-label="Source filter">
        <option id="opt-src-all" value="all">All Sources</option>
        <option value="global">Global (~/.gemini/config/skills)</option>
        <option value="plugin">Plugins</option>
        <option value="declared">skills.json</option>
        <option value="workspace">Workspace (.agents/.agent)</option>
        <option value="builtin">Built-in</option>
      </select>
      <button id="f-all" type="button">All Modes</button>
      <button id="f-auto" type="button">Auto-Trigger</button>
      <button id="f-explicit" type="button">Explicit /cmd</button>
      <button id="f-builtin" type="button">Show Built-in</button>
      <button id="f-inactive" type="button">Show Shadowed/Excl.</button>
    </section>
    <section class="layout">
      <div id="skill-list" class="skill-list"></div>
      <aside id="detail-pane" class="detail-pane"></aside>
    </section>
  </main>
  <div id="toast" class="toast" role="status" aria-live="polite"></div>
  <script nonce="{safe_nonce}">{WEB_JS}</script>
</body>
</html>
"""


def _is_within_allowed_roots(target: pathlib.Path, allowed_roots: list[pathlib.Path]) -> bool:
    resolved_target = str(target.resolve())
    for root in allowed_roots:
        resolved_root = str(root.resolve())
        if resolved_target == resolved_root or resolved_target.startswith(resolved_root + os.sep):
            return True
    return False


def run_web_server(cwd: pathlib.Path | None, port: int, lang: str = "en", home: pathlib.Path | None = None) -> int:
    home_dir = (home or pathlib.Path.home()).resolve()
    work_dir = (cwd or pathlib.Path.cwd()).resolve()
    # Localhost-only ephemeral CSRF token (never hardcoded, never logged)
    # TODO(security): Local single-user developer utility bound strictly to 127.0.0.1;
    # full OAuth/TLS is intentionally omitted for loopback-only local CLI inspection.
    csrf_token = secrets.token_urlsafe(32)
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    post_timestamps: list[float] = []

    class ReusableTCPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def _send_security_headers(self, nonce: str | None = None) -> None:
            if nonce:
                csp = (
                    f"default-src 'self'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                    "img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
                )
            else:
                csp = "default-src 'none'; frame-ancestors 'none'"
            self.send_header("Content-Security-Policy", csp)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._send_security_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _reject_method(self) -> None:
            self._send_json(405, {"error": "Method not allowed"})

        def do_PUT(self) -> None:
            self._reject_method()

        def do_DELETE(self) -> None:
            self._reject_method()

        def do_PATCH(self) -> None:
            self._reject_method()

        def do_OPTIONS(self) -> None:
            self._reject_method()

        def do_TRACE(self) -> None:
            self._reject_method()

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                nonce = secrets.token_urlsafe(16)
                page = build_web_html(csrf_token, nonce, str(work_dir).replace(str(home_dir), "~"), lang=lang).encode("utf-8")
                self.send_response(200)
                self._send_security_headers(nonce=nonce)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return

            if parsed.path == "/api/skills":
                records = discover_all_skills(cwd=work_dir, home=home_dir, lang=lang)
                self._send_json(200, {"skills": [r.to_dict() for r in records]})
                return

            if parsed.path == "/api/body":
                qs = urllib.parse.parse_qs(parsed.query)
                skill_id = (qs.get("id") or [""])[0]
                records = discover_all_skills(cwd=work_dir, home=home_dir, lang=lang)
                target = next((r for r in records if r.id == skill_id), None)
                if target is None:
                    self._send_json(404, {"error": "Skill not found"})
                    return
                try:
                    content = pathlib.Path(target.resolved_path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    self._send_json(500, {"error": "Failed to read SKILL.md"})
                    return
                self._send_json(200, {"id": target.id, "body": content})
                return

            self._send_json(404, {"error": "Not found"})

        def do_POST(self) -> None:
            now = time.monotonic()
            post_timestamps[:] = [ts for ts in post_timestamps if now - ts < 10.0]
            if len(post_timestamps) >= 30:
                self._send_json(429, {"error": "Too many requests"})
                return
            post_timestamps.append(now)

            origin = self.headers.get("Origin", "")
            if origin not in allowed_origins:
                self._send_json(403, {"error": "Forbidden origin"})
                return

            req_token = self.headers.get("X-CSRF-Token", "")
            if not req_token or not secrets.compare_digest(req_token, csrf_token):
                self._send_json(403, {"error": "Invalid CSRF token"})
                return

            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/api/mode":
                self._send_json(404, {"error": "Not found"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(400, {"error": "Invalid Content-Length"})
                return
            if length <= 0 or length > 8192:
                self._send_json(400, {"error": "Invalid request payload size"})
                return

            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self._send_json(400, {"error": "Malformed JSON"})
                return

            skill_id = str(body.get("id") or "")
            mode = str(body.get("mode") or "")
            if mode not in ("auto", "explicit"):
                self._send_json(400, {"error": "Invalid mode"})
                return

            records = discover_all_skills(cwd=work_dir, home=home_dir, lang=lang)
            target = next((r for r in records if r.id == skill_id and r.editable), None)
            if target is None:
                self._send_json(404, {"error": "Editable skill not found"})
                return

            skill_md = pathlib.Path(target.skill_md_path)
            allowed_root = skill_md.resolve().parent
            if skill_md.name != "SKILL.md" or not _is_within_allowed_roots(skill_md, [allowed_root]):
                self._send_json(403, {"error": "Path boundary violation"})
                return

            try:
                changed = update_disable_model_invocation(skill_md, explicit=(mode == "explicit"))
            except Exception:
                self._send_json(500, {"error": "Failed to update SKILL.md"})
                return

            self._send_json(200, {"ok": True, "changed": changed, "mode": mode})

    server = ReusableTCPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(paint(tr(lang, "web_started", url=url), Ansi.BOLD + Ansi.GREEN))
    print(paint(tr(lang, "web_hint", port=port), Ansi.DIM))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(tr(lang, "web_stopped"))
    finally:
        server.server_close()
    return 0


# ---------------------------------------------------------------------------
# Argument Parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agy-skills",
        description="Inspect, search, diagnose, and manage Agent Skills for Google Antigravity (agy).",
    )
    parser.add_argument("--version", action="version", version=f"agy-skills {VERSION}")
    parser.add_argument("--cwd", default=None, help="Inspect skills as if running agy in this workspace directory")
    parser.add_argument("--lang", choices=["en", "zh"], default=None, help="UI language (en or zh; env: AGY_SKILLS_LANG)")

    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", aliases=["ls"], help="List installed skills (hides built-in and inactive by default)")
    p_list.add_argument("-e", "--explicit", action="store_true", help="Only show explicit-only (/cmd) skills")
    p_list.add_argument("-a", "--auto", action="store_true", help="Only show auto-triggered skills")
    p_list.add_argument("-s", "--source", default=None, help="Filter by source (global|plugin|declared|workspace|builtin)")
    p_list.add_argument("-q", "--query", default=None, help="Filter by keyword in name/description/source")
    p_list.add_argument("--builtin", action="store_true", help="Include Antigravity built-in skills")
    p_list.add_argument("--all", action="store_true", help="Show everything including built-in, shadowed, and excluded")
    p_list.add_argument("--full", action="store_true", help="Show full wrapped descriptions")
    p_list.add_argument("--json", action="store_true", help="Output JSON")

    p_search = sub.add_parser("search", aliases=["find"], help="Search all skills by keyword")
    p_search.add_argument("keywords", nargs="+", help="Search keywords")
    p_search.add_argument("--body", action="store_true", help="Also search full SKILL.md body")
    p_search.add_argument("--all", action="store_true", help="Include shadowed and excluded skills")
    p_search.add_argument("--json", action="store_true", help="Output JSON")

    p_show = sub.add_parser("show", aliases=["info"], help="Show detailed metadata, scripts, and references for one skill")
    p_show.add_argument("name", help="Skill name")
    p_show.add_argument("--body", action="store_true", help="Print full SKILL.md content")
    p_show.add_argument("--json", action="store_true", help="Output JSON")

    p_mode = sub.add_parser("mode", aliases=["toggle"], help="Toggle disable-model-invocation (auto | explicit | toggle)")
    p_mode.add_argument("name", help="Skill name")
    p_mode.add_argument("target_mode", choices=["auto", "explicit", "toggle"], help="Target invocation mode")
    p_mode.add_argument("--force", action="store_true", help="Allow editing read-only sources")

    sub.add_parser("doctor", help="Audit shadowed skills, frontmatter warnings, and resident prompt token budget")
    sub.add_parser("tui", help="Open interactive terminal UI (curses)")

    p_web = sub.add_parser("web", help="Launch hardened localhost-only (127.0.0.1) web dashboard")
    p_web.add_argument("--port", type=int, default=8765, help="Port to bind on 127.0.0.1 (default: 8765)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)

    # Support running `agy-skills` (or `agy-skills --explicit`) without typing `list`
    subcommands = {"list", "ls", "search", "find", "show", "info", "mode", "toggle", "doctor", "tui", "web"}
    top_value_flags = {"--cwd", "--lang"}
    top_solo_flags = {"-h", "--help", "--version"}

    idx = 0
    has_subcmd = False
    has_top_help = False
    while idx < len(raw_argv):
        tok = raw_argv[idx]
        if tok in top_solo_flags and idx == 0:
            has_top_help = True
            break
        if tok in top_value_flags:
            idx += 2
            continue
        if any(tok.startswith(f + "=") for f in top_value_flags):
            idx += 1
            continue
        if tok in subcommands:
            has_subcmd = True
        break

    if not has_subcmd and not has_top_help:
        raw_argv.insert(idx, "list")

    args = parser.parse_args(raw_argv)
    lang = resolve_lang(args.lang)
    cmd = args.command or "list"

    if cmd in ("list", "ls"):
        return cmd_list(args, lang)
    if cmd in ("search", "find"):
        return cmd_search(args, lang)
    if cmd in ("show", "info"):
        return cmd_show(args, lang)
    if cmd in ("mode", "toggle"):
        return cmd_mode(args, lang)
    if cmd == "doctor":
        return cmd_doctor(args, lang)
    if cmd == "tui":
        return run_tui(pathlib.Path(args.cwd) if args.cwd else None, lang=lang)
    if cmd == "web":
        return run_web_server(pathlib.Path(args.cwd) if args.cwd else None, args.port, lang=lang)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
