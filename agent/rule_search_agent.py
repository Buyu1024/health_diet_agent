"""
Agent A: 规则检索Agent (agent_rule_search)
职责：
1. 提供 Milvus 向量检索能力，按健康标签检索饮食规则
2. 提供 A2A 发送能力，可将配餐请求通过A2A协议发给 Agent B（分布式部署时使用）
（不再负责 profile 管理和流程编排，由 api_server + Agent B 处理）
"""
from typing import Optional

from config.settings import settings
from agent.a2a_official_sdk import (
    create_user_message,
    create_task,
    update_task_status,
    add_artifact,
    is_task_completed,
)
from a2a.types import TaskState


# 健康关键词 → 疾病标签映射（与Milvus中人群标签对齐）
HEALTH_KEYWORD_MAP = {
    "高血压": ["高血压", "血压高", "降压", "血压"],
    "高脂血症": ["高血脂", "血脂高", "血脂", "降脂"],
    "高尿酸血症_痛风": ["痛风", "尿酸", "尿酸高", "高尿酸"],
    "糖尿病": ["糖尿病", "血糖", "血糖高", "降糖"],
    "肥胖": ["肥胖", "超重", "很胖", "减肥", "减重", "瘦身", "偏胖", "微胖"],
    "慢性肾脏病": ["肾病", "肾脏", "肾功能"],
    "感冒": ["感冒", "感冒发烧", "着凉"],
    "营养指南": ["营养均衡", "膳食指南", "营养搭配"],
}


def identify_health_label(user_input: str) -> str:
    """从用户输入中识别健康标签（模块级函数，供 api_server 调用）"""
    for label, keywords in HEALTH_KEYWORD_MAP.items():
        if any(kw in user_input for kw in keywords):
            return label
    return ""


class RuleSearchAgent:
    """Agent A: Milvus 饮食规则检索"""

    def __init__(self):
        self.agent_id = settings.A2A_AGENT_A_ID
        self.vector_store = None
        self._milvus_available = False

    async def initialize(self):
        """初始化，加载 VectorStore"""
        print(f"[Agent A] 初始化规则检索Agent: {self.agent_id}")
        try:
            from core.vector_store import VectorStore
            self.vector_store = VectorStore()
            self._milvus_available = True
            print(f"[Agent A] VectorStore加载成功，连接 Milvus 集合: {self.vector_store.collection_name}")
        except Exception as e:
            self._milvus_available = False
            print(f"[Agent A] VectorStore加载失败({e})，将使用通用饮食建议")

    def search_rules(self, user_input: str, health_label: str) -> Optional[dict]:
        """
        通过 Milvus 混合检索 + 重排序 获取饮食规则
        返回: {diet_notes: [str], milvus_used: bool} 或 None
        """
        if not self._milvus_available or not self.vector_store:
            return None

        try:
            source_filter = health_label if health_label else None
            results = self.vector_store.hybrid_search_with_rerank(
                query=user_input,
                k=3,
                source_filter=source_filter,
            )
            if results and len(results) > 0:
                top_doc = results[0]
                return {
                    "health_label": top_doc.metadata.get("source", health_label),
                    "diet_notes": [top_doc.page_content],
                }
        except Exception as e:
            print(f"[Agent A] VectorStore检索失败: {e}")
        return None

    async def _send_a2a_request(self, task) -> Optional[dict]:
        """
        发送 A2A 请求并解析响应（内部方法）
        Returns: A2A 响应的 payload (dict)，失败返回 None
        """
        try:
            import httpx
            import json
        except ImportError:
            print("[Agent A] 未安装 httpx，无法发送A2A请求")
            return None

        agent_b_url = settings.A2A_AGENT_B_URL
        print(f"[Agent A] 发送A2A请求 → {agent_b_url}")

        # 构建请求数据
        request_data = {
            "id": task.id,
            "context_id": task.context_id,
            "message": {
                "role": task.history[0].role,
                "parts": [{"text": p.text} for p in task.history[0].parts]
            }
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{agent_b_url}/tasks/send",
                    json=request_data
                )
                resp_data = resp.json()

            # 解析响应
            status = resp_data.get("status", {})
            state = status.get("state")
            
            # 支持字符串和枚举值两种格式
            is_completed = (
                state == "completed" or 
                state == "TASK_STATE_COMPLETED" or 
                state == 3  # Protobuf 枚举值
            )
            
            if is_completed:
                artifacts = resp_data.get("artifacts", [])
                if artifacts:
                    print(f"[Agent A] A2A请求成功")
                    # 提取产出物数据
                    for artifact in artifacts:
                        for part in artifact.get("parts", []):
                            if "data" in part:
                                return part["data"]
                            elif "text" in part:
                                return {"response": part["text"]}

            print(f"[Agent A] A2A响应状态异常: state={state}")
            return None

        except httpx.RequestError as e:
            print(f"[Agent A] A2A请求发送失败: {e}")
            return None
        except Exception as e:
            print(f"[Agent A] A2A响应解析失败: {e}")
            return None

    async def send_diet_request(
        self, user_query: str, user_profile: dict,
        health_label: str, diet_notes: list, constraints: dict
    ) -> Optional[dict]:
        """
        通过 A2A 协议发送配餐请求给 Agent B（分布式部署时使用）
        
        完整链路：
        1. 构造 A2A Task 对象
        2. HTTP POST 到 Agent B 的 /tasks/send 端点
        3. 解析 A2A 响应，提取 payload
        
        Returns: Agent B 返回的配餐数据 (dict)，失败返回 None
        """
        # 构建用户消息
        user_msg = create_user_message(user_query)
        
        # 创建任务
        task = create_task(user_msg)
        
        # 添加约束信息到任务元数据
        task.metadata["health_label"] = health_label
        task.metadata["diet_notes"] = diet_notes
        task.metadata["constraints"] = constraints
        task.metadata["user_profile"] = user_profile
        
        return await self._send_a2a_request(task)

    async def send_recipe_query(self, user_query: str) -> Optional[str]:
        """
        通过 A2A 协议发送食谱查询请求给 Agent B（分布式部署时使用）
        
        Returns: Agent B 返回的回答文本 (str)，失败返回 None
        """
        user_msg = create_user_message(user_query)
        task = create_task(user_msg)
        
        payload = await self._send_a2a_request(task)
        if payload:
            return payload.get("response", "")
        return None