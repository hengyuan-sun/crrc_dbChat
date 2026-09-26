import logging
from typing import Optional

from fastapi import Header

from dbgpt._private.pydantic import BaseModel

logger = logging.getLogger(__name__)


class UserRequest(BaseModel):
    user_id: Optional[str] = None
    user_no: Optional[str] = None
    real_name: Optional[str] = None
    # same with user_id
    user_name: Optional[str] = None
    user_channel: Optional[str] = None
    role: Optional[str] = "normal"
    nick_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    nick_name_like: Optional[str] = None


def get_user_from_headers(user_id: Optional[str] = Header(None)):
    """从兼容请求头构造用户对象；当前实现仅是未可信的演示桩。

    Args:
        user_id: 请求方可自行设置的用户标识，不是经过验证的身份凭证。

    Returns:
        UserRequest: 有请求头时将其映射为 `admin`；缺少请求头时返回固定
            `001/admin`。调用方不能把此结果视为可信认证上下文。

    Raises:
        Exception: 用户对象构造失败时包装底层异常。

    安全边界：该函数没有验证签名、令牌、账号状态、组织或 workspace；
    在接入可信内网身份提供方前，不能用于保护生产接口或授予任何权限。
    """
    try:
        # Mock User Info
        if user_id:
            return UserRequest(
                user_id=user_id, role="admin", nick_name=user_id, real_name=user_id
            )
        else:
            return UserRequest(
                user_id="001", role="admin", nick_name="dbgpt", real_name="dbgpt"
            )
    except Exception as e:
        logging.exception("Authentication failed!")
        raise Exception(f"Authentication failed. {str(e)}")
