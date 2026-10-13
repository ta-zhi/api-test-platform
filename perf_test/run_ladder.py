r"""阶梯加压脚本：自动跑多档并发，采集数据，汇总成表。

【什么是阶梯加压？】
就是"一次比一次人多"地压：
    10 个虚拟用户跑 1 分钟 → 50 个跑 1 分钟 → 100 个跑 1 分钟

为什么要一档一档来，而不是直接上 100 人？
因为这样能看出**拐点在哪**：
    10 人时很快、50 人时开始变慢、100 人时直接崩 ——
    这个"从正常到劣化"的转折点，就是系统的容量上限。
直接上 100 人，你只知道"崩了"，不知道它是在哪个量级开始撑不住的。

【为什么要写脚本自动跑，而不是手敲三次命令？】
1. 手敲容易漏参数，三次的命令不完全一致，结果就没法对比；
2. 每档跑完要人工把数字抄下来 —— 抄错了整份报告就是错的；
3. 这个实验后面还要在不同数据量下重复做，手动做太累。

【脚本还会顺手监控服务端 CPU】
只压测、不看服务端状态，等于医生只看病人喊疼、不量体温。
CPU 打满说明瓶颈在计算（比如 JSON 序列化），
CPU 很低但很慢，说明瓶颈在等（比如数据库锁、磁盘 I/O）。
这两种情况要采取的优化手段完全不同。

用法：
    # 先确保被测服务在跑，然后：
    ..\.venv\Scripts\python.exe run_ladder.py 数据量标签
    # 例如：
    ..\.venv\Scripts\python.exe run_ladder.py 少量数据
    ..\.venv\Scripts\python.exe run_ladder.py 万条数据
"""

import csv
import subprocess
import sys
import time
from pathlib import Path

import psutil

# Windows 控制台默认用 GBK 编码，不设成 UTF-8，
# 下面那些 ▶ ✔ 之类的符号会直接抛 UnicodeEncodeError，脚本半路崩掉。
sys.stdout.reconfigure(encoding="utf-8")

PERF_DIR = Path(__file__).parent
RESULTS_DIR = PERF_DIR / "results"

# 三档并发人数
LEVELS = [10, 50, 100]

# 每档持续多久。太短了数据不稳定，太长了浪费时间，60 秒是个常用值。
DURATION = "60s"


