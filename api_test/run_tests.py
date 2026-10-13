"""一键执行：跑测试 → 生成 Allure 报告 → 打开浏览器。

用法（在 api_test 目录下）：
    python run_tests.py                     # 全量跑
    python run_tests.py -m smoke            # 只跑冒烟
    python run_tests.py -m regression       # 只跑回归
    python run_tests.py -k 注入             # 按名字筛选用例
    python run_tests.py --no-open           # 跑完不自动开浏览器

【为什么要写这个脚本？】
原来跑一次要敲三段命令，而且中间任何一步忘了都会出问题：
  1. 没启动 Django 服务     → 44 条用例全挂，满屏 ConnectionError
  2. 忘了 generate         → 报告还是上一次的，看了个假结果
  3. 忘了 open             → 还得自己去翻目录

脚本把这些串成一条命令，并且【在跑之前先确认被测服务活着】——
失败要失败在第一步，而且要给出人话提示，而不是让 44 条用例替它背锅。
"""
import argparse
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent          # api_test/
RESULTS = ROOT / "allure_results"
REPORT = ROOT / "allure_report"
BASE_URL = "http://127.0.0.1:8000"

# 【Windows 的坑】allure 装出来其实是个 allure.bat（批处理脚本），
# 而 Python 的 subprocess 只认 .exe，不认 .bat ——
# 直接跑会报 [WinError 2] 系统找不到指定的文件，看起来像是"没装 allure"，
# 其实装了，只是没走 cmd.exe。
# 解法：先用 shutil.which 拿到完整路径，再交给 shell 执行。
ALLURE = shutil.which("allure") or "allure"


def run_allure(*args: str) -> subprocess.CompletedProcess:
    """调用 allure 命令行（自动处理 Windows 的 .bat 问题）。"""
    cmd = " ".join(f'"{a}"' for a in (ALLURE, *args))
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def check_server() -> bool:
    """被测服务活着吗？

    能收到任何 HTTP 响应（哪怕是 404、500）都算活着 ——
    那说明服务在跑，只是这个路径不存在。
    只有"连不上"才算没起来。
    """
    try:
        urllib.request.urlopen(f"{BASE_URL}/api/projects/", timeout=3)
        return True
    except urllib.error.HTTPError:
        return True          # 有响应 = 服务活着
    except Exception:
        return False         # 连不上 = 服务没起来


def main() -> int:
    parser = argparse.ArgumentParser(description="一键跑接口自动化测试")
    parser.add_argument("-m", "--marker", default="", help="只跑指定 marker: smoke / regression")
    parser.add_argument("-k", default="", help="按用例名筛选")
    parser.add_argument("--no-open", action="store_true", help="跑完不自动打开报告")
    args = parser.parse_args()

    # ---- 第 0 步：先确认被测服务活着 ----
    if not check_server():
        print("=" * 64)
        print("  ✗ 被测服务没起来，测试没法跑")
        print("=" * 64)
        print(f"\n  {BASE_URL} 连不上。先把它启动起来：\n")
        print('    cd D:/cekai/django')
        print('    ./.venv/Scripts/python.exe manage.py runserver\n')
        print("  然后再跑一次本脚本。")
        print("=" * 64)
        return 1

    # ---- 第 1 步：跑 pytest ----
    cmd = [sys.executable, "-m", "pytest"]
    if args.marker:
        cmd += ["-m", args.marker]
    if args.k:
        cmd += ["-k", args.k]

    print(f"执行: {' '.join(cmd)}\n")
    exit_code = subprocess.call(cmd, cwd=ROOT)

    # ---- 第 2 步：生成 Allure 报告 ----
    gen = run_allure("generate", str(RESULTS), "-o", str(REPORT), "--clean")
    if gen.returncode != 0:
        print("\n生成 Allure 报告失败：")
        print(gen.stdout or "", gen.stderr or "")
        return 1

    # ---- 第 3 步：打开报告 ----
    print()
    print("=" * 64)
    print(f"  报告已生成: {REPORT}")
    if not args.no_open:
        # 用 Popen（不等待）：allure open 会起一个本地 web 服务一直挂着，
        # 用 run 会把脚本卡死在这里。
        #
        # 【必须把子进程的输出接到 DEVNULL】
        # allure open 起的是常驻服务，它会一直占着继承来的 stdout。
        # 如果脚本的输出被管道接走（比如 `python run_tests.py | tail`），
        # 管道的写端永远不关闭，下游就会一直等 —— 表现成"脚本卡死"。
        subprocess.Popen(
            f'"{ALLURE}" open "{REPORT}"', shell=True, cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print("  正在打开浏览器...")
    print("=" * 64)

    # 把 pytest 的退出码原样传出去，方便接到 CI 上判断成败
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
