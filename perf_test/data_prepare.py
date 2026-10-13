"""压测数据准备脚本（造数据）。

【为什么性能测试必须先造数据？】
因为性能问题往往不是"代码写错了"，而是"数据量大了才暴露"。

举个你接口里的真实例子（suite/views.py 的列表接口）：
    projects = [p.to_dict() for p in Project.objects.all()]

这行代码会把库里【所有】项目一次性查出来返回，没有分页。

    库里 2 条    →  毫秒级返回，看起来毫无问题
    库里 1 万条  →  每次请求要实例化 1 万个对象、序列化 1 万个 JSON，
                     响应时间飙升，响应体好几 MB

功能测试永远发现不了这个问题，因为功能是对的 —— 它只是慢。
**只有把数据量拉起来，问题才会浮现。** 这就是造数据脚本存在的意义。

【为什么用 bulk_create 而不是循环 .create()？】
    for i in range(10000):
        Project.objects.create(name=...)     # 慢：执行 1 万次 SQL、1 万次事务

    Project.objects.bulk_create(batch)       # 快：拼成几条批量 INSERT

造 1 万条数据，前者要几十秒，后者 1 秒内搞定。
这是 Django 里最常用的一个性能技巧，面试也常问。

用法：
    ./.venv/Scripts/python.exe perf_test/data_prepare.py 10000

注意：造出来的数据名字都带 perf- 前缀，
      压测结束后用 data_cleanup.py 一键清掉，不会污染你的真实数据。
"""

import os
import sys
import time

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "BienfanPlatform.settings")
sys.stdout.reconfigure(encoding="utf-8")
django.setup()

from suite.models import Project  # noqa: E402

# 【前缀必须和 locustfile.py 配合，不能随便改】
#   perf-seed-*  这里的"种子数据"：预先进库、压测期间只读不删
#   perf-load-*  locustfile.py 压测过程中创建的：稍后会被删掉
#
# locustfile 的预热逻辑靠这个前缀区分"哪些数据可以安全读取"。
# 统一用 perf- 开头，data_cleanup.py 才能一次清掉两种。
PERF_PREFIX = "perf-seed-"

# 每批插入多少条。太大占内存，太小失去批量优势，1000 是个常用值。
BATCH_SIZE = 1000


def prepare(count: int) -> None:
    """往数据库里灌 count 条压测数据。"""
    print(f"  正在生成 {count} 条数据 ...")

    before = Project.objects.count()

    # 先把对象在内存里全建好，再一次性批量写库
    batch = [
        Project(name=f"{PERF_PREFIX}数据-{i}", description=f"压测数据第 {i} 条")
        for i in range(count)
    ]

    start = time.perf_counter()
    # ignore_conflicts=False：正常插入。如果有唯一约束冲突会报错，方便发现问题。
    Project.objects.bulk_create(batch, batch_size=BATCH_SIZE)
    cost = time.perf_counter() - start

    after = Project.objects.count()
    print(f"  完成：{before} 条 → {after} 条，耗时 {cost:.2f} 秒")
    if cost > 0:
        print(f"  写入速度：约 {count / cost:,.0f} 条/秒")
    print()


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10000

    print()
    print("=" * 60)
    print("  压测数据准备")
    print("=" * 60)

    prepare(count)

    print("  提示：")
    print("    - 现在可以跑 locustfile.py 观察接口在大数据量下的表现了")
    print("    - 测完记得清理：perf_test/data_cleanup.py --yes")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
