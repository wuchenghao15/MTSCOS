#!/usr/bin/env python3
"""
EigenFlux 项目文件架构自动整理引擎
=====================================
扫描根目录散落的Python文件，按分类移动到合适的子目录，
自动更新所有import引用，创建__init__.py，并生成迁移报告。

用法:
    python3 eigenflux_file_organizer.py --dry-run    # 预览（不实际移动）
    python3 eigenflux_file_organizer.py --execute     # 执行整理
    python3 eigenflux_file_organizer.py --execute --category eigenflux  # 只整理eigenflux
"""

import os
import re
import sys
import json
import shutil
import ast
from pathlib import Path
from datetime import datetime
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

# ============================================================
#  文件分类规则
# ============================================================
CATEGORIES = {
    "eigenflux": {
        "target_dir": "services/eigenflux",
        "patterns": [r"^eigenflux_"],
        "description": "EigenFlux系统文件",
    },
    "education": {
        "target_dir": "services/education",
        "patterns": [r"^education_"],
        "description": "教育服务模块",
    },
    "ai": {
        "target_dir": "services/ai_modules",
        "patterns": [r"^ai_"],
        "description": "AI模块",
        "excludes": ["ai_engines"],  # 不移动ai_engines目录中的文件
    },
    "debug": {
        "target_dir": "scripts/debug",
        "patterns": [r"^debug_"],
        "description": "调试脚本",
    },
    "run": {
        "target_dir": "scripts",
        "patterns": [r"^run_"],
        "description": "运行脚本",
    },
    "test": {
        "target_dir": "tests",
        "patterns": [r"^test_", r"^_smoke_test_", r"^_test_"],
        "description": "测试文件",
    },
    "fix": {
        "target_dir": "scripts/fix",
        "patterns": [r"^fix_"],
        "description": "修复脚本",
    },
    "student": {
        "target_dir": "services/student",
        "patterns": [r"^student_"],
        "description": "学生服务",
    },
    "misc_service": {
        "target_dir": "services",
        "patterns": [r".*_service$", r".*_service\.py$"],
        "description": "通用服务",
    },
}

# 不移动的文件（核心入口文件）
KEEP_IN_ROOT = {
    "app.py",
    "server_real_db.py",
    "server_real_db_dev.py",
    "wsgi.py",
    "manage.py",
    "config.py",
    "settings.py",
}


