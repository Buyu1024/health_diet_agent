"""
FastAPI 接口服务
意图路由：食谱查询 → Agent B（直接）| 配餐请求 → Agent B 编排（按需调 Agent A Milvus）
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from contextlib import asynccontextmanager
import os
import json
import uuid

from config.settings import settings
from agent.rule_search_agent import RuleSearchAgent, identify_health_label
from agent.diet_assistant_agent import DietAssistantAgent
from agent.profile_manager import UserProfile, ProfileParser
from agent.llm_profile_parser import LLMProfileParser


# ==================== 数据模型 ====================

class ChatRequest(BaseModel):
    """聊天请求"""
    message: str = Field(..., description="用户消息，如'我有高血压，推荐一日三餐食谱'")
    session_id: Optional[str] = Field(None, description="会话ID")
    intent: Optional[str] = Field(
        None,
        description="用户选择的意图: 'meal_plan'(配餐推荐) | 'recipe_query'(食谱查询)。"
                    "为空时自动通过关键词识别"
    )


class ChatResponse(BaseModel):
    """聊天响应"""
    response: str
    session_id: str
    a2a_trace: Optional[dict] = Field(None, description="A2A消息链路追踪")


class RecipeFilterRequest(BaseModel):
    """食谱筛选请求"""
    max_calorie: Optional[float] = None
    max_fat: Optional[float] = None
    max_sodium: Optional[float] = None
    max_carbohydrate: Optional[float] = None
    exclude_ingredients: Optional[List[str]] = []
    health_label: Optional[str] = ""
    limit: int = 10


# ==================== FastAPI 应用 ====================

agent_a: Optional[RuleSearchAgent] = None
agent_b: Optional[DietAssistantAgent] = None
# 会话级用户指标存储 {session_id: UserProfile}
_session_profiles: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    global agent_a, agent_b

    print("=" * 60)
    print("[INFO] 初始化双Agent架构...")
    print("=" * 60)

    # 初始化 Agent A
    agent_a = RuleSearchAgent()
    await agent_a.initialize()

    if settings.A2A_MODE_ENABLED:
        # A2A分布式模式：Agent B 运行在独立服务上，不本地初始化
        print(f"\n[OK] A2A分布式模式")
        print(f"  Agent A: {agent_a.agent_id}")
        print(f"  Agent B: 远程服务 ({settings.A2A_AGENT_B_URL})")
        print(f"  通信模式: A2A分布式 ({settings.A2A_AGENT_B_URL})")
    else:
        # 同进程直连模式：本地初始化 Agent B
        agent_b = DietAssistantAgent()
        await agent_b.initialize()

        if not agent_b.mcp_tools:
            print("[WARN] Agent B 未加载到MCP工具，部分功能不可用")

        print(f"\n[OK] 双Agent架构初始化完成")
        print(f"  Agent A: {agent_a.agent_id}")
        print(f"  Agent B: {agent_b.agent_id}")
        print(f"  通信模式: 同进程直连")
    print("=" * 60 + "\n")

    yield

    print("[INFO] 关闭双Agent...")


app = FastAPI(
    title="Health Diet Agent API",
    description="Agent B 编排 + 按需 Milvus 检索 + MCP 工具",
    version="3.0.0",
    lifespan=lifespan,
)

# 配置 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有请求头
)


# ==================== 核心路由 ====================


async def _classify_intent(user_input: str) -> str:
    """用 LLM 识别用户意图，Agent不可用时使用关键词回退"""
    if agent_b:
        return await agent_b.classify_intent(user_input)
    # 关键词回退（A2A模式下 agent_b 不在本地）
    query_keywords = ["查一下", "查询", "搜索", "营养成分", "热量",
                      "卡路里", "成分", "多少卡", "含量"]
    if any(kw in user_input for kw in query_keywords):
        return "recipe_query"
    return "meal_plan"


def _format_meal_plan_response(result: dict, milvus_used: bool, profile: dict) -> str:
    """将 Agent B 返回的配餐数据格式化为可读文本"""
    parts = []
    # 当llm_analysis存在时，evaluation会在结构化部分展示，跳过纯文本summary
    llm_analysis = result.get("llm_analysis")
    summary = result.get("summary", "")
    if summary and not llm_analysis:
        parts.append(summary)

    meal_plan = result.get("meal_plan")
    if meal_plan:
        meal_labels = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐"}
        for meal_key, meal_label in meal_labels.items():
            meal_data = meal_plan.get(meal_key, {})
            meal_recipes = meal_data.get("recipes", [])
            target = meal_data.get("target", {})

            if meal_recipes:
                meal_cal = sum(
                    r.get("nutrients", {}).get("calorie", {}).get("value", 0) or 0
                    for r in meal_recipes
                )
                target_cal = target.get("calorie", 0)
                parts.append(f"\n【{meal_label}】(目标{target_cal}kcal，实际{round(meal_cal, 1)}kcal)")

                for r in meal_recipes:
                    n = r.get("nutrients", {})
                    cal = n.get("calorie", {})
                    pro = n.get("protein", {})
                    fat = n.get("fat", {})
                    carb = n.get("carbohydrate", {})
                    sod = n.get("sodium", {})
                    parts.append(
                        f"  - {r.get('recipe_name', '未知')}"
                        f"  | 热量: {cal.get('value', 'N/A')}{cal.get('unit', '')}"
                        f"  | 蛋白质: {pro.get('value', 'N/A')}g"
                        f"  | 脂肪: {fat.get('value', 'N/A')}g"
                        f"  | 碳水: {carb.get('value', 'N/A')}g"
                        f"  | 钠: {sod.get('value', 'N/A')}mg"
                    )

        daily_total = meal_plan.get("daily_total", {})
        daily_target = meal_plan.get("daily_target", {})
        if daily_total:
            parts.append(f"\n【全天总计】")
            parts.append(f"  热量: {daily_total.get('calorie', 0)}kcal (目标{daily_target.get('calorie', 0)}kcal)")
            parts.append(f"  蛋白质: {daily_total.get('protein', 0)}g (目标{daily_target.get('protein', 0)}g)")
            parts.append(f"  脂肪: {daily_total.get('fat', 0)}g (目标{daily_target.get('fat', 0)}g)")
            parts.append(f"  碳水: {daily_total.get('carbohydrate', 0)}g (目标{daily_target.get('carbohydrate', 0)}g)")
            parts.append(f"  钠: {daily_total.get('sodium', 0)}mg")

    # 营养合规性分析结果
    nutrition_analysis = result.get("nutrition_analysis")
    if nutrition_analysis:
        total = nutrition_analysis.get("total", 0)
        compliant = nutrition_analysis.get("compliant_count", 0)
        non_compliant = nutrition_analysis.get("non_compliant_count", 0)

        if non_compliant > 0:
            parts.append(f"\n⚠️ 【营养合规性检查】{compliant}/{total}个食谱符合约束")
            analysis_list = nutrition_analysis.get("analysis", [])
            for item in analysis_list:
                if not item.get("compliant", True):
                    name = item.get("recipe_name", "未知")
                    issues = item.get("issues", [])
                    for issue in issues:
                        parts.append(f"  ⚠ {name}: {issue}")
        else:
            parts.append(f"\n✅ 【营养合规性检查】全部{total}个食谱均符合约束")

        tool_warnings = nutrition_analysis.get("warnings", [])
        if tool_warnings:
            for w in tool_warnings:
                parts.append(f"  ⚠ {w}")

    # LLM结构化专业解读（变量已在顶部提取）
    if llm_analysis and isinstance(llm_analysis, dict):
        # 整体评价
        evaluation = llm_analysis.get("evaluation", "")
        if evaluation:
            parts.append(f"\n📝 【整体评价】{evaluation}")

        # 专业食用建议
        cooking_advice = llm_analysis.get("cooking_advice", [])
        if cooking_advice:
            parts.append("\n💡 【专业食用建议】")
            for item in cooking_advice:
                category = item.get("category", "")
                suggestions = item.get("suggestions", [])
                basis = item.get("scientific_basis", "")
                parts.append(f"\n  ◆ {category}")
                for sug in suggestions:
                    parts.append(f"    - {sug}")
                if basis:
                    parts.append(f"    🧬 依据：{basis}")

        # 营养不达标项
        nutrition_gaps = llm_analysis.get("nutrition_gaps", [])
        if nutrition_gaps:
            parts.append("\n⚠️ 【营养不达标项及补充建议】")
            for gap in nutrition_gaps:
                nutrient = gap.get("nutrient", "")
                gap_desc = gap.get("gap_description", "")
                supplement = gap.get("supplement", "")
                effect = gap.get("expected_effect", "")
                parts.append(f"\n  ◆ {nutrient}（{gap_desc}）")
                if supplement:
                    parts.append(f"    补充：{supplement}")
                if effect:
                    parts.append(f"    预期：{effect}")

    text = "\n".join(parts)

    if not milvus_used:
        text += "\n\n⚠️ 注：本次回复未参考Milvus饮食规则库（检索未命中），以上建议基于通用饮食指南，仅供参考。"

    # 追加用户指标
    if profile:
        bmi = profile.get("bmi", "N/A")
        daily_cal = profile.get("daily_calories", "N/A")
        if bmi and bmi != "N/A":
            text += f"\n\n📊 您的个人指标：BMI {bmi}，每日建议摄入 {daily_cal} kcal"

    return text


@app.get("/", response_class=HTMLResponse)
async def root():
    """根路径 - 提供 Web 前端页面"""
    frontend_path = os.path.join(os.path.dirname(__file__), "web", "index.html")
    if os.path.exists(frontend_path):
        with open(frontend_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>前端页面未找到</h1>")


@app.get("/.well-known/agent.json")
async def get_agent_card():
    """获取 AgentCard - A2A 协议标准端点"""
    from agent.a2a_official_sdk import create_agent_b_card
    from google.protobuf.json_format import MessageToDict
    
    card = create_agent_b_card()
    return MessageToDict(card)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    智能对话接口

    路由逻辑:
    - 食谱查询 → 直接调用 Agent B
    - 配餐请求 → 健康标签检测 → 按需调Agent A(Milvus) → Agent B配餐
    """
    try:
        if not agent_b and not settings.A2A_MODE_ENABLED:
            raise HTTPException(status_code=503, detail="Agent未初始化")

        session_id = request.session_id or str(uuid.uuid4())
        request.session_id = session_id

        # === 意图识别（优先用户显式选择，否则LLM自动分类）===
        if request.intent:
            intent = request.intent
            intent_source = "用户选择"
        else:
            intent = await _classify_intent(request.message)
            intent_source = "LLM分类"
        print(f"[API] 意图: {intent} (来源: {intent_source}) | 输入: {request.message}")

        # === 食谱查询：直接调用 Agent B 或通过 A2A ===
        if intent == "recipe_query":
            if settings.A2A_MODE_ENABLED and agent_a:
                summary = await agent_a.send_recipe_query(request.message)
                if summary is None:
                    raise HTTPException(status_code=502, detail="A2A请求失败，Agent B 不可达")
            elif agent_b:
                summary = await agent_b.handle_recipe_query(request.message)
            else:
                raise HTTPException(status_code=503, detail="Agent B 未初始化")
            return ChatResponse(
                response=summary,
                session_id=session_id,
                a2a_trace={
                    "intent": "recipe_query",
                    "route": "a2a" if settings.A2A_MODE_ENABLED else "direct_agent_b",
                },
            )

        # === 配餐请求 ===

        # 1. Profile 管理
        profile = _session_profiles.get(session_id, UserProfile())
        extracted = LLMProfileParser.parse(request.message)
        profile = ProfileParser.update_profile(profile, extracted)

        missing_fields = profile.get_missing_fields()
        if missing_fields:
            prompt = (
                f"为了给您提供更精准的个性化饮食建议，我还需要了解以下信息：\n\n"
                + "\n".join([f"• {f['label']}（{f['unit']}）" for f in missing_fields])
                + '\n\n请告诉我这些信息，例如："身高170cm，体重65kg，25岁，男"'
            )
            return ChatResponse(
                response=prompt,
                session_id=session_id,
                a2a_trace={
                    "need_more_info": True,
                    "missing_fields": [
                        {"field": f["label"], "unit": f["unit"], "type": f["type"]}
                        for f in missing_fields
                    ],
                    "profile": profile.to_dict(),
                },
            )

        _session_profiles[session_id] = profile

        # 2. 健康标签检测 + 按需 Milvus 检索
        health_label = identify_health_label(request.message)
        if not health_label and profile.health_condition:
            health_label = identify_health_label(profile.health_condition)

        diet_notes = []
        milvus_used = False

        if health_label and agent_a:
            rule_data = agent_a.search_rules(request.message, health_label)
            if rule_data:
                diet_notes = rule_data.get("diet_notes", [])
                milvus_used = True
                print(f"[API] Milvus命中: {rule_data.get('health_label', '')}")
            else:
                print(f"[API] Milvus未命中，使用默认{health_label}建议")
        elif health_label:
            print(f"[API] Agent A不可用，使用默认{health_label}建议")

        if not health_label:
            health_label = "通用"
            print(f"[API] 未检测到健康标签，使用通用饮食建议")

        # 默认饮食注意（Milvus未命中或无标签时）
        if not diet_notes:
            diet_notes = ["均衡饮食，荤素搭配", "控制油盐摄入", "多吃蔬菜水果"]

        # 3. 构建 profile dict（含计算值）
        profile_dict = profile.to_dict()
        bmi = profile.calculate_bmi()
        bmr = profile.calculate_bmr()
        daily_calories = profile.calculate_daily_calories()
        if bmi is not None and bmi > 0:
            profile_dict["bmi"] = bmi
        if bmr is not None and bmr > 0:
            profile_dict["bmr"] = bmr
        if daily_calories is not None and daily_calories > 0:
            profile_dict["daily_calories"] = daily_calories

        # 4. 调用 Agent B 配餐（支持两种通信模式）
        if settings.A2A_MODE_ENABLED and agent_a:
            # A2A分布式模式：通过A2A协议发送请求给 Agent B
            result = await agent_a.send_diet_request(
                user_query=request.message,
                user_profile=profile_dict,
                health_label=health_label,
                diet_notes=diet_notes,
                constraints={},
            )
            if result is None:
                raise HTTPException(status_code=502, detail="A2A请求失败，Agent B 不可达")
        else:
            # 同进程直连模式：直接调用 Agent B
            result = await agent_b.handle_meal_plan(
                user_query=request.message,
                user_profile=profile_dict,
                health_label=health_label,
                diet_notes=diet_notes,
                constraints={},
            )

        # 5. 格式化响应
        final_response = _format_meal_plan_response(result, milvus_used, profile_dict)

        return ChatResponse(
            response=final_response,
            session_id=session_id,
            a2a_trace={
                "intent": "meal_plan",
                "health_label": health_label,
                "milvus_used": milvus_used,
                "a2a_mode": settings.A2A_MODE_ENABLED,
                "meal_plan": result.get("meal_plan"),
                "nutrition_analysis": result.get("nutrition_analysis"),
                "llm_analysis": result.get("llm_analysis"),
                "profile": profile_dict,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理请求失败: {str(e)}")


@app.post("/a2a/tasks/send")
async def a2a_receive_task(task: dict):
    """
    A2A 任务接收端点 (Agent B 侧) - 使用官方 SDK
    
    接收来自 Agent A 的 A2A Task 请求，返回处理后的 Task 响应
    用于分布式部署时 Agent A 通过 HTTP 调用 Agent B
    """
    try:
        if not agent_b:
            raise HTTPException(status_code=503, detail="Agent B 未初始化")

        response = await agent_b.handle_a2a_task(task)
        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"A2A处理失败: {str(e)}")


@app.post("/api/recipe/filter")
async def filter_recipes(request: RecipeFilterRequest):
    """
    直接筛选食谱 (绕过Agent A，直接调用Agent B的MCP工具)
    """
    try:
        if not agent_b:
            raise HTTPException(status_code=503, detail="Agent B 未初始化")

        # 有健康标签 → 用推荐工具
        if request.health_label:
            tool = agent_b._get_tool("recommend_healthy_recipes")
            if tool:
                result = await tool.ainvoke({
                    "health_label": request.health_label,
                    "limit": request.limit,
                })
                return {"success": True, "data": agent_b._extract_tool_result(result)}

        # 按约束条件筛选
        tool = agent_b._get_tool("filter_recipes")
        if tool:
            args = {}
            if request.max_calorie:
                args["max_calorie"] = request.max_calorie
            if request.max_fat:
                args["max_fat"] = request.max_fat
            if request.max_sodium:
                args["max_sodium"] = request.max_sodium
            if request.max_carbohydrate:
                args["max_carbohydrate"] = request.max_carbohydrate
            if request.exclude_ingredients:
                args["exclude_ingredients"] = request.exclude_ingredients
            args["limit"] = request.limit

            result = await tool.ainvoke(args)
            return {"success": True, "data": agent_b._extract_tool_result(result)}

        raise HTTPException(status_code=500, detail="filter_recipes工具不可用")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"筛选失败: {str(e)}")


