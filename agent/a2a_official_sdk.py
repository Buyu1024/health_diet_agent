"""
基于 Google 官方 A2A SDK 的 Agent 实现
使用 a2a-sdk 官方包 (pip install a2a-sdk)
"""
from a2a.types import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
    Task,
    TaskState,
    TaskStatus,
    Message,
    Part,
    Artifact,
    Role,
)
from config.settings import settings


def create_agent_a_card() -> AgentCard:
    """创建 Agent A（规则检索Agent）的 AgentCard"""
    card = AgentCard()
    card.name = "规则检索Agent"
    card.description = "接收用户健康饮食相关提问，通过 Milvus 向量库检索饮食规则与约束"
    card.version = "1.0.0"
    card.documentation_url = settings.A2A_AGENT_B_URL.replace("/a2a/receive", "")
    card.default_input_modes.append("text")
    card.default_output_modes.extend(["text", "data"])
    
    skill = AgentSkill()
    skill.id = "health_rule_search"
    skill.name = "健康饮食规则检索"
    skill.description = "基于用户健康标签，从 Milvus 向量库检索个性化饮食禁忌与约束"
    skill.tags.extend(["milvus", "health", "diet-rules"])
    card.skills.append(skill)
    
    card.capabilities.streaming = False
    card.capabilities.push_notifications = False
    
    return card


def create_agent_b_card() -> AgentCard:
    """创建 Agent B（饮食助手Agent）的 AgentCard"""
    card = AgentCard()
    card.name = "健康饮食助手Agent"
    card.description = "接收 A2A 协议传来的饮食规则，调用 MCP 食谱工具筛选、分析食谱"
    card.version = "1.0.0"
    card.documentation_url = settings.A2A_AGENT_B_URL.replace("/a2a/receive", "")
    card.default_input_modes.extend(["text", "data"])
    card.default_output_modes.extend(["text", "data"])
    
    skill = AgentSkill()
    skill.id = "meal_plan"
    skill.name = "个性化配餐"
    skill.description = "根据饮食约束和健康标签，调用 MCP 工具生成一日三餐配餐方案"
    skill.tags.extend(["meal-plan", "diet", "nutrition"])
    card.skills.append(skill)
    
    card.capabilities.streaming = False
    card.capabilities.push_notifications = False
    
    return card


def create_user_message(text: str) -> Message:
    """创建用户消息"""
    part = Part()
    part.text = text
    
    msg = Message()
    msg.role = Role.ROLE_USER
    msg.parts.append(part)
    
    return msg


def create_agent_message(text: str) -> Message:
    """创建 Agent 消息"""
    part = Part()
    part.text = text
    
    msg = Message()
    msg.role = Role.ROLE_AGENT
    msg.parts.append(part)
    
    return msg


def create_task(message: Message, context_id: str = None) -> Task:
    """创建任务"""
    import uuid
    from datetime import datetime, timezone
    
    task = Task()
    task.id = f"task_{uuid.uuid4().hex[:12]}"
    task.context_id = context_id or f"context_{uuid.uuid4().hex[:8]}"
    task.status.state = TaskState.TASK_STATE_SUBMITTED
    task.status.timestamp.GetCurrentTime()
    task.history.append(message)
    
    return task


def update_task_status(task: Task, state: TaskState) -> Task:
    """更新任务状态"""
    task.status.state = state
    task.status.timestamp.GetCurrentTime()
    
    return task


def add_artifact(task: Task, name: str, text: str = None, data: dict = None) -> Task:
    """添加产出物"""
    part = Part()
    if text:
        part.text = text
    elif data:
        part.data = data
    
    artifact = Artifact()
    artifact.name = name
    artifact.parts.append(part)
    
    task.artifacts.append(artifact)
    return task


def is_task_completed(task: Task) -> bool:
    """判断任务是否完成"""
    return task.status.state in [
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
    ]