"""检查仓库自有文本中尚未迁移的历史标识。"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Finding:
    """记录一个文件行中出现的历史标识。"""

    path: str
    line: int
    identifier: str
    snippet: str


def scan_text(text: str, identifiers: Iterable[str]) -> list[Finding]:
    """按行检查文本，并返回区分大小写的历史标识命中。"""
    tokens = sorted({token for token in identifiers if token}, key=str.casefold)
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for token in tokens:
            if token in line:
                findings.append(
                    Finding(
                        path="",
                        line=line_number,
                        identifier=token,
                        snippet=line.strip()[:240],
                    )
                )
    return findings


def _normalize_path(path: str | Path) -> str:
    """将仓库内路径规范为便于清单匹配的 POSIX 形式。"""
    return Path(path).as_posix().removeprefix("./")


def _is_allowlisted(path: str, allowlist: Iterable[str]) -> bool:
    """只匹配明确列出的文件或以斜杠结尾的目录前缀。"""
    normalized = _normalize_path(path)
    for entry in allowlist:
        candidate = _normalize_path(entry.strip())
        if not candidate or candidate.startswith("#"):
            continue
        if candidate.endswith("/") and normalized.startswith(candidate):
            return True
        if normalized == candidate:
            return True
    return False


def audit_paths(
    root: Path,
    paths: Iterable[str | Path],
    identifiers: Iterable[str],
    allowlist: Iterable[str],
) -> list[Finding]:
    """检查文件集合，跳过白名单和不可解码的二进制内容。"""
    findings: list[Finding] = []
    tokens = tuple(identifiers)
    allowed = tuple(allowlist)
    for relative_path in sorted({_normalize_path(path) for path in paths}):
        if _is_allowlisted(relative_path, allowed):
            continue
        candidate = root.joinpath(*relative_path.split("/"))
        try:
            raw = candidate.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        for item in scan_text(text, tokens):
            findings.append(
                Finding(
                    path=relative_path,
                    line=item.line,
                    identifier=item.identifier,
                    snippet=item.snippet,
                )
            )
    return findings


def _load_identifiers(map_path: Path) -> list[str]:
    """从迁移映射 CSV 读取要检查的历史标识。"""
    with map_path.open("r", encoding="utf-8-sig", newline="") as mapping_file:
        return [
            row["legacy_token"].strip()
            for row in csv.DictReader(mapping_file)
            if row.get("legacy_token", "").strip()
        ]


def _git_paths(root: Path) -> list[str]:
    """读取 Git 跟踪和未跟踪文件，并遵循仓库忽略规则。"""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8", errors="replace") for item in result.stdout.split(b"\x00") if item]


def _read_allowlist(path: Path) -> list[str]:
    """读取逐行配置的精确文件或目录豁免项。"""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _render(findings: Sequence[Finding], output_format: str) -> str:
    """将扫描结果渲染为便于人工查看或机器处理的格式。"""
    if output_format == "json":
        return json.dumps(
            {"count": len(findings), "findings": [asdict(item) for item in findings]},
            ensure_ascii=False,
            indent=2,
        )
    if not findings:
        return "未发现未豁免的历史标识。"
    return "\n".join(
        f"{item.path}:{item.line}: {item.identifier}: {item.snippet}"
        for item in findings
    )


def main(argv: Sequence[str] | None = None) -> int:
    """运行品牌标识审计命令，并以退出码区分是否存在残留。"""
    for output_stream in (sys.stdout, sys.stderr):
        if hasattr(output_stream, "reconfigure"):
            output_stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="审计仓库中的历史产品标识")
    parser.add_argument("--root", type=Path, default=default_root, help="Git 仓库根目录")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    arguments = parser.parse_args(argv)
    root = arguments.root.resolve()
    map_path = root / "docs/enterprise/identifier-inventory.csv"
    allowlist_path = root / "docs/enterprise/branding-allowlist.txt"
    try:
        identifiers = _load_identifiers(map_path)
        allowlist = _read_allowlist(allowlist_path)
        paths = _git_paths(root)
        findings = audit_paths(root, paths, identifiers, allowlist)
    except (OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"审计初始化失败：{error}", file=sys.stderr)
        return 2
    print(_render(findings, arguments.format))
    if arguments.format == "text":
        print(f"共发现 {len(findings)} 行未豁免的历史标识。")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