@app.get("/api/recipe/search")
async def search_recipe(keyword: str, limit: int = 5):
    """按关键词搜索食谱"""
    try:
        if not agent_b:
            raise HTTPException(status_code=503, detail="Agent B 未初始化")

        tool = agent_b._get_tool("search_recipe_by_name")
        if not tool:
            raise HTTPException(status_code=500, detail="search_recipe_by_name工具不可用")

        result = await tool.ainvoke({"keyword": keyword, "limit": limit})
        result_text = agent_b._extract_tool_result(result)
        # 解析为结构化数据
        parsed_data = json.loads(result_text) if isinstance(result_text, str) else result_text
        return {"success": True, "data": parsed_data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@app.get("/api/recipe/{recipe_id}/nutrition")
async def get_recipe_nutrition(recipe_id: str):
    """获取食谱完整营养详情"""
    try:
        if not agent_b:
            raise HTTPException(status_code=503, detail="Agent B 未初始化")

        tool = agent_b._get_tool("get_recipe_nutrition")
        if not tool:
            raise HTTPException(status_code=500, detail="get_recipe_nutrition工具不可用")

        result = await tool.ainvoke({"recipe_id": recipe_id})
        result_text = agent_b._extract_tool_result(result)
        # 解析为结构化数据
        parsed_data = json.loads(result_text) if isinstance(result_text, str) else result_text
        return {"success": True, "data": parsed_data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


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


@app.get("/api/agents/status")
async def agents_status():
    """查看 Agent 状态"""
    return {
        "agent_a": {
            "id": agent_a.agent_id if agent_a else None,
            "milvus_available": agent_a._milvus_available if agent_a else False,
        },
        "agent_b": {
            "id": agent_b.agent_id if agent_b else settings.A2A_AGENT_B_ID,
            "mode": "remote (A2A)" if settings.A2A_MODE_ENABLED else "local",
            "url": settings.A2A_AGENT_B_URL if settings.A2A_MODE_ENABLED else None,
            "llm_available": agent_b.llm is not None if agent_b else None,
            "mcp_tools_count": len(agent_b.mcp_tools) if agent_b else None,
            "tools": [t.name for t in (agent_b.mcp_tools if agent_b else [])],
        },
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "a2a_mode": settings.A2A_MODE_ENABLED,
        "agent_a_initialized": agent_a is not None,
        "agent_b_initialized": agent_b is not None,
        "agent_b_url": settings.A2A_AGENT_B_URL if settings.A2A_MODE_ENABLED else "local",
        "mcp_tools_loaded": len(agent_b.mcp_tools) > 0 if agent_b else None,
    }


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )