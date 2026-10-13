"""接口视图。

提供一组 REST 风格的接口，用来管理「测试项目」(Project)。
它们是 api_test 接口自动化框架的被测对象。

设计要点（面试可讲）：
  1. 状态码语义化 —— 创建成功返回 201、参数错误返回 400、资源不存在返回 404，
     不是一个 200 走天下。这样测试用例才能通过状态码判断行为是否正确。
  2. 每个分支都有明确返回值 —— 不存在"悄悄失败"的情况。
  3. GET/PUT/DELETE 挂在同一个 URL 上，靠请求方法区分，符合 REST 风格。
"""

import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Project

# ---------------------------------------------------------------------------
# 列表接口的分页参数
#
# 【为什么必须有上限，而不是"客户端想拿多少给多少"？】
# 没有上限，客户端传 ?limit=999999999 就等于把分页关掉了。
# 那这次优化等于白做 —— 只要有一个调用方这么干，数据库照样被打穿。
# 所以上限必须由服务端说了算，不能交给客户端。
#
# 【为什么默认只给 100 条，而不是"默认全给、要分页自己传"？】
# 因为"默认全给"意味着默认行为就是最危险的那个。
# 性能优化的一条基本原则：把安全的选择设成默认值，
# 让需要大量数据的人显式声明自己的意图。
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


def _parse_paging(request):
    """从 query string 里取分页参数，并把越界的值夹回合法范围。

    任何非法输入都不该让服务端报错，也不该让服务端干重活，所以统一兜底：
        limit  不存在/非法  → 用默认值；小于 1 抬到 1；大于上限压到上限
        offset 不存在/非法  → 用 0；  小于 0 抬到 0
    """
    def _as_int(name, default):
        raw = request.GET.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = max(1, min(_as_int("limit", DEFAULT_LIMIT), MAX_LIMIT))
    offset = max(0, _as_int("offset", 0))
    return limit, offset


def _parse_body(request) -> dict:
    """把请求体里的 JSON 解析成字典，解析不出对象就返回空字典。

    【这里有两道坎，只堵一道是不够的】

    第一道：JSON 语法就不合法
        "{这不是json"  →  json.loads 直接抛 JSONDecodeError

    第二道（边界用例抓出来的）：语法合法，但解出来的不是对象
        "null"   →  None
        "123"    →  123
        '"abc"'  →  "abc"
        "[1,2]"  →  [1, 2]

    这几个对 json.loads 来说【毫无毛病】，所以 try/except 一个都拦不住，
    下一行 data.get("name") 立刻 AttributeError → 500。
    类型不对是客户端的问题，服务端不该崩，所以这里再补一道 isinstance。

    教训：只想到"格式错"是不够的，"格式对但类型错"是另一类问题。
    """
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}
    return data


def _as_text(value) -> str:
    """把任意输入安全地转成字符串；不是字符串的一律当空字符串。

    【为什么需要这么个函数？】
    这是边界用例（"name 传数字 123"那条）抓出来的第二个缺陷：

        name = (data.get("name") or "").strip()

    这行看着没问题，其实只兜得住 None / "" / [] / 0 这些【假值】。
    一旦传进来 123、True 这种【真值】，or 不生效，123 原样透传，
    紧接着 123.strip() 直接 AttributeError → Django 返回 500。

    500 的意思是"服务端挂了"，但参数类型不对明明是【客户端的错】，
    应该老老实实回 400。所以这里必须先做类型归一化。

    另一个好处：App 端传 int、前端传 bool 这类脏数据会在这一层
    被静默转成空字符串，往下走就是标准的"name 不能为空" 400，
    不会再有任何一条路径能炸出 500。
    """
    if not isinstance(value, str):
        return ""
    return value


# 从模型里反查上限，避免和 models.py 各写一份 50、改一处漏一处
NAME_MAX_LENGTH = Project._meta.get_field("name").max_length
DESC_MAX_LENGTH = Project._meta.get_field("description").max_length


def _validate_project(data: dict):
    """校验项目参数。返回错误信息字符串；没问题返回 None。

    【为什么必须手写这段校验？】
    这是接口自动化用例（"名字51个字符"那条边界用例）帮我抓出来的缺陷：

        Django 的 max_length 只在「表单 / 序列化器」里才自动生效。
        直接 Project.objects.create(name=超长字符串) 是不会校验的，
        超长数据会原样写进数据库。

    也就是说，光在 models.py 里写 max_length=50 是【不够的】，
    接口层必须自己再校验一遍，才能真正挡住脏数据。
    """
    name = _as_text(data.get("name")).strip()
    if not name:
        return "name 不能为空"
    if len(name) > NAME_MAX_LENGTH:
        return f"name 长度不能超过 {NAME_MAX_LENGTH} 个字符"

    description = _as_text(data.get("description"))
    if len(description) > DESC_MAX_LENGTH:
        return f"description 长度不能超过 {DESC_MAX_LENGTH} 个字符"

    return None


@csrf_exempt
@require_http_methods(["GET", "POST"])
def project_list(request):
    """GET  /api/projects/   查询全部项目
       POST /api/projects/   新建一个项目
    """
    if request.method == "GET":
        # 【这一行原来长这样】
        #     projects = [p.to_dict() for p in Project.objects.all().order_by("id")]
        # 它把【整张表】一次性查出来返回，没有分页。
        # 库里 2 条时毫无问题，涨到 1 万条后：每次请求要实例化 1 万个 ORM 对象、
        # 建 1 万个字典、序列化出 1.5 MB 响应体，纯计算就要 78ms，
        # 而且这个成本会随数据量【线性】增长 —— 数据越多越慢，永远在恶化。
        #
        # 改成"只取当前这一页"：
        #   · 单次请求的工作量从"跟表大小相关"变成"跟每页条数相关"，是个常数
        #   · 数据涨到 100 万条，只要没人翻到最后一页，响应时间就不变
        #
        # 【为什么响应仍然是数组，不改成 {"count":…,"results":[…] }】
        # 因为已有 44 条接口用例依赖 isinstance(response.json(), list)。
        # 改成对象会让这批用例全挂 —— 这正是"回归测试"存在的意义：
        # 它逼你在改接口时想清楚"这个改动会破坏谁"，而不是想改就改。
        #
        # 那总数怎么给调用方？用 X-Total-Count 响应头。
        # 这是 REST 里很常见的做法：既保住了响应体结构，又没丢信息。
        # 如果以后要上 v2，再改成带分页元信息的对象更规范。
        limit, offset = _parse_paging(request)
        queryset = Project.objects.all().order_by("id")
        total = queryset.count()
        projects = [p.to_dict() for p in queryset[offset:offset + limit]]

        response = JsonResponse(projects, safe=False)
        response["X-Total-Count"] = total
        return response

    # ---- POST：新建 ----
    data = _parse_body(request)
    error = _validate_project(data)
    if error:
        return JsonResponse({"error": error}, status=400)

    project = Project.objects.create(
        name=_as_text(data.get("name")).strip(),
        description=_as_text(data.get("description")),
    )
    return JsonResponse(project.to_dict(), status=201)


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
def project_detail(request, pk):
    """GET    /api/projects/<id>/   查询单个项目
       PUT    /api/projects/<id>/   更新项目
       DELETE /api/projects/<id>/   删除项目
    """
    try:
        project = Project.objects.get(pk=pk)
    except Project.DoesNotExist:
        return JsonResponse({"error": "项目不存在"}, status=404)

    if request.method == "GET":
        return JsonResponse(project.to_dict())

    if request.method == "PUT":
        data = _parse_body(request)
        error = _validate_project(data)
        if error:
            return JsonResponse({"error": error}, status=400)

        project.name = _as_text(data.get("name")).strip()
        project.description = _as_text(data.get("description"))
        project.save()
        return JsonResponse(project.to_dict())

    # ---- DELETE ----
    project.delete()
    return JsonResponse({"message": "删除成功"})
