"""markers 演示专用文件（不属于正式用例，讲完就删）。

注意它【不会被自动收集】—— 因为 pytest.ini 里写了 testpaths = testcases，
不带参数跑 pytest 时只会去 testcases 目录找。
想跑它必须显式点名：pytest test_demo_marker.py

这样放是为了演示时不污染正式用例。
"""

import pytest


# ---- 贴了 smoke 标签的：核心功能 ----
@pytest.mark.smoke
def test_核心功能_登录():
    assert True


@pytest.mark.smoke
def test_核心功能_下单():
    assert True


# ---- 贴了 regression 标签的：边角功能 ----
@pytest.mark.regression
def test_边角功能_名字带空格():
    assert True


@pytest.mark.regression
def test_边角功能_名字超长():
    assert True


# ---- 这条【故意不打标签】----
# 用来演示：漏打标签会发生什么
def test_忘了打标签的():
    assert True
