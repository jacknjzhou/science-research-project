"""请求体 Schema 验证层（pydantic v2，对齐"接口请求加入 schema 验证定义"）。

用法：
    from core.reqschema import validate_body
    from apps.asset.schemas import AssetIn

    @validate_body(AssetIn)
    @transaction.atomic
    def create_asset(request: HttpRequest):
        b = read_json(request)   # 原逻辑不变；已通过 schema 验证

- 校验失败 → 统一信封 `{code: 40001, message: "参数校验失败: ..."}` HTTP 400，
  与手工校验语义一致（ninja 的 payload Schema 校验同样会落到该语义）。
- 通过验证的实例挂在 `request.validated`（pydantic 模型），原 handler 可继续用
  read_json 读取原始 dict，逐步迁移不强制。
- Schema 定义集中在各域 `apps/<x>/schemas.py`（接口请求的验证定义）。
- 设计取舍：token/枚举类字段一律用 str 放行，非法取值仍由 handler 按业务码
  （40002 等）判定——schema 只负责结构/必填/类型。
"""
from __future__ import annotations

import functools

from pydantic import BaseModel, ConfigDict, ValidationError

from core.httpx import err, read_json_soft


class BaseIn(BaseModel):
    """域 Schema 公共基类：忽略未声明字段（向后兼容渐进收紧）。"""

    model_config = ConfigDict(extra="ignore")


def validate_body(schema: type[BaseModel], optional: bool = False):
    """装饰器：对 POST/PUT/PATCH 请求体做 schema 验证。

    optional=True 时允许空 body（通过 None），用于"无 body 合法"的端点；
    有 body 仍须通过校验。
    """
    def deco(func):
        @functools.wraps(func)
        def wrapper(request, *args, **kwargs):
            if request.method in ("POST", "PUT", "PATCH"):
                raw = read_json_soft(request)
                if optional and not raw:
                    request.validated = None
                else:
                    try:
                        request.validated = schema(**raw)
                    except ValidationError as e:
                        detail = "; ".join(
                            f"{'.'.join(map(str, it['loc']))}: {it['msg']}"
                            for it in e.errors()[:8]
                        )
                        return err(request, 400, 40001, f"参数校验失败：{detail}")
                    except Exception:
                        return err(request, 400, 40001, "参数校验失败：请求体格式非法")
            return func(request, *args, **kwargs)
        return wrapper
    return deco
