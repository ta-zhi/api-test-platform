import uuid
import os.path
from pathlib import Path
from django.db import models
import pytest

# Create your models here.

#动态生成保存路径
def get_case_path(instance, filename):
    #上传的用例文件保存在 tests/id/file
    return os.path.join('tests', str(instance.id), filename)

def main_with(test_dir):
    #在指定目录运行 pytest，返回退出码（0=全部通过，非0=有失败/错误）
    #--alluredir 让 pytest 生成 allure 结果数据，供后续生成报告
    allure_results = test_dir / "allure_results"
    return pytest.main([str(test_dir), f"--alluredir={allure_results}"])

class TestTask(models.Model):
    #测试任务 将用例文件上传至指定的目录，并在该目录执行用例

    id = models.UUIDField(primary_key=True, default=uuid.uuid4,editable=False)
    name = models.CharField('任务名称', max_length=100)
    case = models.FileField('用例文件', upload_to=get_case_path)


    status = models.IntegerField('测试状态', default=-1, choices=[
        (-2, "出现错误"),
        (-1, "初始化"),
        (0, "等待执行"),
        (1, "执行用例"),
        (2, "生成报告"),
        (3, "执行完毕"),
    ])

    is_processing = models.BooleanField("正在执行", default=False, editable=False)
    is_pass = models.BooleanField("是否通过", default=False, editable=False)
    has_report = models.BooleanField("拥有报告", default=False, editable=False)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    update_at = models.DateTimeField('最后更新', auto_now=True)

    class Meta:
        verbose_name_plural = verbose_name = '测试任务'


    def __str__(self):
        return self.name


    def save(self, *args, **kwargs):
        #在model保存的时候自动调用

        super().save(*args, **kwargs)

        #用例执行逻辑
        if self.status == 0 and self.is_processing is False: #可以执行用例
            self.status = 1
            self.is_processing = True
            self.save() #更新执行状态

            test_dir = Path(str(self.case.path)).parent #用例所在的目录

            ret = main_with(test_dir) #调用 pytest

            if ret == pytest.ExitCode.OK:
                self.is_pass = True
            else:
                self.is_pass = False

            self.status = 2
            self.is_processing = True
            self.save()  # 更新执行状态

            report_dir = test_dir / "report"
            allure_results = test_dir / "allure_results"
            ret = os.system(f'allure generate -c -o "{report_dir}" "{allure_results}"')

            if ret == 0:
                self.has_report = True
            else:
                self.has_report = False

            self.status = 3
            self.is_processing = False
            self.save()  # 更新执行状态


class TestSuite(models.Model):
    """内置测试套件：平台可以直接执行的一整套用例。

    【和 TestTask 的区别】
        TestTask    —— 用户【上传】一堆用例文件，平台在它所在目录里跑。
                       适合"随便传点东西跑跑看"。
        TestSuite   —— 平台【自己知道】的成套用例，比如仓库里的 api_test。
                       不需要上传，选中点一下就能跑。

    这两者回答的是不同的问题：
        TestTask  = "我传的这份用例能过吗？"
        TestSuite = "我们项目的接口自动化，现在还是全绿吗？"

    后者才是日常真正要反复跑的东西，也是 CI 会调用的东西。

    【为什么用 choices 而不是写死成只有 api_test】
    suite_type 留了扩展位：将来要接 UI 自动化、性能测试，
    只需要在 choices 里加一项、在 runner 里加一个分支，
    模型和 Admin 不用动。

    （这个扩展位 2026-09-22 第一次派上用场：加了 game_test，
      模型只动了两行、Admin 一行没改，报告路径也不用调整。
      验证了当初把 suite_type 做成 choices 而不是写死是对的。）
    """

    SUITE_TYPES = [
        ("api_test", "接口自动化套件"),
        ("game_test", "游戏自动化套件（EditMode）"),
    ]

    STATUS_CHOICES = [
        (-2, "出现错误"),
        (-1, "初始化"),
        (0, "等待执行"),
        (1, "执行用例中"),
        (2, "生成报告中"),
        (3, "执行完毕"),
    ]

    name = models.CharField("套件名称", max_length=100, default="接口自动化套件")
    suite_type = models.CharField(
        "套件类型", max_length=50, choices=SUITE_TYPES, default="api_test"
    )
    status = models.IntegerField("执行状态", default=-1, choices=STATUS_CHOICES)
    is_pass = models.BooleanField("是否通过", default=False)
    has_report = models.BooleanField("拥有报告", default=False)
    report_path = models.CharField(
        "报告路径", max_length=255, blank=True, default="",
        help_text="相对 MEDIA_ROOT 的目录，如 suites/1/report",
    )
    summary = models.CharField(
        "执行结果摘要", max_length=255, blank=True, default="",
        help_text="本轮执行的结果摘要，如 44 passed in 0.83s / 167 passed, 0 failed, 167 total",
    )

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("最后更新", auto_now=True)

    class Meta:
        verbose_name_plural = verbose_name = "测试套件"

    def __str__(self):
        return self.name

    # ---- 下面两个是给 Admin 显示用的，把数字变成人话 ----

    def status_text(self) -> str:
        """把状态码翻译成人能看懂的文字。"""
        return dict(self.STATUS_CHOICES).get(self.status, f"未知({self.status})")

    def result_text(self) -> str:
        """一句话结论，没跑过就显示「未执行」。"""
        if self.status == -1:
            return "未执行"
        if self.status == -2:
            return self.summary or "执行出错"
        if self.status == 3:
            return f"{'✅ 通过' if self.is_pass else '❌ 失败'} — {self.summary}"
        return self.status_text()

    result_text.short_description = "执行结果"


class Project(models.Model):
    """测试项目。

    给接口自动化框架提供一组「真实落库」的增删改查对象。
    和 TestTask 不同，它没有文件字段，纯粹是文本数据，
    适合用来验证接口的返回码、参数校验和用例依赖处理。
    """

    name = models.CharField('项目名称', max_length=50)
    description = models.CharField('项目描述', max_length=200, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name_plural = verbose_name = '测试项目'

    def __str__(self):
        return self.name

    def to_dict(self):
        """转成可以 JSON 序列化的字典，给接口返回用"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }