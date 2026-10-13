r"""接口耗时三层拆解工具 —— 「这个接口到底慢在哪一节？」

【为什么需要它？】
压测只能告诉你【慢】这个结论，告诉不了你【慢在哪】。
Locust 说 P95 是 51 秒，然后呢？是数据库慢？代码慢？网络慢？
没有下一层信息，优化就只能靠猜，而猜错的代价很大。

【三层拆解的思路】
把一次请求，从"纯计算"到"完整走网络"，分层测量：

    第 1 层  纯计算        —— 直接调 ORM + 转字典 + 序列化，不起服务器
    第 2 层  Django 请求处理 —— 用 testing Client，走完整中间件/视图，但不走网络
    第 3 层  真实 HTTP      —— 打真的服务器，测 TTFB 和总耗时

于是每一层的差额，就是那一层自己的开销：
    第 2 层 - 第 1 层  = Django 中间件 / 请求构造 / 响应构造 的开销
    第 3 层 - 第 2 层  = WSGI 服务器 + TCP + 发送 的开销

【这个方法是踩坑踩出来的，说个真实事故】
当时发现：接口真实请求要 500ms，可第 1 层拆解只算出 75ms。
中间 400 多毫秒凭空消失，怎么都想不通，一度怀疑是 JSON 序列化器的问题。

真相是：机器上同时跑着【两个】Django 服务，都绑在 8000 端口
（Windows 的 SO_REUSEADDR 允许这么做），请求被分给谁是不确定的。
也就是说 —— 我拿"进程 A 的代码耗时"去解释"进程 B 的响应时间"，
两边根本不是同一个对象，当然对不上。

清掉多余进程后，三层数据立刻自洽：75ms / 84ms / 100ms。

教训有两条：
    1. 测量之前先确认"被测对象是唯一且明确的"，否则数据再漂亮也没意义；
    2. 分层测量本身就是最好的排错手段 —— 它把"猜"变成了"量"。

用法：
    ./.venv/Scripts/python.exe perf_test/profile_view.py
"""

import json
import os
import sys
import time
import urllib.request

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "BienfanPlatform.settings")
sys.stdout.reconfigure(encoding="utf-8")
django.setup()

from django.test import Client  # noqa: E402

from suite.models import Project  # noqa: E402

URL = "http://127.0.0.1:8000/api/projects/"
PATH = "/api/projects/"
ROUNDS = 5


def ms(t0, t1):
    return (t1 - t0) * 1000


def layer1_pure_compute():
    """第 1 层：不起服务器，直接量代码本身要多久。"""
    # ---- ① 查数据库 + 建 ORM 对象 ----
    t0 = time.perf_counter()
    rows = list(Project.objects.all().order_by("id"))
    t1 = time.perf_counter()

    # ---- ② 逐条转成字典 ----
    projects = [p.to_dict() for p in rows]
    t2 = time.perf_counter()

    # ---- ③ 序列化成 JSON 文本 ----
    text = json.dumps(projects)
    t3 = time.perf_counter()

    return {
        "查询+建对象": ms(t0, t1),
        "转字典": ms(t1, t2),
        "序列化": ms(t2, t3),
        "合计": ms(t0, t3),
        "体积KB": len(text) / 1024,
        "条数": len(rows),
    }


def layer2_django_handler():
    """第 2 层：走完整 Django 请求流程，但不走网络、不起 WSGI 服务器。"""
    c = Client()
    host = {"HTTP_HOST": "127.0.0.1"}
    c.get(PATH, **host)                      # 暖机：首次要建连接、加载 URL 表

    ts = []
    size = 0
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        r = c.get(PATH, **host)
        ts.append(ms(t0, time.perf_counter()))
        size = len(r.content)
    return sum(ts) / len(ts), size


def layer3_real_http():
    """第 3 层：真实 HTTP。分别量首字节时间(TTFB)和总耗时。

    TTFB 是关键指标：它衡量"服务器多久才开始回应"。
    如果 TTFB ≈ 总耗时，说明时间花在服务端处理上；
    如果总耗时远大于 TTFB，说明时间花在传输响应体上。
    """
    ttfb, total, size = [], [], 0
    for _ in range(ROUNDS):
        t0 = time.perf_counter()
        with urllib.request.urlopen(URL) as resp:
            resp.read(1)                      # 只读 1 字节 → 拿到"首字节时刻"
            t1 = time.perf_counter()
            rest = resp.read()                # 剩下的读完
            t2 = time.perf_counter()
            size = 1 + len(rest)
        ttfb.append(ms(t0, t1))
        total.append(ms(t0, t2))
    return sum(ttfb) / len(ttfb), sum(total) / len(total), size


def main() -> int:
    count = Project.objects.count()

    print()
    print("=" * 72)
    print("  接口耗时三层拆解")
    print("=" * 72)
    print(f"  目标接口   : {URL}")
    print(f"  当前记录数 : {count}")
    if count < 1000:
        print()
        print("  ⚠ 数据量偏小，瓶颈很可能压不出来。")
        print("    先造数据再测： ./.venv/Scripts/python.exe perf_test/data_prepare.py 10000")
    print("=" * 72)
    print()

    # ---------------- 第 1 层 ----------------
    l1 = layer1_pure_compute()
    print("  【第 1 层】纯计算（不起服务器、不走网络）")
    print(f"      ① 查数据库 + 建 ORM 对象 : {l1['查询+建对象']:7.0f} ms")
    print(f"      ② 逐条转成字典           : {l1['转字典']:7.0f} ms")
    print(f"      ③ 序列化成 JSON          : {l1['序列化']:7.0f} ms")
    print(f"      ─────────────────────────────────────")
    print(f"      合计                     : {l1['合计']:7.0f} ms"
          f"   （{l1['条数']} 条，{l1['体积KB']:.0f} KB）")
    print()

    # ---------------- 第 2 层 ----------------
    try:
        l2, l2_size = layer2_django_handler()
    except Exception as exc:
        print(f"  【第 2 层】失败：{exc}")
        l2 = None
    if l2 is not None:
        print("  【第 2 层】Django 请求处理（走中间件和视图，不走网络）")
        print(f"      平均 {l2:.0f} ms   （响应体 {l2_size/1024:.0f} KB）")
        print(f"      比第 1 层多出 {l2 - l1['合计']:.0f} ms  ← 中间件 / 请求响应构造的开销")
        print()

    # ---------------- 第 3 层 ----------------
    ttfb, total, l3_size = layer3_real_http()
    print("  【第 3 层】真实 HTTP（打真正的服务器）")
    print(f"      TTFB（首字节）: {ttfb:7.0f} ms")
    print(f"      总耗时        : {total:7.0f} ms   （响应体 {l3_size/1024:.0f} KB）")
    print(f"      传输耗时      : {total - ttfb:7.0f} ms  ← 总耗时 - TTFB")
    if l2 is not None:
        print(f"      比第 2 层多出  : {ttfb - l2:7.0f} ms  ← WSGI 服务器 + TCP 的开销")
    print()

    print("=" * 72)
    print("  怎么读这张表：")
    print("    · 如果某一层的差额特别大，瓶颈就在那一层，往那一层查")
    print("    · TTFB ≈ 总耗时  → 时间花在服务端处理，不是传数据慢")
    print("    · 传输耗时很大    → 响应体太大，该做分页/字段裁剪/压缩")
    print("=" * 72)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
