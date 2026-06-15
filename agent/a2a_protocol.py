"""
A2A 通信协议层
实现 Agent A ↔ Agent B 之间的标准消息传递
支持 HTTP 和本地直连两种通信模式
"""
import uuid
import time
from typing import Optional


class A2AMessage:
    """A2A 标准消息体"""

    @staticmethod
    def build_request(
        sender_id: str,
        receiver_id: str,
        user_query: str,
        task: str = "diet_recommend",
        health_label: str = "",
        diet_notes: list = None,
        hard_constraints: dict = None,
        user_profile: dict = None,
        session_id: str = None,
    ) -> dict:
        """
        构造 A2A 任务请求消息 (Agent A → Agent B)
        
        task 类型:
        - "diet_recommend": 配餐请求（默认）
        - "recipe_query": 食谱查询请求
        """
        payload = {
            "user_query": user_query,
            "health_label": health_label,
            "diet_notes": diet_notes or [],
            "hard_constraints": hard_constraints or {},
        }
        if user_profile:
            payload["user_profile"] = user_profile
        return {
            "a2a_version": "1.0",
            "msg_id": f"a2a_req_{uuid.uuid4().hex[:8]}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "sender": sender_id,
            "receiver": receiver_id,
            "msg_type": "request",
            "session_id": session_id or f"sess_{uuid.uuid4().hex[:8]}",
            "task": task,
            "payload": payload,
        }

    @staticmethod
    def build_response(
        req_msg: dict,
        sender_id: str,
        result_data: dict,
        status: str = "success",
    ) -> dict:
        """
        构造 A2A 任务响应消息 (Agent B → Agent A)

        根据原始请求消息构造标准的 A2A 响应，用于 Agent B 处理完任务后
        将结果返回给 Agent A。响应消息通过 ref_msg_id 关联原始请求，
        通过 session_id 保持会话一致性。

        Args:
            req_msg: Agent A 发送的原始请求消息字典，用于提取 sender、
                     session_id 和 msg_id 等信息
            sender_id: 当前发送方（即 Agent B）的标识
            result_data: 任务处理结果数据，作为响应 payload
            status: 响应状态，默认为 "success"，异常时可设为 "error"

        """
        return {
            "a2a_version": "1.0",
            "msg_id": f"a2a_resp_{uuid.uuid4().hex[:8]}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "sender": sender_id,
            "receiver": req_msg.get("sender", ""),
            "msg_type": "response",
            "session_id": req_msg.get("session_id", ""),
            "ref_msg_id": req_msg.get("msg_id", ""),
            "status": status,
            "payload": result_data,
        }

    @staticmethod
    def build_error(
        req_msg: dict,
        sender_id: str,
        error_code: str,
        error_msg: str,
    ) -> dict:
        """构造 A2A 异常消息"""
        return {
            "a2a_version": "1.0",
            "msg_id": f"a2a_err_{uuid.uuid4().hex[:8]}",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "sender": sender_id,
            "receiver": req_msg.get("sender", ""),
            "msg_type": "error",
            "session_id": req_msg.get("session_id", ""),
            "ref_msg_id": req_msg.get("msg_id", ""),
            "error_code": error_code,
            "error_msg": error_msg,
        }

    @staticmethod
    def validate(msg: dict) -> bool:
        """校验A2A消息合法性"""
        required_fields = ["a2a_version", "msg_id", "sender", "receiver", "msg_type"]
        return all(field in msg for field in required_fields)

    @staticmethod
    def parse_constraints(msg: dict) -> dict:
        """从A2A请求中提取饮食约束规则"""
        payload = msg.get("payload", {})
        return payload.get("hard_constraints", {})

    @staticmethod
    def parse_diet_notes(msg: dict) -> list:
        """从A2A请求中提取饮食注意事项"""
        payload = msg.get("payload", {})
        return payload.get("diet_notes", [])

    @staticmethod
    def parse_user_query(msg: dict) -> str:
        """从A2A请求中提取用户原始问题"""
        payload = msg.get("payload", {})
        return payload.get("user_query", "")