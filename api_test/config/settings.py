"""环境配置。

当前只有一套配置，Day4 会扩展成 dev / test 多环境切换。
把 base_url、超时这类「环境相关」的东西集中放在这里，
用例层永远不出现具体的域名。
"""

ENVS = {
    "test": {
        "base_url": "https://jsonplaceholder.typicode.com",
        "timeout": 10,
    },
    # 预留：将来被测系统换成你自己的 Django 平台时，加一个 dev 环境即可
    "dev": {
        "base_url": "http://127.0.0.1:8000",
        "timeout": 10,
    },
}

# 默认指向自己的 Django 平台。
# 为什么从 "test" 改过来：testpaths 里全是项目接口的用例，
# 默认还留在假接口上的话，忘写 --env dev 就会满屏 404，
# 而且报错信息看起来像"用例写错了"，很容易查半天。
DEFAULT_ENV = "dev"


def get_config(env: str = DEFAULT_ENV) -> dict:
    """按环境名取配置，环境不存在时直接报错，避免静默跑到错的环境上。"""
    if env not in ENVS:
        raise ValueError(f"未知环境: {env}，可选: {list(ENVS)}")
    return ENVS[env]
