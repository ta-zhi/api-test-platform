# test_demo.py
"""
测试平台状态流转 - 示例用例
包含 3 个用例：2 个通过 + 1 个故意失败
上传后 pytest 会在该目录执行，因存在失败用例，退出码为 1。

如果想测试"全部通过"的成功路径，把 test_intentional_failure 整个函数注释掉即可。
"""


def test_addition():
    """加法测试"""
    assert 1 + 1 == 2


def test_string_methods():
    """字符串方法测试"""
    assert "hello".upper() == "HELLO"
    assert "  hi  ".strip() == "hi"


def test_intentional_failure():
    """故意失败的用例，用于测试失败状态下 is_pass=False 的流转。
    测试成功路径时注释掉本函数。"""
    assert 2 + 2 == 5, "故意写错：2+2 应该等于 4"
