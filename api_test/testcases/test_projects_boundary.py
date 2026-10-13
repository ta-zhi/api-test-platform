"""异常 / 边界用例集。

【为什么单独一个文件？】
正向用例回答的是「功能能不能用」，边界用例回答的是「会不会出事」。

这个文件里所有用例都来自同一个提问方式：

    如果传进去的**不是**它期待的东西，会怎么样？

正常流程永远传字符串、永远传合法 JSON —— 但线上不会。
前端漏了 JSON.stringify、脚本拼错一个字段、别人手动构造请求，
都能造出下面这些输入。

【本文件已经抓出过两类真实缺陷，都是靠用例抓的，不是靠肉眼看的】

  缺陷一：name 传数字 / 布尔 / 列表  →  500
     根因：name = (data.get("name") or "").strip()
           or "" 只兜得住 None / "" / [] 这些【假值】，
           123、True 这种【真值】原样透传，123.strip() 直接炸。

  缺陷二：body 是 null / 123 / "abc" / [1,2]  →  500
     根因：只防了「JSON 语法错误」，没防「语法合法但不是对象」。
           json.loads("123") 毫无毛病地返回 123，
           但下一行 123.get("name") 就崩了。

两处都已在 suite/views.py 修复。这组用例现在的职责是
【防止以后有人改代码时把它们改回去】—— 这就是回归用例的价值。
"""

import allure
import pytest

import common.assertions as ast

# 模块级 marker：一行代码，本文件所有用例全部打上 regression 标记。
# 不用在每个函数头上写一遍 @pytest.mark.regression。
# 跑 `pytest -m regression` 就能只跑这一类。
pytestmark = [
    pytest.mark.regression,                              # 属于回归用例
    allure.feature("项目管理"),                           # 报告里归到"项目管理"这个功能下
    allure.story("参数边界与异常输入"),                     # 子场景
    allure.severity(allure.severity_level.NORMAL),       # 默认严重程度：一般
]


# ---- 边界数据统一放这里，改一处就够 ----
NAME_50 = "a" * 50          # 正好 50，卡在上限上，应该通过
NAME_51 = "a" * 51          # 比上限多 1，应该被拒
DESC_200 = "d" * 200        # 正好 200，应该通过
DESC_201 = "d" * 201        # 比上限多 1，应该被拒
SQL_PAYLOAD = "'; DROP TABLE suite_project; --"

RAW_JSON = {"Content-Type": "application/json"}


# ==================================================================
# 一、name 字段的类型边界
#     "万一传进来的根本不是个字符串呢？"
# ==================================================================
@pytest.mark.parametrize(
    "bad_value",
    [123, True, ["a"], {"k": "v"}, None],
    ids=["数字", "布尔", "列表", "对象", "null"],
)
def test_create_with_non_string_name(projects_api, bad_value):
    """name 传非字符串 —— 曾经全部 500，现在统一 400。

    400 = "你参数不对"（客户端的错）
    500 = "我服务挂了"（服务端的错）
    参数类型不对，服务端不该崩，所以必须是 400。
    """
    response = projects_api.create_project(name=bad_value)
    ast.assert_status(response, 400)


# ==================================================================
# 二、name 的内容边界
#     "字符串里面的内容会不会被处理坏？"
# ==================================================================
@allure.title("创建项目 - 前后空格应被去掉")
def test_create_strips_outer_spaces(projects_api, cleanup):
    """前后空白应该被去掉，不能存成 "    名字    "。"""
    response = projects_api.create_project(name="    前后带空格    ")
    if response.status_code == 201:
        cleanup(response.json()["id"])

    ast.assert_status(response, 201)
    ast.assert_field(response.json(), "name", "前后带空格")


@allure.title("创建项目 - 中间空格应原样保留")
def test_create_keeps_inner_spaces(projects_api, cleanup):
    """和上一条配成一对：该去的去，不该动的别动。

    strip() 只动首尾，中间的空格是用户数据的一部分，必须原样保留。
    只写"去空格"那条用例是不够的 —— 万一有人图省事写成
    " ".join(name.split())，首尾对了、中间也被压扁了，你发现不了。
    """
    response = projects_api.create_project(name="项目  A  B")
    if response.status_code == 201:
        cleanup(response.json()["id"])

    ast.assert_status(response, 201)
    ast.assert_field(response.json(), "name", "项目  A  B")


@allure.title("创建项目 - 中文与 emoji 应原样存取")
def test_create_keeps_unicode(projects_api, cleanup):
    """中文 + emoji + 特殊符号要能原样存、原样取。

    编码问题在 HTTP + 数据库 + 序列化三层都可能出，
    国内项目里这是高频踩坑点，值得固定一条用例守住。
    """
    name = "项目🚀测试-Ω"
    response = projects_api.create_project(name=name)
    if response.status_code == 201:
        cleanup(response.json()["id"])

    ast.assert_status(response, 201)
    ast.assert_field(response.json(), "name", name)


