"""用例层：测试项目（Project）接口。

被测对象：http://127.0.0.1:8000/api/projects/  （就是你自己 Django 平台里的接口）
运行方式：pytest --env dev

和 test_posts.py 的区别只有两点：
  1. 被测对象换成了自己的平台（靠 --env dev 切换）
  2. 数据是「真」的 —— 增删改会真的写进 db.sqlite3，所以用例要负责收拾现场
"""

import allure
import pytest


# ============================================================
# 一、查询类
# ============================================================

@allure.feature("项目管理")
@allure.story("查询项目")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("查询全部项目应返回 200 且是列表")
@pytest.mark.smoke
def test_list_projects(projects_api):
    """查询全部项目，应返回 200 且是一个列表"""
    response = projects_api.list_projects()

    assert response.status_code == 200
    assert isinstance(response.json(), list)


@allure.feature("项目管理")
@allure.story("查询项目")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("查询单个项目应返回创建时的数据")
@pytest.mark.smoke
def test_get_project_detail(projects_api, created_project):
    """查询单个项目，返回的字段应该和创建时一致

    注意这里多了一个参数 created_project —— 它来自 conftest.py，
    会自动帮我们先造一条数据，再用这条数据去查。
    这样用例就不用「假设数据库里已经有 id=1 的数据」了，
    用例之间也就互不依赖了。
    """
    response = projects_api.get_project(created_project["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created_project["id"]
    assert body["name"] == created_project["name"]
    assert body["created_at"]  # 服务端应该补上创建时间


@allure.feature("项目管理")
@allure.story("性能底线")
@allure.severity(allure.severity_level.MINOR)
@allure.title("列表接口响应时间应小于 1 秒")
@pytest.mark.regression
def test_list_projects_response_time(projects_api):
    """性能底线：列表接口响应时间应小于 1 秒

    归到 regression 而不是 smoke：
    性能用例受机器负载影响，偶尔会抖，不适合卡在每次提交的快速通道上。
    """
    response = projects_api.list_projects()

    assert response.status_code == 200
    assert response.elapsed.total_seconds() < 1


# ============================================================
# 二、新增类
# ============================================================

@allure.feature("项目管理")
@allure.story("新增项目")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("新增项目应返回 201 并回显数据")
@pytest.mark.smoke
def test_create_project(projects_api):
    """新增：POST 应返回 201，并回显数据、由服务端生成 id"""
    response = projects_api.create_project(
        name="面试演示项目",
        description="由 pytest 自动创建",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "面试演示项目"
    assert body["description"] == "由 pytest 自动创建"
    assert body["id"] > 0  # id 是服务端生成的，不是我们传的

    # 收尾：把自己造出来的数据删掉，不给下一次运行留垃圾
    projects_api.delete_project(body["id"])


@allure.feature("项目管理")
@allure.story("新增项目")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("name 为空应返回 400 而不是 500")
@pytest.mark.regression
def test_create_project_without_name(projects_api):
    """异常：name 为空，应该返回 400 而不是 500

    这是最容易被忽略、面试官却最爱问的一类用例。
    参数校验没写好的话，服务端会直接抛异常返回 500，
    用户看到的就是「服务器内部错误」，完全不知道是自己没填名字。
    """
    response = projects_api.create_project(name="")

    assert response.status_code == 400
    assert "error" in response.json()


# ============================================================
# 三、更新类
# ============================================================

@allure.feature("项目管理")
@allure.story("更新项目")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("更新项目后重新查询应拿到新值")
@pytest.mark.smoke
def test_update_project(projects_api, created_project):
    """更新：PUT 之后再查一次，拿到的是新值

    「再查一次」这步是关键。
    只断言 PUT 的返回值是不够的 —— 有的接口 PUT 会回显你传的值，
    但根本没往数据库里写。必须重新 GET 一次才能证明「真的存进去了」。
    这个坑在假接口（jsonplaceholder）上永远测不出来，因为它不存数据。
    """
    project_id = created_project["id"]

    response = projects_api.update_project(
        project_id, name="改名后的项目", description="改后的描述"
    )
    assert response.status_code == 200

    # 重新查一次，验证数据真的落库了
    again = projects_api.get_project(project_id)
    assert again.status_code == 200
    assert again.json()["name"] == "改名后的项目"
    assert again.json()["description"] == "改后的描述"


@allure.feature("项目管理")
@allure.story("更新项目")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("更新时 name 为空应返回 400 且不改坏原数据")
@pytest.mark.regression
def test_update_project_without_name(projects_api, created_project):
    """异常：更新时 name 传空，应该返回 400，且原数据不能被改坏"""
    project_id = created_project["id"]

    response = projects_api.update_project(project_id, name="")
    assert response.status_code == 400

    # 校验失败之后，原来的数据必须还在（不能被"改了一半"）
    still_there = projects_api.get_project(project_id)
    assert still_there.status_code == 200
    assert still_there.json()["name"] == created_project["name"]


# ============================================================
# 四、删除类
# ============================================================

@allure.feature("项目管理")
@allure.story("删除项目")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("删除项目后应查不到该资源")
@pytest.mark.smoke
def test_delete_project(projects_api):
    """删除：删掉之后再也查不到 —— 这才叫真的删除"""
    created = projects_api.create_project(name="待删除项目").json()
    project_id = created["id"]

    assert projects_api.delete_project(project_id).status_code == 200

    # 关键断言：删除之后必须变成 404。
    # 只测 DELETE 返回 200 是不够的，很多 bug 是"返回成功但没删掉"。
    assert projects_api.get_project(project_id).status_code == 404


# ============================================================
# 五、端到端：完整生命周期
# ============================================================

@allure.feature("项目管理")
@allure.story("端到端全链路")
@allure.severity(allure.severity_level.BLOCKER)
@allure.title("项目完整生命周期：新增 → 查询 → 更新 → 删除")
@pytest.mark.smoke
def test_project_lifecycle(projects_api):
    """把增 → 查 → 改 → 删串成一条完整链路走一遍

    这类用例面试时最好讲：它模拟的是一次真实的用户操作流程，
    任何一环出问题都会失败，是「冒烟测试」里最有价值的一条。
    """
    # 用 allure.step 把用例切成 4 段，报告里就是一个步骤列表。
    #
    # 【为什么值得这么写？】
    # 不加 step 时，用例失败只告诉你"这条挂了"；
    # 加了 step，报告里会明确显示是【第 3 步 更新项目】红的 ——
    # 你连日志都不用翻就知道问题出在哪个环节。
    #
    # 步骤名用中文写，报告是给团队所有人看的，不是只给自己看。

    with allure.step("1. 新增一个项目"):
        created = projects_api.create_project(
            name="生命周期-新增", description="v1"
        ).json()
        project_id = created["id"]
        assert created["description"] == "v1"

    with allure.step("2. 查询这个项目，名字应该是刚创建的"):
        assert projects_api.get_project(project_id).json()["name"] == "生命周期-新增"

    with allure.step("3. 更新项目，再查一次确认落库"):
        projects_api.update_project(project_id, name="生命周期-更新", description="v2")
        assert projects_api.get_project(project_id).json()["description"] == "v2"

    with allure.step("4. 删除项目，删除后应查不到"):
        projects_api.delete_project(project_id)
        assert projects_api.get_project(project_id).status_code == 404
