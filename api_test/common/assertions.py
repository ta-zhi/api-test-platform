"""断言封装层。

不是 `assert` 不好用，而是「裸 assert 失败时给的信息太少了」。

--------------------------------------------------------------------------
裸 assert 失败时你看到的是：

    E   assert 400 == 201

然后你得自己再手工发一次请求，才知道服务端到底返回了什么、返回体长什么样。
定位一个失败要花好几分钟。

--------------------------------------------------------------------------
用这里的封装失败时你看到的是：

    AssertionError:
    状态码不符
      期望: 201
      实际: 400
      请求: POST http://127.0.0.1:8000/api/projects/
      响应体: {"error": "name 不能为空"}

一眼就能看出「服务端说 name 不能为空，但我期望它能建成功」——
是测试数据写错了，还是后端校验写严了，当场就能判断。

--------------------------------------------------------------------------
面试点：断言封装的价值是什么？
        不是「少写几个字符」，而是「失败时能自解释」。
        自动化用例失败后，最贵的是「人去定位原因」的那几分钟。
"""

# 用来区分「字段值就是 None」和「字段压根不存在」两种情况
_MISSING = object()


def _brief(response, limit: int = 300) -> str:
    """把响应体截断成一个适合放进报错信息的字符串。

    服务端返回上万字符的时候，全打出来会把控制台刷爆，
    反而看不清关键信息。
    """
    try:
        text = response.text
    except Exception:
        return "<响应体无法读取>"
    if len(text) > limit:
        return text[:limit] + f"...（还有 {len(text) - limit} 个字符）"
    return text


def assert_status(response, expected: int):
    """断言 HTTP 状态码，失败时把实际响应一起打出来。"""
    if response.status_code != expected:
        raise AssertionError(
            f"\n状态码不符"
            f"\n  期望: {expected}"
            f"\n  实际: {response.status_code}"
            f"\n  请求: {response.request.method} {response.request.url}"
            f"\n  响应体: {_brief(response)}"
        )


def assert_field(body: dict, field: str, expected):
    """断言响应体里某个字段的值。"""
    actual = body.get(field, _MISSING)

    if actual is _MISSING:
        raise AssertionError(
            f"\n响应体里没有字段 {field!r}"
            f"\n  实际字段: {list(body)}"
        )

    if actual != expected:
        raise AssertionError(
            f"\n字段 {field!r} 的值不符"
            f"\n  期望: {expected!r}"
            f"\n  实际: {actual!r}"
        )


def assert_has_keys(body: dict, keys):
    """断言响应体里必须有这些字段。

    接口少返回一个字段，前端可能不会立刻报错，
    而是在某个用户点了某个按钮之后才崩 —— 所以要在接口层就拦住。
    """
    missing = [k for k in keys if k not in body]
    if missing:
        raise AssertionError(
            f"\n响应体缺少字段: {missing}"
            f"\n  实际字段: {list(body)}"
        )


def assert_schema(body: dict, schema: dict):
    """断言响应体里各字段的「类型」是否和预期一致。

    schema 形如 {"id": int, "name": str}

    为什么只查类型不查具体值？
      因为具体值每次都变（id 是自增的、created_at 是当前时间），
      但「id 应该是数字不是字符串」这种约定永远不变。
      这类检查能抓到「接口把 int 返回成了 str」这种隐蔽 bug ——
      前端拿 "123" 去做加法会变成 "123456"，而不是 123。
    """
    assert_has_keys(body, list(schema))

    for field, expect_type in schema.items():
        actual = body[field]
        # bool 是 int 的子类，排除掉，避免 True 被当成合法的 int
        if isinstance(actual, bool) and expect_type is int:
            ok = False
        else:
            ok = isinstance(actual, expect_type)
        if not ok:
            raise AssertionError(
                f"\n字段 {field!r} 类型不对"
                f"\n  期望类型: {expect_type.__name__}"
                f"\n  实际类型: {type(actual).__name__}（值={actual!r}）"
            )