@allure.title("创建项目 - SQL 注入串应被当作普通文本")
def test_create_sql_injection_as_plain_text(projects_api, cleanup):
    """SQL 注入串应该被当成【一段普通文本】存下来，而不是被执行。

    这里要断言两件事：
      1. 它原样存进去了      → 说明没被吞掉、没被转义坏
      2. 接口还能正常查列表  → 说明表还在，没被 DROP 掉

    第 2 条才是重点。只看第 1 条的话，
    "接口把表删了但顺手返回了个 201" 你也发现不了。

    注：Django ORM 底层用的是参数化查询，天然免疫这类拼接注入。
    这条用例守的是"将来有人为了性能改成手写 SQL 拼字符串"。
    """
    response = projects_api.create_project(name=SQL_PAYLOAD)
    if response.status_code == 201:
        cleanup(response.json()["id"])

    ast.assert_status(response, 201)
    ast.assert_field(response.json(), "name", SQL_PAYLOAD)

    # 表还在吗？接口还活着吗？
    ast.assert_status(projects_api.list_projects(), 200)


# ==================================================================
# 三、description 的长度边界
#     和 Day4 那条 name 超长是同一种，但这条链路以前没测过
# ==================================================================
@allure.title("创建项目 - description 正好 200 字符应放行")
def test_create_description_at_limit(projects_api, cleanup):
    """正好 200 字符 —— 边界【上】，应该放行。"""
    response = projects_api.create_project(name="desc边界-200", description=DESC_200)
    if response.status_code == 201:
        cleanup(response.json()["id"])

    ast.assert_status(response, 201)
    ast.assert_field(response.json(), "description", DESC_200)


@allure.title("创建项目 - description 超长应拒绝且不入库")
def test_create_description_over_limit(projects_api):
    """201 字符 —— 边界【外】，应该拒绝，而且不能写进库。

    【这条用例为什么不只断言状态码？】
    只看 400 的话，下面这种情况会漏掉：
        代码先 Project.objects.create(...) 写进了库，
        然后才发现超长，再 return 400。
      → 用户看到的还是 400，但库里已经多了一条脏数据。

    所以再断言一次"列表条数没变"，才能证明它是【真的没写进去】。
    这个写法可以套用到所有"校验失败"的用例上。
    """
    before = len(projects_api.list_projects().json())

    response = projects_api.create_project(name="desc超长-201", description=DESC_201)
    ast.assert_status(response, 400)

    after = len(projects_api.list_projects().json())
    assert before == after, f"校验返回了 400，数据却还是入库了（{before} 条 → {after} 条）"


@allure.title("创建项目 - description 传数字不应 500")
def test_create_with_non_string_description(projects_api, cleanup):
    """description 传数字 —— 不该 500，按空字符串处理即可。"""
    response = projects_api.create_project(name="desc传数字", description=123)
    if response.status_code == 201:
        cleanup(response.json()["id"])

    ast.assert_status(response, 201)
    ast.assert_field(response.json(), "description", "")


# ==================================================================
# 四、请求体本身有问题
# ==================================================================
@pytest.mark.parametrize(
    "raw",
    ["null", "123", '"abc"', "[1,2]", "true"],
    ids=["null", "数字", "字符串", "数组", "布尔"],
)
def test_create_with_valid_json_but_not_object(client, raw):
    """JSON 语法合法，但解出来的不是对象 —— 曾经全部 500。

    这一组和下面 test_create_with_broken_json 是【两类不同的错】：
        这条：      json.loads 解成功了，但结果是 int / list / None
        下一条：    json.loads 直接就抛异常了

    只防住其中一类，另一类照样 500。这是本文件里最值钱的一组用例。
    """
    response = client.post("/api/projects/", data=raw.encode(), headers=RAW_JSON)
    ast.assert_status(response, 400)


@allure.title("创建项目 - JSON 语法错误应返回 400")
def test_create_with_broken_json(client):
    """JSON 语法就是错的 —— 应该 400，不是 500。"""
    response = client.post("/api/projects/", data="{这不是json".encode("utf-8"), headers=RAW_JSON)
    ast.assert_status(response, 400)


@allure.title("创建项目 - 空请求体应返回 400")
def test_create_with_empty_body(client):
    """一个字节都不发 —— 应该 400，不是 500。"""
    response = client.post("/api/projects/")
    ast.assert_status(response, 400)


