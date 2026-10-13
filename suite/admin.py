from django.conf import settings
from django.contrib import admin, messages
from django.utils import html
from .models import Project, TestSuite, TestTask
from . import runner


def media_url(*parts: str) -> str:
    """把 MEDIA_URL 和若干路径段拼成一个【一定能点开】的 URL。

    【为什么要单独写这个函数？】
    项目里 MEDIA_URL = 'uploads/'（没有开头的斜杠）。
    在 Admin 页面上，这种相对路径会被浏览器理解成"相对当前页面"：

        当前页面  /admin/suite/testsuite/
        拼出来的  uploads/suites/1/report/index.html
        浏览器实际请求  /admin/suite/uploads/suites/1/report/index.html

    这个地址没有任何路由匹配，最后落到 Django Admin 的兜底视图
    catch_all_view 上（已登录时会把你甩回 Admin 首页）—— 总之报告是打不开的。

    （这个坑是实测出来的，不是推测：django.urls.resolve 显示
      /uploads/... 匹配到 views.static.serve，
      /admin/suite/uploads/... 匹配到 admin.sites.catch_all_view。）

    加一个开头的斜杠就变成绝对路径 /uploads/...，这才是 settings 里
    urls.py 挂载 static() 的那个位置。

    这个函数存在的意义就是：链接拼接只写一次，
    将来 MEDIA_URL 怎么改都只影响这一个地方，不会漏改某一处拼错的。
    """
    base = "/" + settings.MEDIA_URL.strip("/")
    return "/".join([base, *(p.strip("/") for p in parts)])


@admin.register(TestTask)
class TestRankAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "is_pass", "has_report", "report_url", "created_at", "update_at")

    def report_url(self, obj: TestTask):
        if obj.status == 3 and obj.has_report and obj.case:
            # str(obj.case) 是相对路径，如 tests/<id>/test_demo.py
            case_dir = str(obj.case).rsplit("/", 1)[0]
            url = media_url(case_dir, "report", "index.html")
            return html.format_html('<a href="{}" target="_blank">点击查看</a>', url)
        return "-"

    report_url.short_description = "测试报告"


@admin.register(TestSuite)
class TestSuiteAdmin(admin.ModelAdmin):
    """内置测试套件的管理页。

    用法：进这个页面 → 勾选一条 → 右上角"操作"下拉里选【立即执行】→ 点"执行"。
    """

    list_display = (
        "name", "status_text", "result_text", "has_report",
        "report_url", "updated_at",
    )
    list_filter = ("suite_type", "status", "is_pass")
    # 执行结果是跑出来的，不该让人手填 —— 手填出来的绿色没有任何意义
    readonly_fields = ("status", "is_pass", "has_report", "report_path", "summary",
                       "created_at", "updated_at")
    actions = ("run_selected",)

    def status_text(self, obj: TestSuite) -> str:
        return obj.status_text()

    status_text.short_description = "状态"

    def report_url(self, obj: TestSuite):
        if obj.has_report and obj.report_path:
            url = media_url(obj.report_path, "index.html")
            return html.format_html('<a href="{}" target="_blank">查看报告</a>', url)
        return "-"

    report_url.short_description = "测试报告"

    @admin.action(description="立即执行选中的套件")
    def run_selected(self, request, queryset):
        """把选中的套件丢到后台执行，【立刻返回】，不等它们跑完。

        【为什么改成异步？】
        原来是同步的：点下去之后页面会卡住十几秒（跑 44 条用例 + 生成报告），
        期间这个 Web 请求线程一直被占着。游戏套件更夸张 ——
        超时上限是 900 秒，浏览器根本等不到，必然断开，
        但后台其实还在跑，用户已经看不到结果了。

        现在改成：请求线程只做"登记 + 标记执行中 + 起后台线程"这三件快事，
        几毫秒就返回。页面立刻刷新成"执行用例中"，
        真正的执行进度由页面【自动轮询刷新】来看。

        【所以这里不再有"执行完毕，44 passed"这种提示了】
        因为返回的时候测试还没跑完，我们根本不知道结果 ——
        这个提示现在必须由页面刷新后的状态列来承担。
        提示语只能说"已经开始执行"，这就是异步的代价：
        从"一问一答"变成了"先受理，再查询"。
        """
        started = []
        skipped = []
        for suite in queryset:
            if runner.start_suite_async(suite):
                started.append(suite.name)
            else:
                skipped.append(suite.name)

        if started:
            self.message_user(
                request,
                f"已开始执行：{'、'.join(started)}。"
                f"页面会自动刷新，跑完就能看到结果和报告链接。",
                messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"以下套件正在执行中，本次已跳过：{'、'.join(skipped)}",
                messages.WARNING,
            )


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "description", "created_at")
    search_fields = ("name",)
