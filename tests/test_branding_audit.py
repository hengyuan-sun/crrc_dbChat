import json
import os
from pathlib import Path
import subprocess
import sys

from scripts.branding_audit import audit_paths, scan_text


def test_scan_text_reports_case_sensitive_identifiers_on_their_lines():
    """验证扫描器按大小写区分标识并报告准确行号。"""
    lowercase_token = "dbg" + "pt"
    uppercase_token = "DB" + "-GPT"
    findings = scan_text(
        f"ok\n{lowercase_token} and {uppercase_token}\ncrrc_dbChat\n",
        [lowercase_token, uppercase_token],
    )

    assert [(item.line, item.identifier) for item in findings] == [
        (2, uppercase_token),
        (2, lowercase_token),
    ]


def test_audit_paths_skips_only_explicitly_allowlisted_files(tmp_path: Path):
    """验证扫描只跳过配置中逐项许可的文件。"""
    legacy_token = "dbg" + "pt"
    (tmp_path / "source.py").write_text(f"{legacy_token}\n", encoding="utf-8")
    (tmp_path / "history.csv").write_text(f"{legacy_token}\n", encoding="utf-8")

    findings = audit_paths(
        tmp_path,
        ["source.py", "history.csv"],
        [legacy_token],
        ["history.csv"],
    )

    assert [(item.path, item.line, item.identifier) for item in findings] == [
        ("source.py", 1, legacy_token)
    ]


def test_audit_paths_ignores_binary_files_but_keeps_text_findings(tmp_path: Path):
    """验证扫描器跳过二进制内容且继续报告文本残留。"""
    lower_token = "dbg" + "pt"
    upper_token = "DB" + "GPT"
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00" + lower_token.encode())
    (tmp_path / "source.py").write_text(f"{upper_token}\n", encoding="utf-8")

    findings = audit_paths(
        tmp_path,
        ["logo.png", "source.py"],
        [upper_token],
        [],
    )

    assert [(item.path, item.identifier) for item in findings] == [
        ("source.py", upper_token)
    ]


def test_cli_emits_utf8_json_when_console_encoding_cannot_print_a_hit(tmp_path: Path):
    """验证 Windows GBK 控制台仍能输出包含特殊字符的 UTF-8 报告。"""
    root = tmp_path
    legacy_token = "dbg" + "pt"
    mapping_dir = root / "docs" / "enterprise"
    mapping_dir.mkdir(parents=True)
    (mapping_dir / "identifier-inventory.csv").write_text(
        f"legacy_token\n{legacy_token}\n", encoding="utf-8"
    )
    (mapping_dir / "branding-allowlist.txt").write_text(
        "docs/enterprise/identifier-inventory.csv\n", encoding="utf-8"
    )
    (root / "source.py").write_text(f"{legacy_token}\u200b\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "--quiet"], check=True)
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "gbk"

    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "scripts" / "branding_audit.py"),
            "--root",
            str(root),
            "--format",
            "json",
        ],
        capture_output=True,
        env=environment,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout.decode("utf-8"))
    assert report["count"] == 1
    assert report["findings"][0]["snippet"] == f"{legacy_token}\u200b"
