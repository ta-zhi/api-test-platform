"""压测数据清理脚本。

【为什么压测必须配一个清理脚本？】
压测会在短时间内往数据库灌进成百上千条数据。
如果不清理：
    1. 数据库越跑越脏，下次压测的起点就不一样了，结果没法复现；
    2. 列表接口返回的数据越来越大，性能越来越差，
       你分不清是"接口有问题"还是"垃圾数据太多"。

所以「造数据」和「清数据」是性能测试必备的一对工具。

【安全设计：怎么保证不误删你的真实数据？】
只删【名字以 perf- 开头】的记录 —— 那是压测脚本自己造的，
带前缀是 locustfile.py 里刻意设计的标记（PERF_PREFIX）。
你手动建的数据不会带这个前缀，所以永远不会被误伤。

用法：
    ./.venv/Scripts/python.exe perf_test/data_cleanup.py          # 先看看要删什么
    ./.venv/Scripts/python.exe perf_test/data_cleanup.py --yes    # 确认删除
"""

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "BienfanPlatform.settings")
sys.stdout.reconfigure(encoding="utf-8")
django.setup()

from suite.models import Project  # noqa: E402

# 【必须和 locustfile.py 里的 PERF_PREFIX 保持一致】
# 改了一处忘了另一处，就会出现"造了数据清不掉"的情况。
PERF_PREFIX = "perf-"


def main() -> int:
    targets = Project.objects.filter(name__startswith=PERF_PREFIX)
    total = Project.objects.count()

    print()
    print("=" * 60)
    print("  压测数据清理")
    print("=" * 60)
    print(f"  数据库总记录数 : {total}")
    print(f"  压测产生的记录 : {targets.count()}  (名字以 '{PERF_PREFIX}' 开头)")
    print(f"  执行后剩余     : {total - targets.count()}")
    print()

    if not targets.exists():
        print("  没有需要清理的数据 ✓")
        print("=" * 60)
        return 0

    # 先展示要删什么，让人确认 —— 这是删数据操作的基本素养
    print("  将要删除的记录：")
    for p in targets[:10]:
        print(f"    id={p.id}  name={p.name}")
    if targets.count() > 10:
        print(f"    ... 还有 {targets.count() - 10} 条")
    print()

    if "--yes" not in sys.argv:
        print("  这是预览模式，什么都没删。")
        print("  确认无误后，加上 --yes 参数真正执行：")
        print("    ./.venv/Scripts/python.exe perf_test/data_cleanup.py --yes")
        print("=" * 60)
        return 0

    deleted, _ = targets.delete()
    print(f"  已删除 {deleted} 条压测数据 ✓")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
