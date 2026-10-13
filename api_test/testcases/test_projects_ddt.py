"""数据驱动用例层（DDT = Data-Driven Testing）。

有了这一层之后，你会看到：
  「6 组测试数据」= 「1 条用例代码」+「1 个 YAML 文件」

而不是：
  「6 组测试数据」= 「6 条几乎一模一样的用例代码」

这样做的好处：
  1. 加数据不用写代码 —— 复制粘贴一段 YAML 就行
  2. 数据和技术分开 —— 业务同学也能看 YAML 提用例
  3. 每条数据在报告里是独立的一条用例，谁挂了清清楚楚

运行：pytest --env dev testcases/test_projects_ddt.py
"""

import allure
import pytest

from common import assertions as ast
from common.data_loader import load_yaml


# 模块加载时就把数据读进来（只读一次，6 条数据共用）
CREATE_CASES = load_yaml("projects_create.yaml")


# ---------------------------------------------------------------------------
# parametrize 是什么？
#
#   @pytest.mark.parametrize("参数名", [值1, 值2, 值3])
#
# 意思是：把这条用例跑 3 遍，每一遍分别把 值1 / 值2 / 值3 塞进那个参数。
#
# 对 pytest 来说，这 3 遍是 3 条【独立的用例】：
#   test_create_project_data_driven[正常创建]          PASSED
#   test_create_project_data_driven[名字为空字符串]     PASSED
#   test_create_project_data_driven[名字51个字符（超出边界）]  FAILED
#
# 所以一条挂了不影响其他几条，报告里也能一眼看出是哪组数据有问题。
# ids= 用来指定每一遍在报告里显示的名字，不写的话会显示 [0] [1] [2]，很难看懂。
# ---------------------------------------------------------------------------

@allure.feature("项目管理")
@allure.story("新增项目 - 数据驱动")
@allure.severity(allure.severity_level.NORMAL)
@pytest.mark.regression
@pytest.mark.parametrize(
    "case",
    CREATE_CASES,
    ids=[c["title"] for c in CREATE_CASES],
)
def test_create_project_data_driven(projects_api, cleanup, case):
    """新增项目 —— 数据来自 data/projects_create.yaml"""

    # 【动态标题】为什么这里不用 @allure.title？
    #
    # @allure.title 是【写死在代码里】的，而 parametrize 的 6 组数据
    # 是运行时才一个个喂进来的 —— 静态标题会让 6 条用例在报告里
    # 挤成同一个名字，反而更难分辨。
    #
    # allure.dynamic.title 是【运行时】设置的，所以能按当前这组数据
    # 生成各自的标题，报告里六条一目了然。
    allure.dynamic.title(f"新增项目 - {case['title']}")

    response = projects_api.create_project(
        name=case["name"],
        description=case["description"],
    )

    # 1. 【最重要的一步】先登记清理，再做任何断言
    #
    #    为什么顺序这么关键？
    #    因为只要下面任何一条断言失败，就会抛异常直接结束用例，
    #    后面所有代码都不执行了 —— 那时候再登记就来不及了。
    #
    #    这个坑是真实踩出来的：最初把 cleanup 写在用例最后一行，
    #    结果 51 字符那条用例一挂，数据库里就多出一条垃圾数据。
    #    规则：拿到资源的那一刻就登记，不要等断言完再登记。
    if response.status_code == 201:
        cleanup(response.json()["id"])

    # 2. 状态码对不对
    ast.assert_status(response, case["expect_status"])

    # 3. 创建成功的，还要进一步检查返回的数据结构
    if case["expect_status"] == 201:
        body = response.json()

        # 返回的字段一个都不能少，类型也不能错
        ast.assert_schema(body, {
            "id": int,
            "name": str,
            "description": str,
            "created_at": str,
        })

        # 服务端回显的 name 应该和我提交的一模一样（没被截断、没被改名）
        ast.assert_field(body, "name", case["name"])