def find_server_pids():
    """找出所有【看起来像】Django 服务的进程，仅用于出错时打印给人看。

    【注意：这个函数的结果不能用来判断"有几个服务器"】

    踩过的坑：一开始我按"命令行里同时含 manage.py 和 runserver"
    去数进程，数出来一堆，于是判定"有两个服务器在抢端口"，
    还花了很久去查一个根本不存在的竞争问题。

    真相是：启动一个 runserver，命令行里会同时出现三类进程 ——

        ① bash.exe        外层包装 shell（它的命令行里也含这串字）
        ② .venv/…/python.exe   venv 的【启动器】
        ③ Anaconda/python.exe 启动器拉起来的【真正干活的解释器】

    也就是说【一个服务 = 好几个进程】，靠命令行去数必然数错。

    【正确的做法：直接问操作系统谁占着端口】
    见 listening_pids()。端口的所有者才是唯一权威答案。
    这个函数现在只负责"出错时列出来给人看"，不参与判断。
    """
    pids = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            if not name.startswith("python"):
                continue          # 过滤掉 bash.exe 这类包装进程
            cmdline = " ".join(proc.info["cmdline"] or [])
            if "manage.py" in cmdline and "runserver" in cmdline:
                pids.append((proc.info["pid"], cmdline))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def run_one_level(users: int, tag: str, server_pid):
    """跑一档并发，返回统计数据。"""
    csv_prefix = RESULTS_DIR / f"{tag}_u{users}"
    # 加速率：每秒增加多少用户。用 users//10 让爬坡过程约 10 秒，不要太突兀。
    spawn_rate = max(1, users // 10)

    cmd = [
        sys.executable, "-m", "locust",
        "-f", "locustfile.py",
        "--headless",
        "-u", str(users),
        "-r", str(spawn_rate),
        "-t", DURATION,
        f"--csv={csv_prefix}",
        "--only-summary",          # 只输出最终汇总，不刷中间过程
    ]

    print(f"  ▶ {users:>3} 并发 ... ", end="", flush=True)

    started = time.perf_counter()
    proc = subprocess.Popen(
        cmd, cwd=PERF_DIR,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # ---- 边跑边采服务端 CPU ----
    cpu_samples = []
    if server_pid:
        try:
            sp = psutil.Process(server_pid)
            sp.cpu_percent(None)        # 预热：第一次调用总是返回 0，先丢弃
            while proc.poll() is None:
                cpu_samples.append(sp.cpu_percent(interval=0.5))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    proc.wait()
    elapsed = time.perf_counter() - started

    stats = read_aggregated(csv_prefix.with_name(csv_prefix.name + "_stats.csv"))

    # CPU 采样中，前几秒还在爬坡，取后 2/3 才算"满载时"的真实水平
    if cpu_samples:
        steady = cpu_samples[len(cpu_samples) // 3:]
        cpu_avg = sum(steady) / len(steady)
        cpu_max = max(steady)
    else:
        cpu_avg = cpu_max = 0.0

    print(f"完成（{elapsed:.0f}s，服务端 CPU 均值 {cpu_avg:.0f}%）")
    return stats, cpu_avg, cpu_max


def read_aggregated(csv_path: Path):
    """从 Locust 导出的 CSV 里，取出 Aggregated（汇总）那一行。"""
    if not csv_path.exists():
        return None
    # errors="replace"：Locust 导出的 CSV 里混有中文请求名（如"[预热] GET 列表"），
    # Windows 下它的编码不完全是 UTF-8，严格解码会直接抛异常。
    # 我们只关心 Aggregated 那一行（纯 ASCII），所以坏字符替换掉即可，不影响结果。
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f):
            # row[0] 是请求方法，row[1] 是名称。汇总行的名称是 Aggregated。
            if len(row) > 1 and row[1] == "Aggregated":
                return row
    return None


def parse(stats):
    """把 CSV 一行拆成我们要的指标。

    CSV 的列顺序（Locust 2.x）：
        0 方法 | 1 名称 | 2 请求数 | 3 失败数 | 4 中位数 | 5 平均
        6 最小 | 7 最大 | 8 平均响应体大小 | 9 每秒请求数(TPS) | 10 每秒失败数
        11 50% | 12 66% | 13 75% | 14 80% | 15 90% | 16 95% | 17 98% | 18 99% ...
    """
    if not stats:
        return None
    return {
        "requests": int(stats[2]),
        "failures": int(stats[3]),
        "avg": float(stats[5]),
        "size_kb": float(stats[8]) / 1024,
        "tps": float(stats[9]),
        "p50": float(stats[11]),
        "p95": float(stats[16]),
        "p99": float(stats[18]),
    }


def listening_pids(port: int = 8000):
    """返回所有正在监听该端口的进程号。

    这是比"扫进程命令行"更硬的证据：直接问操作系统，
    到底是谁占着这个端口。两者结合才能确认
    "跑着的服务"和"应答请求的服务"是同一个。
    """
    pids = set()
    try:
        for conn in psutil.net_connections(kind="inet"):
            if (conn.status == psutil.CONN_LISTEN
                    and conn.laddr and conn.laddr.port == port
                    and conn.pid):
                pids.add(conn.pid)
    except (psutil.AccessDenied, OSError):
        # 某些 Windows 环境下没有权限查连接表，退回到"未知"
        return None
    return pids


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else "默认"
    # 档位可以在命令行覆盖，方便"想往上试探容量上限"时临时加档：
    #     run_ladder.py 找上限 100,200,400
    levels = LEVELS
    if len(sys.argv) > 2:
        levels = [int(x) for x in sys.argv[2].split(",")]
    RESULTS_DIR.mkdir(exist_ok=True)

    # ---------------- 开跑前的环境体检 ----------------
    # 这段是踩坑之后加的。踩的坑：
    #   机器上同时跑着两个 runserver，都监听 8000。
    #   请求被分给谁不确定，采出来的数字一半是错的，
    #   还害我去怀疑代码，白折腾几小时。
    # 结论：压测前必须先确认"只有一个服务在跑"。
    #       数据干净比跑得快重要得多。
    listeners = listening_pids(8000)

    print()
    if listeners is None:
        print("  ⚠ 没有权限查询端口占用情况，跳过环境体检")
        print("    本次数据可用，但建议手工确认只有一个服务在跑")
        server_pid = None
    elif not listeners:
        print("  ✗ 8000 端口没有任何进程在监听，压测没法进行")
        print("    先启动服务：")
        print("      cd D:/cekai/django && ./.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000 --noreload")
        print()
        return 1
    elif len(listeners) > 1:
        # 这是真正危险的情况：两个进程都占着 8000，请求分给谁不确定，
        # 采出来的数据没有意义，而且极难排查。宁可拒绝跑。
        print(f"  ✗ 有多个进程同时监听 8000 端口：{sorted(listeners)}，拒绝压测")
        print()
        print("    为什么必须停下：请求被分给谁是不确定的，")
        print("    采出来的数据没法解释，等于白跑。")
        print()
        print("    先清干净（PID 换成上面列出的）：")
        for pid in sorted(listeners):
            print(f"      taskkill //F //PID {pid}")
        print()
        return 1
    else:
        server_pid = next(iter(listeners))
        # 顺带确认占着端口的确实是个 Django 服务，而不是别的程序
        matched = {pid for pid, _ in find_server_pids()}
        if server_pid not in matched:
            print(f"  ⚠ 占用 8000 端口的是 PID {server_pid}，但它看起来不像 Django 服务")
            print("    先确认你压的是不是想压的那个服务")
            print()

    print()
    print("=" * 78)
    print(f"  阶梯加压   |   数据量标签：{tag}   |   服务进程 PID：{server_pid}")
    print(f"  并发档位：{levels}　每档 {DURATION}")
    print("=" * 78)
    print()

    rows = []
    for users in levels:
        stats, cpu_avg, cpu_max = run_one_level(users, tag, server_pid)
        parsed = parse(stats)
        if parsed:
            parsed["users"] = users
            parsed["cpu_avg"] = cpu_avg
            parsed["cpu_max"] = cpu_max
            rows.append(parsed)

    # ---------------- 输出汇总表 ----------------
    print()
    print("=" * 78)
    print(f"  阶梯加压结果  |  {tag}")
    print("=" * 78)
    header = (f"  {'并发':>4} | {'请求数':>7} | {'失败':>5} | {'TPS':>7} | "
              f"{'平均(ms)':>8} | {'P95(ms)':>8} | {'P99(ms)':>8} | "
              f"{'响应体':>8} | {'服务端CPU':>9}")
    print(header)
    print("  " + "-" * 74)

    for r in rows:
        fail_rate = (r["failures"] / r["requests"] * 100) if r["requests"] else 0
        print(f"  {r['users']:>4} | {r['requests']:>7} | "
              f"{r['failures']:>5} | {r['tps']:>7.1f} | "
              f"{r['avg']:>8.0f} | {r['p95']:>8.0f} | {r['p99']:>8.0f} | "
              f"{r['size_kb']:>6.0f}KB | {r['cpu_avg']:>8.0f}%")

    print("  " + "-" * 74)
    if rows:
        print(f"  失败率：", end="")
        print("  ".join(
            f"{r['users']}并发={r['failures']/r['requests']*100:.1f}%"
            for r in rows if r["requests"]
        ))
    print("=" * 78)
    print(f"  原始数据已存到：{RESULTS_DIR}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
