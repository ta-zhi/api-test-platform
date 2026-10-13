"""测试套件执行器：按套件类型把用例跑起来，产出一份 Allure 报告。

【这个文件和 TestTask.save() 里的老逻辑是什么关系？】
不是替换，是并存。
    TestTask    —— 老的执行方式，写在 model 的 save() 里，跑用户上传的用例。
    runner.py   —— 新的执行方式，独立成模块，跑平台内置的套件。

为什么新的要抽出来？因为把执行逻辑写在 save() 里有三个硬伤：
    1. 保存一次数据库就触发一次跑测试 —— 想看数据、不想跑测试的时候也跑
    2. 出异常没有任何兜底，状态永远卡在"执行中"
    3. 逻辑和模型耦合，没法单独调用、没法测试、没法被别的地方复用

（TestTask 那套的这些问题属于 P1，本文件先不动它。）

【为什么用子进程，而不是直接 pytest.main()？】
如果直接在 Django 进程里调 pytest.main()：
    - pytest 会接管日志、信号、sys.path，跟 Django 自己抢地盘
    - 跑一次之后，Django 进程里就残留了一堆 pytest 的状态，第二次跑可能就不对了
    - 将来要改成异步（后台线程 / Celery），子进程是唯一能干净剥离的方式
代价是慢一点点（起一个 Python 进程约几百毫秒），对这个场景完全可以接受。

【支持两种套件，靠 suite_type 分派】
    api_test   接口自动化套件：子进程跑 pytest，产出 allure 结果
    game_test  游戏自动化套件：子进程跑团结引擎的批处理测试（NUnit XML），
               先转成标准 allure 结果目录，再统一生成报告

两者【各出一份报告】，不合并。
分派只影响"怎么拿到 allure 结果目录"，后面的生成报告、写回状态是同一套代码。

【游戏套件为什么要在游戏项目里自己转格式？】
这样本文件不需要知道 NUnit、Unity、团结引擎的存在 ——
它的输入契约就是标准的 allure-results 目录，和 api_test 完全一样。
转换器在 D:\\RPG GAME\\RPG GAME\\Tools\\nunit-to-allure.py，和 run-tests.sh 放在一起，
将来改测试脚本的人会在同一个目录里看到它。
"""

import logging
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from django.conf import settings
from django.db import connection

from .models import TestSuite

logger = logging.getLogger(__name__)

# ---- 路径统一在这里算清楚，别散落在各处 ----
API_TEST_DIR = Path(settings.BASE_DIR) / "api_test"
ALLURE_RESULTS = API_TEST_DIR / "allure_results"

# 【MEDIA_ROOT 是相对路径 'uploads/'，不能直接用】
# Django 自己解析 MEDIA_ROOT 时是相对「启动 runserver 时的工作目录」的。
# 我们写文件不能赌用户当时在哪个目录敲的命令，所以主动拼成绝对路径。
_media = Path(settings.MEDIA_ROOT)
MEDIA_ROOT_ABS = _media if _media.is_absolute() else Path(settings.BASE_DIR) / _media

# 被测服务地址。api_test 的 config/settings.py 里 dev 环境指向的就是它。
BASE_URL = "http://127.0.0.1:8000"

# 跑一条套件的超时时间（秒）。防止被测服务半死不活时把 Django 进程永远挂住。
PYTEST_TIMEOUT = 300

# Windows 下 allure 是个 .bat，subprocess 只认 .exe —— 要先 which 出来再交给 shell。
ALLURE = shutil.which("allure") or "allure"

# ---- 游戏套件（团结引擎）相关 ----
#
# 这几个常量按本文件的既有惯例放在顶部（不放 settings.py：
# 平台目前一个自定义业务配置项都没有，不在这次改动里破例）。
GAME_PROJECT_DIR = Path(r"D:\RPG GAME\RPG GAME")
GAME_RUN_SCRIPT = GAME_PROJECT_DIR / "Tools" / "run-tests.sh"
GAME_CONVERTER = GAME_PROJECT_DIR / "Tools" / "nunit-to-allure.py"
GAME_ALLURE_RESULTS = GAME_PROJECT_DIR / "allure-results"

