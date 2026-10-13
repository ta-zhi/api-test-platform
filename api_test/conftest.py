"""pytest 公共 fixture 装配。

把「怎么造出一个可用的请求客户端」这件事收敛到这里，
用例里只写 `def test_xxx(posts_api)` 就能拿到可用的接口对象。
"""

import pytest

from apis.posts_api import PostsApi
from apis.projects_api import ProjectsApi
from common.client import HttpClient
from config.settings import DEFAULT_ENV, get_config


def pytest_addoption(parser):
    # 默认值从 config 里取，不要在这里再写一遍。
    # （这里原本硬编码 default="test"，导致改了 config 里的 DEFAULT_ENV
    #   却完全不生效 —— 一个概念两处定义，改一处漏一处。）
    parser.addoption("--env", action="store", default=DEFAULT_ENV,
                     help="运行环境: dev / test")


@pytest.fixture(scope="session")
def env(request) -> str:
    return request.config.getoption("--env")


@pytest.fixture(scope="session")
def client(env):
    # session 级别：整轮用例共用一条连接，跑得更快
    cfg = get_config(env)
    http = HttpClient(base_url=cfg["base_url"], timeout=cfg["timeout"])
    yield http
    http.close()


@pytest.fixture(scope="session")
def posts_api(client) -> PostsApi:
    return PostsApi(client)


@pytest.fixture(scope="session")
def projects_api(client) -> ProjectsApi:
    return ProjectsApi(client)


@pytest.fixture
def created_project(projects_api):
    """造一条「真实存在」的项目数据，用完自动删掉。

    和 jsonplaceholder 最大的区别就在这里：
      假接口   —— 你 POST 什么都行，它不存，跑一万次数据库也不变
      真接口   —— 你 POST 一条，数据库里就真的多一条，不会自己消失

    所以用例必须自己收拾干净，否则：
      第 1 次跑：库里 1 条数据，一切正常
      第 10 次跑：库里 10 条垃圾数据，列表接口的断言就没法写了

    这个 fixture 的写法是 setup + teardown 二合一：
      yield 之前  →  前置准备（造数据）
      yield 之后  →  后置清理（删数据），用例不管成功失败都会执行
    """
    # ---- 前置：造数据 ----
    response = projects_api.create_project(
        name="用例前置数据-自动创建",
        description="这个用例跑完会被自动删除",
    )
    assert response.status_code == 201, f"前置数据创建失败：{response.text}"
    project = response.json()

    yield project  # ← 把数据交给用例使用

    # ---- 后置：清理 ----
    projects_api.delete_project(project["id"])


@pytest.fixture
def cleanup(projects_api):
    """数据清理登记处。

    created_project 适合「固定造一条数据」的场景，
    但数据驱动用例一次要跑好几组数据，每组的 id 都是运行时才知道的，
    没法提前写死。

    所以换一种思路：给用例一个「登记处」，
    用例每造出一条数据就登记一下，跑完由这里统一删除。

    好处是：即使用例中途失败，只要登记过了，就会被删掉。
    （这比在用例最后一行手写 delete 可靠得多 ——
      这一点 Day3 已经用真实案例验证过了）
    """
    pending_ids = []

    def register(project_id: int):
        """把需要清理的数据 id 登记进来"""
        pending_ids.append(project_id)

    yield register  # ← 用例拿到的是 register 这个函数本身

    # 不管用例成功还是失败，登记过的全部删掉
    for project_id in pending_ids:
        projects_api.delete_project(project_id)
