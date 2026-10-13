"""接口定义层：测试项目（Project）。

被测对象就是你自己 Django 项目里 suite/views.py 写的那组接口：

    GET    /api/projects/        查询全部项目
    POST   /api/projects/        新建项目
    GET    /api/projects/{id}/   查询单个项目
    PUT    /api/projects/{id}/   更新项目
    DELETE /api/projects/{id}/   删除项目

注意：这一层和 posts_api.py 长得几乎一模一样。
「换个被测系统」在这里的代价 = 换掉 RESOURCE 和几个方法名。
用例层、客户端层、配置层一行都不用动 —— 这就是分层的价值。
"""


class ProjectsApi:
    RESOURCE = "api/projects"

    def __init__(self, client):
        self.client = client

    def list_projects(self):
        """GET /api/projects/"""
        return self.client.get(f"/{self.RESOURCE}/")

    def create_project(self, name: str, description: str = ""):
        """POST /api/projects/ —— 成功返回 201 + 新建出来的完整数据"""
        return self.client.post(
            f"/{self.RESOURCE}/",
            json={"name": name, "description": description},
        )

    def get_project(self, project_id: int):
        """GET /api/projects/{id}/ —— 不存在返回 404"""
        return self.client.get(f"/{self.RESOURCE}/{project_id}/")

    def update_project(self, project_id: int, name: str, description: str = ""):
        """PUT /api/projects/{id}/ —— 全量更新"""
        return self.client.put(
            f"/{self.RESOURCE}/{project_id}/",
            json={"name": name, "description": description},
        )

    def delete_project(self, project_id: int):
        """DELETE /api/projects/{id}/"""
        return self.client.delete(f"/{self.RESOURCE}/{project_id}/")