# run-tests.sh 是 bash 脚本（用到 cygpath 把路径转成 Windows 形式）。
# 【这个 which 有个已知的坑】Windows 上 `bash` 可能有三个候选：
#   C:\Program Files\Git\usr\bin\bash.exe         ← 我们要的 Git Bash
#   C:\Windows\System32\bash.exe                  ← WSL bash，看不到 D: 盘
#   ...\WindowsApps\bash.exe                      ← 应用商店的存根
# 目前 PATH 顺序里 Git Bash 排第一，所以是对的。
# 换机器如果出问题，第一个要怀疑的就是这里被解析成了 WSL bash。
GAME_BASH = shutil.which("bash") or "bash"

# 团结引擎批处理是重活：Library 预热后约 30 秒，冷启动实测约 186 秒。
# 平台上现成的 PYTEST_TIMEOUT = 300 对这个场景不够安全，单独给一个。
GAME_RUN_TIMEOUT = 900


# ---- 正在后台执行的套件（异步执行用）----
#
# 【为什么要有这个名单？】
# 同一个套件被连点两次，会起两个后台线程，同时往同一个 allure 结果目录里写。
# 后果是：报告里的用例数翻倍，而且两个线程抢同一个目录，结果不可预期。
# 所以在"起线程之前"先在这里登记一下，登记不上就直接拒绝。
#
# 【为什么放内存里，不放数据库字段？】
# 因为这个信息只对【当前这个进程】有意义。
# 线程是跟着进程走的：服务一重启，线程就全没了 ——
# 这时候数据库里如果还留着"某某正在执行中"，反而是错的（它根本没在跑）。
# 放内存里，重启即归零，天然和真实状态一致。
_running: set = set()
_running_lock = threading.Lock()


def _run_allure(*args: str, cwd: Path = None) -> subprocess.CompletedProcess:
    """调用 allure 命令行（自动处理 Windows 的 .bat 问题）。"""
    cmd = " ".join(f'"{a}"' for a in (ALLURE, *args))
    return subprocess.run(
        cmd, shell=True, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def server_is_alive() -> bool:
    """被测服务（Django 自己）活着吗？

    【为什么要在跑测试之前先单独检查这一步？】
    如果没有这一步，服务没起来的时候会怎样：
        44 条用例全部报 ConnectionError，跑满一个超时周期，
        最后 summary 写着"44 failed"。看报告的人第一反应是
        「接口全挂了？」—— 其实只是服务没开。故障现象和真实原因对不上。

    先检查一次，就能把"环境没准备好"和"接口真的有问题"这两件事分开，
    直接给出人话结论。这就是所谓的【失败要失败在第一步】。

    判定标准：能收到任何 HTTP 响应（哪怕 404/500）都算活着 ——
    那说明服务进程在跑，只是这个路径/这次返回有问题。
    只有彻底连不上才算没起来。
    """
    try:
        urllib.request.urlopen(f"{BASE_URL}/api/projects/", timeout=3)
        return True
    except urllib.error.HTTPError:
        return True          # 有响应 = 服务活着
    except Exception:
        return False         # 连不上 = 服务没起来


def extract_summary(output: str) -> str:
    """从 pytest 的输出里，把最后那行统计抠出来。

    我们要的是这种行：
        ======================= 44 passed in 0.74s =======================
        ============ 2 failed, 42 passed, 1 warning in 1.03s =============

    【为什么用正则去捞，而不是直接取最后一行？】
    pytest 退出前可能还会打印别的东西（warning 汇总、插件提示、
    或者 --alluredir 插件自己的一行），最后一行未必是统计行。
    直接取最后一行，偶尔就会把 "See the full warning summary above"
    当成执行结果存进数据库。

    正则找的是"含数字 + passed/failed/error"的那一行，稳得多。
    找不到就返回"未捕获到执行结果"—— 不猜、不编。
    """
    pattern = re.compile(r"\d+ (?:passed|failed|error|skipped)", re.IGNORECASE)
    # reversed：从后往前找，取【最后一条】统计行
    # （多条时最后那条才是汇总，前面的是中间过程）
    for line in reversed(output.splitlines()):
        if pattern.search(line):
            # 去掉 pytest 用来装饰的那圈 = 号和空格
            return line.strip().strip("=").strip()
    return "未捕获到执行结果"


def _summary_from_nunit(xml_path: Path) -> str:
    """从 NUnit XML 根节点的属性拼一句摘要。

    【为什么不复用 extract_summary？】
    那个正则认得是 pytest 的统计行。更关键的是：**Unity 的输出根本不能用**。
    实测团结引擎 Console.WriteLine 打出来的中文在 Windows 上就已经损坏了
    （测试结果 XML 的 <output> 里是烧进去的 U+FFFD 替换字符）。
    所以对游戏套件来说，NUnit XML 是唯一可靠的信息通道，stdout 一律不看。

    好在 XML 的根节点自己就带完整统计，直接读属性，不用猜。
    """
    try:
        root = ET.parse(xml_path).getroot()
    except Exception as exc:
        logger.warning("解析 NUnit XML 失败 %s: %s", xml_path, exc)
        return "已产出结果文件但解析失败"

    total = root.get("total") or "?"
    passed = root.get("passed") or "?"
    failed = root.get("failed") or "?"
    skipped = root.get("skipped") or "0"

    text = f"{passed} passed, {failed} failed"
    if skipped not in ("0", "?"):
        text += f", {skipped} skipped"
    return f"{text}, {total} total"


def _generate_report(suite: TestSuite, results_dir: Path, cwd: Path) -> None:
    """从 allure 结果目录生成 HTML 报告，并把状态写成"执行完毕"。

    这一段【完全不依赖套件类型】：
    report_dir 只由 MEDIA_ROOT_ABS 和 suite.id 决定，
    所以两种套件天然各占一个目录（suites/1/report、suites/2/report），不会撞。
    """
    # 报告输出到 MEDIA_ROOT 下。
    # 因为 settings 里 DEBUG=True + MEDIA_URL='uploads/' 且 urls.py 挂了 static()，
    # uploads/ 整个目录都被映射成了可访问的 URL ——
    # 生成到这里，Admin 里点个链接就能看，不用再写任何静态文件服务代码。
    report_dir = MEDIA_ROOT_ABS / "suites" / str(suite.id) / "report"
    report_dir.mkdir(parents=True, exist_ok=True)

    gen = _run_allure(
        "generate", str(results_dir), "-o", str(report_dir), "--clean",
        cwd=cwd,
    )
    suite.has_report = (gen.returncode == 0)
    if not suite.has_report:
        # 报告没生成出来，但用例结果是真的，别把整条记录判成"出错"
        logger.warning("allure generate 失败: %s %s", gen.stdout, gen.stderr)

    # 存相对路径：换机器、换 MEDIA_ROOT 都不用改数据库里的历史记录
    suite.report_path = f"suites/{suite.id}/report"

    suite.status = 3          # 执行完毕
    suite.save()


def _run_api_suite(suite: TestSuite) -> None:
    """跑接口自动化套件：子进程 pytest → allure 结果 → 报告。"""
    # ---- 第 0 步：环境检查 ----
    if not API_TEST_DIR.exists():
        raise RuntimeError(f"用例目录不存在：{API_TEST_DIR}")

    if not server_is_alive():
        # 这不是"出错"，是"环境没准备好"—— 明确区分开，报告里看得懂
        suite.status = -2
        suite.summary = f"被测服务未启动（{BASE_URL} 连不上）"
        suite.save(update_fields=["status", "summary", "updated_at"])
        return

    # ---- 第 1 步：子进程跑 pytest ----
    # sys.executable = 当前跑 Django 的那个 Python。
    # 用它而不是写死 "python"，是为了保证子进程和 Django 用的是同一个环境，
    # 不然很容易出现"Django 里装了 pyyaml、子进程里没有"这种诡异问题。
    #
    # 【超时要在这里自己接住，不能丢给外层】
    # 外层那个 except 分不清是哪个套件超的，消息里的秒数就会张冠李戴
    # （游戏套件超时 900 秒，却报"超过 300 秒"）。
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest"],
            cwd=API_TEST_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",     # 输出里混进非 UTF-8 字节时用替换字符顶上，别让解码直接抛异常
            timeout=PYTEST_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        suite.status = -2
        suite.summary = f"执行超时（超过 {PYTEST_TIMEOUT} 秒）"
        suite.save(update_fields=["status", "summary", "updated_at"])
        return

    output = proc.stdout + "\n" + proc.stderr

    suite.is_pass = (proc.returncode == 0)
    suite.summary = extract_summary(output)
    suite.status = 2          # 生成报告中
    suite.save(update_fields=["is_pass", "summary", "status", "updated_at"])

    # ---- 第 2 步：生成 Allure 报告 ----
    _generate_report(suite, ALLURE_RESULTS, API_TEST_DIR)


def _run_game_suite(suite: TestSuite) -> None:
    """跑游戏自动化套件：团结引擎批处理 → NUnit XML → 转 allure → 报告。

    链路比 api_test 多一跳：引擎吐的是 NUnit XML，要先用游戏项目里的
    nunit-to-allure.py 转成标准 allure 结果目录，后面才能走同一套生成报告的代码。
    """
    # ---- 第 0 步：环境检查（对应 api_test 的 server_is_alive）----
    if not GAME_PROJECT_DIR.exists():
        raise RuntimeError(f"游戏项目目录不存在：{GAME_PROJECT_DIR}")
    if not GAME_RUN_SCRIPT.exists():
        raise RuntimeError(f"测试脚本不存在：{GAME_RUN_SCRIPT}")

    # 【每轮用唯一的结果名，不能固定叫 game】
    # run-tests.sh 开头会 rm -f 掉同名产物避免旧结果被误用。
    # 如果两次执行共用固定名，第二次会把第一次正在写的 XML 删掉，
    # 或者读到半截文件 —— 报告里出现的是另一次运行的结果。
    # 唯一命名从根上消除互相覆盖；反过来，"跑完发现 XML 不存在"
    # 就干净地等价于"这轮根本没产出结果"。
    result_name = f"platform-{suite.id}-{int(time.time())}"
    xml_path = GAME_PROJECT_DIR / "TestResults" / f"{result_name}.xml"
    log_path = GAME_PROJECT_DIR / "TestResults" / f"{result_name}.log"

    # ---- 第 1 步：子进程跑团结引擎 ----
    # 【必须用 list 形式传参，不能学 _run_allure 那样 shell=True 手工拼引号】
    # 那条路能用只是因为 D:\cekai\django 这个路径里没有空格。
    # 游戏项目是 "D:\RPG GAME\RPG GAME"，有空格，手工拼接必炸。
    try:
        proc = subprocess.run(
            [GAME_BASH, str(GAME_RUN_SCRIPT), "EditMode", result_name],
            cwd=str(GAME_PROJECT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GAME_RUN_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        suite.status = -2
        suite.summary = f"执行超时（超过 {GAME_RUN_TIMEOUT} 秒）"
        suite.save(update_fields=["status", "summary", "updated_at"])
        return

    # ---- 第 2 步：结果文件必须存在 ----
    # run-tests.sh 的退出码：0=全过 2=有用例失败 3=测试运行本身出错。
    # 只有 3 那种情况（编译失败、引擎起不来）才不会有结果文件。
    if not xml_path.exists():
        suite.status = -2
        suite.summary = (
            f"未产出测试结果（引擎退出码 {proc.returncode}），日志见 {log_path.name}"
        )[:255]
        suite.save(update_fields=["status", "summary", "updated_at"])
        return

    suite.is_pass = (proc.returncode == 0)
    suite.summary = _summary_from_nunit(xml_path)
    suite.status = 2          # 生成报告中
    suite.save(update_fields=["is_pass", "summary", "status", "updated_at"])

    # ---- 第 3 步：NUnit XML → 标准 allure 结果目录 ----
    # 用 sys.executable（当前跑 Django 的那个 Python），
    # 这样转换器肯定能 import 到 allure_commons —— 它就在平台的 venv 里。
    conv = subprocess.run(
        [sys.executable, str(GAME_CONVERTER), str(xml_path), str(GAME_ALLURE_RESULTS)],
        cwd=str(GAME_PROJECT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if conv.returncode != 0:
        # 和 _run_allure 失败同样的处理：只记日志，不改状态。
        # 用例结果是真的（上面已经写库了），报告出不来是另一回事。
        logger.warning("nunit-to-allure 转换失败: %s %s", conv.stdout, conv.stderr)

    # ---- 第 4 步：生成 Allure 报告 ----
    _generate_report(suite, GAME_ALLURE_RESULTS, GAME_PROJECT_DIR)


def _mark_running(suite: TestSuite) -> None:
    """把套件标记成"执行用例中"，并清掉上一轮的报告痕迹，立刻写库。

    【本轮开跑之前，为什么必须清掉报告痕迹？】
    这是反向验证时发现的坑：服务没起来 → 状态写成"出错"，
    但 has_report / report_path 还留着上一轮成功时的值，
    页面上就会出现「❌ 执行出错」旁边挂着一个能点开的"查看报告"——
    点进去是【上一轮的旧报告】，而且它还是全绿的。

    报告这东西最怕的就是"看了个假结果"：报告链接必须永远对应
    最近一次执行。宁可这里没有链接，也不要给一个会骗人的链接。

    【为什么单独抽成一个函数？】
    异步执行时，这一步要在【请求线程】里、起后台线程之前先做完 ——
    这样页面刷新一下就能立刻看到"执行用例中"，
    而不是等后台线程被调度起来之后状态才变。
    """
    suite.status = 1          # 执行用例中
    suite.summary = ""
    suite.has_report = False
    suite.report_path = ""
    suite.save(update_fields=["status", "summary", "has_report", "report_path", "updated_at"])


def run_suite(suite: TestSuite) -> TestSuite:
    """执行一个测试套件，把结果写回数据库。返回更新后的 suite。

    【整段用 try/except 包住，这是刻意的】
    这个方法会被 Admin 的 action 调用，运行在 Web 请求里。
    任何一处没接住的异常（文件不存在、allure 没装、子进程超时）
    都会变成用户页面上一个 500 —— 而且数据库里那条记录会永远卡在
    "执行中"，看起来像死了一样。

    所以：不管哪一步炸了，都要保证状态被写成"出错" + 一句人话原因。

    【异步执行时，这个函数跑在后台线程里】
    所以这层 try/except 的意义更大了：线程里抛异常是【静默失败】，
    没有 Django 帮你兜底成 500 页面，只能靠自己写进数据库。
    """
    _mark_running(suite)

    try:
        # 按套件类型分派。
        # 【为什么不写成 if game_test else api_test】
        # 这样将来加第三种套件时，忘了写分支会静静地按 pytest 跑一遍，
        # 而不是报错。显式列全 + 兜底抛异常，改漏了会立刻暴露。
        if suite.suite_type == "api_test":
            _run_api_suite(suite)
        elif suite.suite_type == "game_test":
            _run_game_suite(suite)
        else:
            raise RuntimeError(f"未知的套件类型：{suite.suite_type}")

    except Exception as exc:
        # 【这里 catch Exception 是故意的，而且要把原因写进 summary】
        # 现场最常见的是：allure 没装、目录被删了、磁盘满。
        # 如果只 log 不写库，用户看到的就是一个永远"执行中"的死记录。
        #
        # 注意：子进程超时【不在这里】处理 —— 两个套件的超时值不一样，
        # 各自的 _run_xxx_suite 内部会接住并写出正确的秒数。
        logger.exception("执行套件 %s 失败", suite.id)
        suite.status = -2
        suite.summary = f"执行出错：{type(exc).__name__}: {exc}"[:255]
        suite.save(update_fields=["status", "summary", "updated_at"])

    return suite


# ==========================================================================
# 异步执行：把慢活丢到后台线程，请求线程立刻返回
# ==========================================================================
#
# 【问题是什么？】
# run_suite 会【同步】等 pytest 跑完 —— 接口套件十几秒，游戏套件最长 900 秒。
# 如果直接在 Admin 的 action 里调它，这段时间会一直占着 Web 请求线程：
#
#     浏览器转圈等 → 等太久还会超时断开（900 秒那个必然超时）
#     但后台其实还在跑，用户已经看不到结果了
#
# 【怎么改？两段式】
#
#     请求线程（快）：登记 → 标记"执行中" → 起后台线程 → 【立刻返回】
#     后台线程（慢）：跑 pytest → 生成报告 → 写最终状态
#
# 【为什么用线程，而不是 Celery？】
# 生产环境的正解是 Celery + Redis：任务不丢、能分布式、能重试、能定时。
# 但代价是要额外装 Redis、起 worker 进程、配 broker ——
# 对这个单机演示项目是过度设计。
#
# 所以这里用线程做最小实现，并且把入口收敛成【一个函数】 start_suite_async。
# 将来真要换 Celery，只改这一个函数，调用方（admin.py）一行都不用动。
# —— 面试可以讲这个取舍：知道工业标准是什么，也知道什么时候不该上。


def is_running(suite_id: int) -> bool:
    """这个套件是不是正在后台跑？"""
    with _running_lock:
        return suite_id in _running


def start_suite_async(suite: TestSuite) -> bool:
    """把套件丢到后台线程执行，请求线程立刻返回。

    返回 True  = 成功启动
    返回 False = 已经在跑了，这次跳过（防止连点起两个线程抢同一份结果）

    【注意调用顺序】登记 → 标记 → 起线程，三步都不能换位置：
      - 先登记：两个请求同时进来时，只有一个能登记上，另一个当场被拒
      - 再标记：在请求线程里把状态写成"执行中"，页面刷新就能立刻看到
      - 最后起线程：此时数据库里的状态已经是"执行中"了，不存在空窗期
    """
    with _running_lock:
        if suite.id in _running:
            return False
        _running.add(suite.id)

    _mark_running(suite)

    threading.Thread(
        target=_run_in_background,
        args=(suite.id,),
        name=f"suite-{suite.id}",
        # daemon=True：主进程退出时这个线程跟着一起结束，不会把服务吊住。
        daemon=True,
    ).start()
    return True


def _run_in_background(suite_id: int) -> None:
    """后台线程的入口：按 id 重新取出套件，跑完，然后收拾干净。

    【为什么传 id，不直接传 suite 对象过来？】
    那个对象是在【请求线程】里从数据库读出来的（它的连接绑在请求线程上）。
    跨线程传一个 ORM 实例容易踩到"这个连接不属于当前线程"的坑。
    按 id 重新查一次最稳，代价只是一条 SELECT。
    """
    try:
        suite = TestSuite.objects.get(id=suite_id)
        run_suite(suite)

    except Exception:
        # 【线程里抛异常，没有人兜底】
        # 在 Web 请求里出错，Django 会返回一个 500 页面；
        # 但在后台线程里出错，就是【静默失败】——
        # 状态会永远停在"执行用例中"，页面上看起来像死了一样。
        # 所以这里必须自己接住，并且写进数据库。
        logger.exception("后台执行套件 %s 失败", suite_id)
        try:
            TestSuite.objects.filter(id=suite_id).update(
                status=-2, summary="后台执行失败（详见服务端日志）"
            )
        except Exception:
            logger.exception("写回失败状态时又出错了，套件 %s", suite_id)

    finally:
        # 不管成功还是失败，这两件事都必须做：

        # ① 从"正在跑"名单里移除。
        #    不移除的话，这个套件就【再也启动不了了】—— 永远显示"已在执行中"。
        with _running_lock:
            _running.discard(suite_id)

        # ② 关掉这个线程的数据库连接。
        #    Django 的数据库连接是【按线程分配】的：每个线程有自己的连接。
        #    子线程跑完不关，这条连接就一直挂着 ——
        #    跑的次数多了会把连接数耗光，后面的请求连不上数据库。
        connection.close()
