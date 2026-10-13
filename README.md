# 接口自动化测试平台

[![接口自动化测试](https://github.com/ta-zhi/api-test-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/ta-zhi/api-test-platform/actions/workflows/ci.yml)
[![在线测试报告](https://img.shields.io/badge/Allure-%E5%9C%A8%E7%BA%BF%E6%B5%8B%E8%AF%95%E6%8A%A5%E5%91%8A-blue)](https://ta-zhi.github.io/api-test-platform/)

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
3. 生成 Allure 报告 → 发布成在线网页，同时作为构建产物留档

**[📊 在线测试报告](https://ta-zhi.github.io/api-test-platform/)** ← 直接点开就能看，不用下载

实现方式：报告用 `upload-pages-artifact` 打成包，再由 `deploy-pages`
发布到 GitHub Pages。注意这两步在**单独的 job** 里，且带 `always()` ——
用例失败时报告照样发布，因为那正是最需要看报告的时候。

> 💡 为什么不用"下载 artifact 双击打开"？下载下来的是静态 HTML，
> 用 `file://` 打开会因为浏览器禁止本地页面读取本地文件而白屏。
> 想本地看可以跑 `allure open <报告目录>`（它会起个本地服务器）。

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