@allure.title("创建项目 - 多余字段应被忽略且不能指定主键")
def test_create_ignores_extra_fields(projects_api, cleanup):
    """body 里塞多余字段 —— 应该被忽略，尤其不能接受客户端指定的 id。

    这里同时守两件事：
      1. 未知字段不报错        （宽容：接口要能容忍调用方多发字段）
      2. 客户端不能指定 id     （严格：主键由服务端决定）

    第 2 条是安全问题 —— 如果能指定 id，客户端就能覆盖别人的数据。
    """
    response = projects_api.client.post("/api/projects/", json={
        "name": "多余字段-用例",
        "description": "正常描述",
        "id": 999999,
        "is_admin": True,
        "hacker": "我是多余字段",
    })
    if response.status_code == 201:
        cleanup(response.json()["id"])

    ast.assert_status(response, 201)
    body = response.json()
    assert body["id"] != 999999, "接口居然接受了客户端指定的主键 id"
    assert "hacker" not in body, f"接口把多余字段原样返回了：{body}"


# ==================================================================
# 五、路径 / 方法 / id 格式
# ==================================================================
@allure.title("不支持的 PATCH 方法应返回 405")
def test_patch_method_not_allowed(client):
    """不支持的 HTTP 方法应该 405 Method Not Allowed，不是 404 也不是 500。"""
    ast.assert_status(client.patch("/api/projects/"), 405)


@pytest.mark.parametrize("bad_id", ["abc", "-1", "999999"], ids=["非数字", "负数", "不存在"])
def test_get_project_with_bad_id(client, bad_id):
    """id 格式不对 / 不存在，统一 404。

    注意这里期望的是 404 而不是 400 ——
    因为调用方请求的路径形态是合法的（/api/projects/<东西>/），
    只是那个资源不存在。404 比 400 更贴合语义。
    """
    ast.assert_status(client.get(f"/api/projects/{bad_id}/"), 404)


@allure.title("更新项目 - 空请求体应返回 400")
def test_update_with_empty_body(client, created_project):
    """PUT 不带 body —— 相当于把 name 清空，应该 400。"""
    response = client.put(f"/api/projects/{created_project['id']}/")
    ast.assert_status(response, 400)


# ==================================================================
# 六、资源不存在时的写操作
# ==================================================================
@allure.title("更新不存在的项目应返回 404 而非悄悄创建")
def test_update_nonexistent_project(client):
    """更新一个不存在的项目 —— 404，不能悄悄创建一条新的。

    有些框架的 PUT 是 upsert 语义（不存在就创建），
    这条用例就是用来锁死"我们是 404，不搞 upsert"这个契约的。
    """
    response = client.put("/api/projects/999999/", json={"name": "不存在的项目", "description": ""})
    ast.assert_status(response, 404)


@allure.title("删除不存在的项目应返回 404")
def test_delete_nonexistent_project(client):
    ast.assert_status(client.delete("/api/projects/999999/"), 404)


@allure.title("重复删除同一条 - 第一次 200 第二次 404")
def test_delete_twice(projects_api, cleanup):
    """删两次 —— 第一次 200，第二次必须 404。

    这是【幂等性】的边界：DELETE 重复调用不该报 500，
    但也要如实告诉调用方"它已经没了"。
    """
    created = projects_api.create_project(name="重复删除-用例")
    ast.assert_status(created, 201)
    project_id = created.json()["id"]
    cleanup(project_id)          # 先登记，失败也不会漏清理

    first = projects_api.delete_project(project_id)
    ast.assert_status(first, 200)

    second = projects_api.delete_project(project_id)
    ast.assert_status(second, 404)


# ==================================================================
# 七、数据一致性 —— 最后这条是给整个接口兜底的
# ==================================================================
@allure.title("所有校验失败的请求都不应产生任何数据")
def test_failed_validation_creates_nothing(projects_api):
    """把所有"校验失败"的输入连打一遍，最后确认库里一条都没多。

    单条用例只能证明"这一个输入没写进去"。
    这条用例把所有失败路径串起来，证明【没有任何一条漏网】。

    面试里这叫「数据污染检查」：
    接口测试不能只看返回值，还得回头看它有没有偷偷改数据。
    """
    before = len(projects_api.list_projects().json())

    ast.assert_status(projects_api.create_project(name=""), 400)
    ast.assert_status(projects_api.create_project(name="   "), 400)
    ast.assert_status(projects_api.create_project(name=NAME_51), 400)
    ast.assert_status(projects_api.create_project(name="desc超长", description=DESC_201), 400)
    ast.assert_status(projects_api.create_project(name=123), 400)

    after = len(projects_api.list_projects().json())
    assert before == after, f"有请求校验失败了，数据却依然入库（{before} 条 → {after} 条）"
