"""HTTP 请求封装层。

这一层解决的是「所有接口都需要的公共能力」，用例层不需要重复写：
  1. 会话复用     —— 一个 Session 走到底，复用 TCP 连接，比每次 requests.get() 快
  2. 超时统一控制 —— 避免某个接口卡住把整轮回归拖死
  3. 失败重试     —— 只对「可恢复」的错误重试，业务错误不重试
  4. 日志         —— 请求和响应统一落日志，失败时能直接定位到是哪条接口

面试点：为什么不直接用 requests.get()？
        因为每个用例都写一遍 timeout / 重试 / 日志，重复且容易漏。
"""

import json
import logging
import time

import allure
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# 附着到报告里的响应体最长记这么多字符。
# 查列表接口可能返回几十 KB，全塞进报告会让报告又大又卡，没必要。
MAX_ATTACH_BODY = 2000


class HttpClient:
    def __init__(self, base_url: str, timeout: int = 10, retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

        # only 5xx / 连接错误这类「服务端临时抖动」才重试；
        # 4xx 是业务错误，重试多少次结果都一样，重试只会掩盖问题。
        retry = Retry(
            total=retries,
            backoff_factor=0.5,               # 重试间隔 0.5s、1s 递增，避免打爆服务端
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        kwargs.setdefault("timeout", self.timeout)

        logger.info("→ %s %s | params=%s json=%s",
                    method, url, kwargs.get("params"), kwargs.get("json"))
        start = time.perf_counter()

        response = self.session.request(method, url, **kwargs)

        cost_ms = (time.perf_counter() - start) * 1000
        logger.info("← %s %s | %.0fms", response.status_code, url, cost_ms)

        # 把这一来一回写进 Allure 报告
        self._attach(method, url, kwargs, response, cost_ms)
        return response

    @staticmethod
    def _attach(method, url, kwargs, response, cost_ms):
        """把请求和响应附着到 Allure 报告上。

        【为什么放在这一层，而不是写进用例里？】

        attach 是 allure 的"贴附件"功能：贴上去的东西会出现在报告的
        用例详情里，谁点开都能看到。

        放到用例里也能做，但 44 条用例就得写 44 遍，而且第 45 条
        一定会有人忘。这里（所有请求唯一的出口）写一次，
        全部用例、全部接口就自动都有了，用例代码一个字都不用动。

        这是框架设计里很典型的一条思路：
        「公共能力上收，业务用例下放」——
        凡是每个用例都需要、但每个用例都不该关心的东西（日志、报告、
        重试、鉴权），全部收进框架层。

        另一个实际好处：用例失败时，报告里直接躺着当时的请求和响应，
        不用再翻控制台日志、也不用手动发一次请求去复现。
        """
        body = kwargs.get("json")
        allure.attach(
            f"{method} {url}\n"
            f"查询参数: {kwargs.get('params') or '(无)'}\n"
            f"请求体:\n"
            f"{json.dumps(body, ensure_ascii=False, indent=2) if body is not None else '(无)'}",
            name="→ 请求",
            attachment_type=allure.attachment_type.TEXT,
        )

        resp_body = response.text
        if len(resp_body) > MAX_ATTACH_BODY:
            resp_body = f"{resp_body[:MAX_ATTACH_BODY]}\n...(已截断，响应体共 {len(response.text)} 字符)"

        allure.attach(
            f"状态码: {response.status_code}\n"
            f"耗时: {cost_ms:.0f}ms\n"
            f"响应体:\n{resp_body}",
            name="← 响应",
            attachment_type=allure.attachment_type.TEXT,
        )

    # ---- 下面是语义化的快捷方法，让接口层读起来更自然 ----

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> requests.Response:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs) -> requests.Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self.request("DELETE", path, **kwargs)

    def close(self):
        self.session.close()
