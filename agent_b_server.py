"""
Agent B 独立服务（分布式部署时使用）

启动方式：python agent_b_server.py
监听端口：8001

功能：
- 接收 A2A 协议请求，调用 Agent B 处理配餐任务
- 提供健康检查和状态接口

与主服务 (api_server.py, 端口8000) 分离运行，
主服务通过 A2A 协议 (HTTP) 向本服务发送配餐请求。
"""
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from config.settings import settings
from agent.diet_assistant_agent import DietAssistantAgent


# ==================== 数据模型 ====================

class MessagePart(BaseModel):
    """消息部分"""
    text: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class Message(BaseModel):
    """A2A 消息"""
    role: str
    parts: List[MessagePart]


class A2ATaskRequest(BaseModel):
    """官方 A2A SDK 格式的任务请求"""
    id: str
    context_id: Optional[str] = None
    message: Message


class A2ADirectRequest(BaseModel):
    """旧版 A2A 消息请求（向后兼容）"""
    a2a_version: Optional[str] = None
    msg_id: Optional[str] = None
    timestamp: Optional[str] = None
    sender: Optional[str] = None
    receiver: Optional[str] = None
    msg_type: Optional[str] = None
    session_id: Optional[str] = None
    task: Optional[str] = None
    payload: Optional[dict] = None


# ==================== FastAPI 应用 ====================

agent_b: Optional[DietAssistantAgent] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    global agent_b

    print("=" * 60)
    print("[Agent B Server] 启动独立 Agent B 服务...")
    print("=" * 60)

    agent_b = DietAssistantAgent()
    await agent_b.initialize()

    if not agent_b.mcp_tools:
        print("[WARN] Agent B 未加载到MCP工具，部分功能不可用")

    print(f"\n[OK] Agent B 独立服务就绪")
    print(f"  Agent ID: {agent_b.agent_id}")
    print(f"  LLM: {settings.QWEN_MODEL}")
    print(f"  MCP工具: {len(agent_b.mcp_tools)}个")
    print(f"  监听: http://0.0.0.0:8001")
    print("=" * 60 + "\n")

    yield

    print("[Agent B Server] 关闭...")


app = FastAPI(
    title="Agent B Standalone Service",
    description="Agent B 独立服务 - 接收 A2A 协议请求",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 路由 ====================


@app.post("/a2a/tasks/send")
async def a2a_receive(request: dict):
    """
    A2A 任务接收端点（支持官方 SDK 格式和旧版格式）

    接收来自 Agent A / api_server 的 A2A 请求，返回 A2A 响应。
    完整链路：
    1. 校验 A2A 消息格式
    2. 提取 payload (user_query, health_label, diet_notes, user_profile)
    3. 调用 Agent B 处理配餐任务
    4. 包装为 A2A 响应返回
    """
    try:
        if not agent_b:
            raise HTTPException(status_code=503, detail="Agent B 未初始化")

        # 判断请求格式
        if "id" in request and "message" in request:
            # 官方 SDK 格式
            print(f"[Agent B Server] 收到A2A请求(官方格式): id={request.get('id')}")
            response = await agent_b.handle_a2a_task(request)
        elif "a2a_version" in request or "msg_id" in request:
            # 旧版格式 - 转换为官方格式
            print(f"[Agent B Server] 收到A2A请求(旧版格式): msg_id={request.get('msg_id')}")
            task = {
                "id": request.get("msg_id", ""),
                "context_id": request.get("session_id", ""),
                "message": {
                    "role": "user",
                    "parts": [{"text": request.get("payload", {}).get("user_query", "")}]
                },
                "metadata": {
                    "health_label": request.get("payload", {}).get("health_label", ""),
                    "diet_notes": request.get("payload", {}).get("diet_notes", []),
                    "constraints": request.get("payload", {}).get("constraints", {}),
                    "user_profile": request.get("payload", {}).get("user_profile", {}),
                }
            }
            response = await agent_b.handle_a2a_task(task)
        else:
            raise HTTPException(status_code=400, detail="不支持的请求格式")

        print(f"[Agent B Server] A2A响应: status={response.get('status', {}).get('state', 'unknown')}")

        return response

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"A2A处理失败: {str(e)}")


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "agent_b_initialized": agent_b is not None,
        "agent_id": agent_b.agent_id if agent_b else None,
        "mcp_tools_loaded": len(agent_b.mcp_tools) > 0 if agent_b else False,
    }


@app.get("/api/agents/status")
async def agents_status():
    """Agent B 状态"""
    return {
        "agent_b": {
            "id": agent_b.agent_id if agent_b else None,
            "llm_available": agent_b.llm is not None if agent_b else False,
            "mcp_tools_count": len(agent_b.mcp_tools) if agent_b else 0,
            "tools": [t.name for t in (agent_b.mcp_tools if agent_b else [])],
        },
    }


@app.get("/api/tools")
async def list_tools():
    """获取可用MCP工具列表"""
    try:
        if not agent_b:
            raise HTTPException(status_code=503, detail="Agent B 未初始化")

        tools_info = [
            {"name": t.name, "description": t.description}
            for t in agent_b.mcp_tools
        ]
        return {"success": True, "tools": tools_info, "total": len(tools_info)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取工具列表失败: {str(e)}")


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "agent_b_server:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info",
    )