class FileOrganizer:
    """文件架构整理引擎"""

    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.moved_files = []  # [(old_path, new_path, category)]
        self.updated_imports = []  # [(file, old_import, new_import)]
        self.created_dirs = []
        self.created_inits = []
        self.errors = []
        self.skipped = []

    def classify_file(self, filename: str) -> str:
        """根据文件名判断分类"""
        if filename in KEEP_IN_ROOT:
            return "keep"

        for category, config in CATEGORIES.items():
            for pattern in config["patterns"]:
                if re.match(pattern, filename):
                    # 确保不是excludes中指定的
                    if "excludes" in config:
                        for excl in config["excludes"]:
                            if excl in filename:
                                return "keep"
                    return category
        return "keep"

    def scan_root_files(self) -> dict:
        """扫描根目录下所有Python文件并分类"""
        result = defaultdict(list)
        for item in os.listdir(PROJECT_ROOT):
            if not item.endswith(".py"):
                continue
            filepath = os.path.join(PROJECT_ROOT, item)
            if not os.path.isfile(filepath):
                continue
            category = self.classify_file(item)
            result[category].append(item)
        return dict(result)

    def find_import_references(self, module_name: str) -> list:
        """查找所有引用了该模块的文件"""
        references = []
        for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
            # 跳过排除目录
            dirnames[:] = [
                d for d in dirnames
                if d not in {
                    "__pycache__", ".git", "node_modules", ".venv",
                    "venv", "env", "flask-app", "site-packages",
                    "_archive", "archive", "backups", "Database_Backups",
                }
            ]
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, "r", errors="ignore") as f:
                        content = f.read()
                    # 检查 import module_name 或 from module_name import
                    patterns = [
                        rf"(?<![\w.])import\s+{re.escape(module_name)}\b",
                        rf"(?<![\w.])from\s+{re.escape(module_name)}\s+import",
                    ]
                    for pat in patterns:
                        if re.search(pat, content):
                            rel_path = os.path.relpath(fpath, PROJECT_ROOT)
                            references.append(rel_path)
                            break
                except Exception:
                    pass
        return references

    def update_imports_in_file(self, filepath: str, old_module: str, new_module: str) -> int:
        """更新单个文件中的import引用"""
        try:
            with open(filepath, "r", errors="ignore") as f:
                content = f.read()
        except Exception:
            return 0

        original = content
        # from old_module import ... -> from new_module import ...
        content = re.sub(
            rf"(?<![\w.])from\s+{re.escape(old_module)}\s+import",
            f"from {new_module} import",
            content,
        )
        # import old_module -> import new_module as old_module (保持兼容)
        content = re.sub(
            rf"(?<![\w.])import\s+{re.escape(old_module)}\b(?!_)",
            f"import {new_module} as {old_module}",
            content,
        )

        if content != original:
            if not self.dry_run:
                with open(filepath, "w") as f:
                    f.write(content)
            self.updated_imports.append((filepath, old_module, new_module))
            return 1
        return 0

    def move_file(self, filename: str, category: str) -> bool:
        """移动单个文件到目标目录"""
        config = CATEGORIES.get(category)
        if not config:
            return False

        old_path = PROJECT_ROOT / filename
        target_dir = PROJECT_ROOT / config["target_dir"]
        new_path = target_dir / filename

        if not old_path.exists():
            self.errors.append(f"源文件不存在: {filename}")
            return False

        if new_path.exists():
            self.skipped.append(f"目标已存在: {new_path}")
            return False

        # 查找引用
        module_name = filename.replace(".py", "")
        references = self.find_import_references(module_name)
        new_module = f"{config['target_dir'].replace('/', '.')}.{module_name}"

        if self.dry_run:
            print(f"  [DRY-RUN] {filename} -> {config['target_dir']}/{filename}")
            if references:
                print(f"           引用更新: {len(references)}个文件")
                for ref in references[:5]:
                    print(f"             - {ref}")
                if len(references) > 5:
                    print(f"             ... 还有{len(references) - 5}个")
            self.moved_files.append((str(old_path), str(new_path), category))
            return True

        # 实际执行
        # 1. 创建目标目录
        target_dir.mkdir(parents=True, exist_ok=True)
        if str(target_dir) not in self.created_dirs:
            self.created_dirs.append(str(target_dir))

        # 2. 创建__init__.py
        init_file = target_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text(f'"""{config["description"]}"""\n')
            self.created_inits.append(str(init_file))

        # 3. 移动文件
        shutil.move(str(old_path), str(new_path))
        self.moved_files.append((str(old_path), str(new_path), category))

        # 4. 更新所有引用
        for ref in references:
            ref_path = os.path.join(PROJECT_ROOT, ref)
            self.update_imports_in_file(ref_path, module_name, new_module)

        return True

    def organize(self, categories: list = None):
        """执行整理"""
        print(f"\n{'=' * 60}")
        print(f"  EigenFlux 文件架构整理引擎")
        print(f"  模式: {'预览 (DRY-RUN)' if self.dry_run else '执行 (EXECUTE)'}")
        print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 60}\n")

        # 扫描
        classified = self.scan_root_files()
        total = sum(len(v) for k, v in classified.items() if k != "keep")
        keep_count = len(classified.get("keep", []))

        print(f"根目录Python文件总数: {total + keep_count}")
        print(f"  待整理: {total}")
        print(f"  保留在根目录: {keep_count}")
        print()

        for category in sorted(CATEGORIES.keys()):
            if categories and category not in categories:
                continue
            files = classified.get(category, [])
            if not files:
                continue

            config = CATEGORIES[category]
            print(f"--- {config['description']} ({category}) ---")
            print(f"    目标: {config['target_dir']}/")
            print(f"    文件数: {len(files)}")

            for fname in sorted(files):
                self.move_file(fname, category)

            print()

        # 汇总
        self.print_summary()
        self.save_report()

    def print_summary(self):
        """打印汇总"""
        print(f"\n{'=' * 60}")
        print(f"  整理汇总")
        print(f"{'=' * 60}")
        print(f"  移动文件:     {len(self.moved_files)}")
        print(f"  创建目录:     {len(self.created_dirs)}")
        print(f"  创建__init__: {len(self.created_inits)}")
        print(f"  更新引用:     {len(self.updated_imports)}")
        print(f"  跳过:         {len(self.skipped)}")
        print(f"  错误:         {len(self.errors)}")

        if self.errors:
            print(f"\n  错误详情:")
            for e in self.errors:
                print(f"    - {e}")

        if self.updated_imports:
            print(f"\n  引用更新示例 (前10个):")
            for filepath, old, new in self.updated_imports[:10]:
                rel = os.path.relpath(filepath, PROJECT_ROOT)
                print(f"    {rel}: {old} -> {new}")

    def save_report(self):
        """保存迁移报告"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "mode": "dry-run" if self.dry_run else "execute",
            "summary": {
                "moved_files": len(self.moved_files),
                "created_dirs": len(self.created_dirs),
                "created_inits": len(self.created_inits),
                "updated_imports": len(self.updated_imports),
                "skipped": len(self.skipped),
                "errors": len(self.errors),
            },
            "moved_files": [
                {"old": o, "new": n, "category": c}
                for o, n, c in self.moved_files
            ],
            "updated_imports": [
                {"file": f, "old": o, "new": n}
                for f, o, n in self.updated_imports
            ],
            "errors": self.errors,
            "skipped": self.skipped,
        }

        report_path = PROJECT_ROOT / "logs" / f"file_organizer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  报告已保存: {report_path}")

        # 同时保存最新报告
        latest_path = PROJECT_ROOT / "logs" / "file_organizer_latest.json"
        with open(latest_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)


def main():
    dry_run = "--execute" not in sys.argv
    categories = None

    # 解析 --category 参数
    for i, arg in enumerate(sys.argv):
        if arg == "--category" and i + 1 < len(sys.argv):
            categories = sys.argv[i + 1].split(",")

    organizer = FileOrganizer(dry_run=dry_run)
    organizer.organize(categories=categories)


if __name__ == "__main__":
    main()
