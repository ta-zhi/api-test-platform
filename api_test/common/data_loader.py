"""测试数据加载层。

解决的痛点：测试数据原来硬编码在用例里。

    def test_create_project(projects_api):
        response = projects_api.create_project(name="面试演示项目")   # ← 数据写死在这

这样有三个问题：
  1. 想加一组数据，就得把用例复制一遍 —— 10 组数据 = 10 条几乎一样的用例
  2. 测试数据和测试逻辑混在一起，改数据要动代码
  3. 数据没法给非开发人员维护（产品/业务同学看 YAML 也能加用例）

所以把数据搬到 data/*.yaml，由这一层统一读进来。

为什么用 yaml.safe_load 而不是 yaml.load？
    yaml.load 可以执行文件里的任意 Python 对象构造，等于「打开一个文件就执行它」。
    测试数据文件是纯配置，用 safe_load 就够了，也更安全。
    这是面试爱问的一个小细节。
"""

from pathlib import Path

import yaml

# __file__          = .../api_test/common/data_loader.py
# .parent           = .../api_test/common
# .parent.parent    = .../api_test
DATA_DIR = Path(__file__).parent.parent / "data"


def load_yaml(filename: str):
    """读取 data/ 目录下的 YAML 文件。

    filename 只写文件名，比如 "projects_create.yaml"，
    路径拼接交给这里，用例层不用关心文件到底放在哪。
    """
    path = DATA_DIR / filename

    if not path.exists():
        raise FileNotFoundError(
            f"测试数据文件不存在：{path}\n"
            f"（data 目录下的文件有：{[p.name for p in DATA_DIR.glob('*.yaml')]}）"
        )

    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
