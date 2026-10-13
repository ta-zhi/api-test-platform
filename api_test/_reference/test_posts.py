"""用例层。

规则：用例里只写「业务断言」，不出现 URL、不出现 requests。
     读一条用例 = 读一条测试用例文档。

覆盖三类场景：
  正常情况 —— 接口按预期返回
  异常情况 —— 查不存在的资源应该 404，而不是 200 或 500
  边界情况 —— 条数限制、响应时间等边界条件
"""

import pytest


# ============================================================
# 一、正常情况
# ============================================================

@pytest.mark.smoke
def test_get_post_detail(posts_api):
    """查询单条 post，应返回 200 且 id 与请求一致"""
    response = posts_api.get_post(1)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    # 关键字段不能为空 —— 接口返回 200 不代表数据是对的，
    # 有可能返回一个内容为空的"空壳数据"
    assert body["title"]
    assert body["body"]


@pytest.mark.smoke
def test_list_posts(posts_api):
    """查询列表，默认返回 100 条"""
    response = posts_api.list_posts()

    assert response.status_code == 200
    assert len(response.json()) == 100


def test_list_posts_with_limit(posts_api):
    """边界：带 _limit=5 时，应该只返回 5 条"""
    response = posts_api.list_posts(_limit=5)

    assert response.status_code == 200
    assert len(response.json()) == 5


def test_list_posts_filter_by_user(posts_api):
    """筛选：按 userId=3 过滤，返回的每一条 userId 都应该是 3"""
    response = posts_api.list_posts(userId=3)

    assert response.status_code == 200
    posts = response.json()
    assert len(posts) > 0
    # 筛选项没生效的话，会混进别人的数据 —— 所以每条都要查
    assert all(p["userId"] == 3 for p in posts)


def test_list_posts_response_time(posts_api):
    """性能底线：列表接口响应时间应小于 2 秒"""
    response = posts_api.list_posts()

    assert response.status_code == 200
    assert response.elapsed.total_seconds() < 2


# ============================================================
# 二、异常情况
# ============================================================

def test_get_nonexistent_post(posts_api):
    """异常：查询不存在的资源，应该返回 404 而不是 200"""
    response = posts_api.get_post(99999)

    assert response.status_code == 404


# ============================================================
# 三、写入类：新增 / 更新 / 删除
# ============================================================

def test_create_post(posts_api):
    """新增：POST 应返回 201（不是 200），并回显提交的数据"""
    payload = {"title": "测试开发", "body": "接口自动化", "userId": 1}

    response = posts_api.create_post(payload)

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == payload["title"]
    assert body["userId"] == payload["userId"]


def test_update_post(posts_api):
    """PUT 全量更新：返回 200，标题和内容都被整体替换"""
    payload = {"id": 1, "title": "新标题", "body": "新内容", "userId": 1}

    response = posts_api.update_post(1, payload)

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "新标题"
    assert body["body"] == "新内容"


def test_patch_post(posts_api):
    """PATCH 部分更新：只改 title，其他字段不受影响"""
    response = posts_api.patch_post(1, {"title": "只改标题"})

    assert response.status_code == 200
    assert response.json()["title"] == "只改标题"


def test_delete_post(posts_api):
    """删除：DELETE 应返回 200"""
    response = posts_api.delete_post(1)

    assert response.status_code == 200
