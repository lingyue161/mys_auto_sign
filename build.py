#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller 打包脚本
用法: python build.py
"""

import subprocess
import sys
import shutil
from pathlib import Path

def main():
    project_dir = Path(__file__).parent
    dist_dir = project_dir / "dist"

    # 安全检查：打包前删除 data 目录，防止账号凭证泄露
    data_dir = project_dir / "data"
    if data_dir.exists():
        print("[WARNING] data/ directory detected - may contain account credentials!")
        confirm = input("  Type 'yes' to delete data/ and continue: ")
        if confirm.strip().lower() != "yes":
            print("Build cancelled.")
            return
        shutil.rmtree(data_dir)
        print("[OK] data/ directory deleted")

    # 清理旧构建
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    build_dir = project_dir / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)

    # 使用相对路径打包图片资源（避免绝对路径 C: 与分隔符冲突）
    add_data_args = [
        "--add-data=ico.jpg:.",
        "--add-data=icon.ico:.",
        "--add-data=作者ico.jpg:.",
        "--add-data=贡献者3.jpg:.",
    ]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",           # 不弹出控制台窗口
        "--onefile",            # 打包成单个 exe
        "--name=米游社自动签到",
        "--icon=icon.ico",
        *add_data_args,
        "--hidden-import=requests",
        "--hidden-import=qrcode",
        "--hidden-import=PIL",
        "--hidden-import=mys_signer",
        f"--distpath={dist_dir}",
        f"--workpath={build_dir}",
        f"--specpath={project_dir}",
        str(project_dir / "main.py"),
    ]

    # 过滤掉空字符串参数
    cmd = [c for c in cmd if c]

    print("开始打包...")
    print(f"命令: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd, cwd=str(project_dir))

    if result.returncode == 0:
        exe_path = dist_dir / "米游社自动签到.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"\n打包成功！")
            print(f"输出文件: {exe_path}")
            print(f"文件大小: {size_mb:.1f} MB")
        else:
            print(f"\n打包完成，但未找到 exe 文件")
            print(f"请检查 dist 目录: {dist_dir}")
    else:
        print(f"\n打包失败，返回码: {result.returncode}")

if __name__ == "__main__":
    main()
