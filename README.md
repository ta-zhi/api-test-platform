# 接口自动化测试平台

[![接口自动化测试](https://github.com/ta-zhi/api-test-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/ta-zhi/api-test-platform/actions/workflows/ci.yml)

一个**自己测自己**的测试闭环：为了有东西可测，先手写了一组 REST 接口；再用 pytest 搭一套分层接口自动化框架测它；另外用 Locust 压它、定位并优化了数据库瓶颈；最后把整个流程接进测试平台，一键执行、自动出 Allure 报告。

## 它由四部分组成

| 部分 | 目录 | 说明 |
|---|---|---|
| ① 被测系统 | [`suite/`](suite/) | 5 个 REST 接口（项目的增删改查 + 分页），基于 Django + SQLite |
| ② 接口自动化框架 | [`api_test/`](api_test/) | pytest + requests + Allure，**44 条用例**，分层设计 |
| ③ 性能测试 | [`perf_test/`](perf_test/) | Locust 压测脚本 + 阶梯加压 + 瓶颈定位脚本 |
| ④ 测试平台 | [`suite/admin.py`](suite/admin.py) [`suite/runner.py`](suite/runner.py) | 基于 Django Admin，勾选套件 → 立即执行 → 看报告 |

## 快速开始

```bash
# 1. 建虚拟环境（Python 3.12）
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

# 2. 装依赖
pip install -r requirements-test.txt

# 3. 初始化数据库（空库即可，用例不依赖预置数据）
python manage.py migrate

# 4. 起被测服务（另开一个终端）
python manage.py runserver
```

服务起来后，浏览器打开 <http://127.0.0.1:8000/api/projects/> 应该能看到接口返回的 JSON 列表。

## 跑测试，看报告

```bash
cd api_test
python run_tests.py                # 跑全部 44 条 + 生成报告 + 自动打开浏览器
python run_tests.py -m smoke       # 只跑冒烟用例
python run_tests.py -m regression  # 只跑回归用例
```

`run_tests.py` 会先确认被测服务活着，再跑用例，最后生成 Allure 报告。任何一步出问题都会给出人话提示，而不是让 44 条用例集体抛 `ConnectionError`。

## 持续集成

每次 push / PR，GitHub Actions 会自动：

1. 拉代码、装依赖、起被测服务
2. 跑全部 44 条用例（**用例失败会让这次构建变红**）
3. 生成 Allure 报告并作为构建产物留存

在 Actions 页面点进任意一次运行，底部 **Artifacts** 里能下载 `allure-report`。

> ⚠️ 下载下来的是静态 HTML。直接双击用 `file://` 打开常因浏览器安全策略白屏，
> 这是正常现象。想正常浏览可以本地跑 `allure open <报告目录>`。

## 技术栈

**被测系统**：Python 3.12 · Django 6.1 · SQLite（WAL 模式）
**接口测试**：pytest · requests · allure-pytest · PyYAML（数据驱动）
**性能测试**：Locust
**持续集成**：GitHub Actions

## 关于依赖文件的三个分层

```
requirements.txt        跑应用本身
requirements-test.txt   跑接口用例（CI 用这一份）
requirements-perf.txt   跑性能压测（只有本地按需装）
```

拆开的理由：CI 每次都会装依赖，而 Locust 会拖进 gevent 等一批较重的东西 —— 它跟"跑接口用例"没关系，没必要让每次构建都白装一遍。
