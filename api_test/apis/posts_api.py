"""接口定义层。

职责：把「接口」翻译成 Python 方法。
  - 接口的 URL、请求方法只在这一层出现
  - 用例层只调方法名，不关心 URL 长什么样

好处：接口地址或参数变了，只改这一层，所有用例不用动。
      （面试常问：接口和用例怎么解耦？答案就是这一层）
"""


class PostsApi:
    RESOURCE = "posts"

    def __init__(self, client):
        self.client = client

    def list_posts(self, **params):
        """GET /posts —— 支持 _limit / userId 等查询参数"""
        return self.client.get(f"/{self.RESOURCE}", params=params)

    def get_post(self, post_id: int):
        """GET /posts/{id}"""
        return self.client.get(f"/{self.RESOURCE}/{post_id}")

    def create_post(self, payload: dict):
        """POST /posts"""
        return self.client.post(f"/{self.RESOURCE}", json=payload)

    def update_post(self, post_id: int, payload: dict):
        """PUT /posts/{id} —— 全量更新（没传的字段会被清空）"""
        return self.client.put(f"/{self.RESOURCE}/{post_id}", json=payload)

    def patch_post(self, post_id: int, payload: dict):
        """PATCH /posts/{id} —— 部分更新（只改传了的字段）"""
        return self.client.patch(f"/{self.RESOURCE}/{post_id}", json=payload)

    def delete_post(self, post_id: int):
        """DELETE /posts/{id}"""
        return self.client.delete(f"/{self.RESOURCE}/{post_id}")
