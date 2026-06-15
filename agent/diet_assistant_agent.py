"""
Agent B: 健康饮食助手Agent (agent_diet_assistant)
职责：
1. 食谱查询：按名称搜索食谱 → 返回完整营养详情（api_server直接调用）
2. 配餐：接收饮食规则 → 调用MCP食谱工具 → 生成一日三餐方案（通过A2A）
3. 所有食谱数据来源于 MCP 工具 (MySQL)，禁止自行编造
"""
import json
import os
import sys
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

try:
    from langchain_community.chat_models import ChatTongyi as Tongyi
    QWEN_AVAILABLE = True
except ImportError:
    try:
        from langchain_community.chat_models.tongyi import Tongyi
        QWEN_AVAILABLE = True
    except ImportError:
        QWEN_AVAILABLE = False

from config.settings import settings
from agent.a2a_official_sdk import (
    create_agent_b_card,
    create_user_message,
    create_agent_message,
    create_task,
    update_task_status,
    add_artifact,
    is_task_completed,
)
from a2a.types import TaskState
from agent.meal_planner import MealPlanner


class DietAssistantAgent:
    """Agent B: 健康饮食助手Agent"""

    def __init__(self):
        self.agent_id = settings.A2A_AGENT_B_ID
        self.llm = None
        self.mcp_tools = []
        self.agent_chain = None

    async def initialize(self):
        """初始化 Agent B"""
        print(f"[Agent B] 初始化饮食助手Agent: {self.agent_id}")
        self._init_llm()
        await self._load_mcp_tools()
        if self.mcp_tools:
            self._create_agent_chain()

    def _init_llm(self):
        """初始化LLM"""
        if not QWEN_AVAILABLE:
            print("[Agent B] 通义千问不可用，将使用纯工具模式")
            return
        if not settings.DASHSCOPE_API_KEY:
            print("[Agent B] 未配置DASHSCOPE_API_KEY")
            return

        self.llm = Tongyi(
            model=settings.QWEN_MODEL,
            dashscope_api_key=settings.DASHSCOPE_API_KEY,
            temperature=0.7,
            base_url="https://dashscope.aliyuncs.com/api/v1",
        )
        print(f"[Agent B] LLM: {settings.QWEN_MODEL}")

    async def _load_mcp_tools(self):
        """
        加载MCP工具 (recipe_db_server)
        
        支持两种模式：
        - Streamable HTTP 模式：MCP_SERVER_URL 非空时，连接远程 MCP Server
        - stdio 模式：默认，作为子进程启动 MCP Server
        """
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError:
            print("[Agent B] 未安装 langchain-mcp-adapters")
            self.mcp_tools = []
            return

        try:
            if settings.MCP_SERVER_URL:
                # Streamable HTTP 模式：连接远程 MCP Server
                mcp_url = settings.MCP_SERVER_URL
                print(f"[Agent B] MCP 连接模式: Streamable HTTP ({mcp_url})")
                client = MultiServerMCPClient({
                    "recipe_db": {
                        "url": mcp_url,
                        "transport": "streamable_http",
                    },
                })
            else:
                # stdio 模式：作为子进程启动
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                python_executable = sys.executable
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                print(f"[Agent B] MCP 连接模式: stdio (子进程)")
                client = MultiServerMCPClient({
                    "recipe_db": {
                        "command": python_executable,
                        "args": [os.path.join(project_root, "mcp_servers", "recipe_db_server.py")],
                        "transport": "stdio",
                        "env": env,
                    },
                })

            self.mcp_tools = await client.get_tools()
            if self.mcp_tools:
                print(f"[Agent B] 加载 {len(self.mcp_tools)} 个MCP工具:")
                for tool in self.mcp_tools:
                    print(f"   - {tool.name}: {tool.description[:60]}...")
            else:
                print("[Agent B] 未加载到任何工具")

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[Agent B] MCP工具加载失败: {e}")
            self.mcp_tools = []

    def _create_agent_chain(self):
        """创建LLM链"""
        if not self.llm or not self.mcp_tools:
            return

        tools_desc = "\n".join(
            f"- {tool.name}: {tool.description}" for tool in self.mcp_tools
        )

        system_prompt = f"""你是【健康饮食助手Agent】，负责根据饮食规则筛选食谱并生成饮食方案。

可用MCP工具：
{tools_desc}

工作流程：
1. 解析A2A消息中的饮食约束和禁忌
2. 根据约束调用MCP食谱工具完成筛选、营养分析
3. 结合规则生成最终饮食方案
4. 所有食谱数据、营养判断均依赖MCP工具，禁止自行编造数据

回答要求：
- 专业但易懂
- 给出具体数据和单位
- 关注营养合规性"""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}"),
        ])
        self.agent_chain = prompt | self.llm | StrOutputParser()
        print("[Agent B] Agent链创建成功")

    def _get_tool(self, tool_name: str):
        """获取指定名称的MCP工具"""
        return next((t for t in self.mcp_tools if t.name == tool_name), None)

    def _extract_tool_result(self, result) -> str:
        """提取工具返回结果"""
        try:
            if isinstance(result, list) and len(result) > 0:
                result_text = result[0].text if hasattr(result[0], "text") else json.dumps(result[0])
            elif isinstance(result, dict):
                result_text = json.dumps(result)
            else:
                result_text = str(result)

            data = json.loads(result_text)
            if isinstance(data, dict) and "text" in data:
                data = json.loads(data["text"])
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"工具执行错误: {str(e)}"

    async def classify_intent(self, user_query: str) -> str:
        """
        用 LLM 判断用户意图: 'recipe_query' | 'meal_plan'
        - recipe_query: 查询特定食谱的营养、食材、做法等
        - meal_plan: 要求生成一日三餐/单餐配餐方案
        """
        if not self.llm:
            return "meal_plan"

        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "你是意图分类器，只需输出一个词。\n"
                "规则：\n"
                "- 用户想查某个菜/食谱的营养、热量、成分、做法 → 输出 recipe_query\n"
                "- 用户想让你推荐、配餐、制定一日三餐、饮食方案 → 输出 meal_plan\n"
                "只输出 recipe_query 或 meal_plan，不要输出其他内容。"
            )),
            ("human", "{input}"),
        ])
        try:
            chain = prompt | self.llm | StrOutputParser()
            result = await chain.ainvoke({"input": user_query})
            result = result.strip().lower()
            if "recipe_query" in result:
                intent = "recipe_query"
            elif "meal_plan" in result:
                intent = "meal_plan"
            else:
                intent = "meal_plan"
            print(f"[Agent B] LLM意图分类: {intent}")
            return intent
        except Exception as e:
            print(f"[Agent B] LLM意图分类失败，默认 meal_plan: {e}")
            return "meal_plan"

    async def _extract_recipe_keyword(self, user_query: str) -> str:
        """用 LLM 从用户提问中提取食谱名称关键词"""
        if not self.llm:
            # LLM不可用时简单去除常见停用词
            for sw in ["查一下", "查一查", "查询", "搜索", "营养成分",
                       "热量", "成分", "卡路里", "含量", "多少",
                       "是什么", "怎么样", "有什么"]:
                user_query = user_query.replace(sw, "")
            return user_query.strip()

        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system", (
                    "从用户提问中提取食谱/菜品名称关键词，用于搜索食谱数据库。\n"
                    "只输出食谱名称，不要输出其他内容。"
                    "例如：“查一下宫保鸡丁的热量” → “宫保鸡丁”"
                )),
                ("human", "{input}"),
            ])
            chain = prompt | self.llm | StrOutputParser()
            keyword = await chain.ainvoke({"input": user_query})
            return keyword.strip()
        except Exception as e:
            print(f"[Agent B] LLM提取关键词失败: {e}")
            return user_query.strip()

    async def handle_meal_plan(
        self, user_query: str, user_profile: dict,
        health_label: str, diet_notes: list, constraints: dict
    ) -> dict:
        """
        配餐编排公开接口（供 api_server 直接调用，无需A2A包装）
        生成一日三餐方案，返回结构化数据
        """
        print(f"[Agent B] 配餐请求: health_label={health_label}, "
              f"diet_notes={len(diet_notes)}条")

        meal_plan = await self._generate_full_day_meal_plan(
            user_profile=user_profile,
            health_condition=health_label,
            diet_notes=diet_notes,
            constraints=constraints
        )

        if not meal_plan:
            return {
                "summary": "无法生成合适的配餐方案",
                "meal_plan": None,
                "milvus_used": False,
            }

        # 营养合规性分析
        nutrition_analysis = await self._analyze_nutrition_compliance(
            meal_plan, health_label
        )

        # LLM结构化解读
        llm_analysis = await self._explain_meal_plan_with_llm(
            user_profile=user_profile,
            health_condition=health_label,
            diet_notes=diet_notes,
            meal_plan=meal_plan
        )

        # 从结构化解读中提取摘要（向下兼容）
        summary = ""
        if llm_analysis and isinstance(llm_analysis, dict):
            summary = llm_analysis.get("evaluation", "")

        return {
            "summary": summary or "已为您生成一日三餐配餐方案",
            "meal_plan": meal_plan,
            "milvus_used": bool(diet_notes),
            "nutrition_analysis": nutrition_analysis,
            "llm_analysis": llm_analysis,
            "diet_notes": diet_notes,
        }

    async def handle_recipe_query(self, user_query: str) -> str:
        """
        食谱查询公开接口（供 api_server 直接调用，无需A2A包装）
        返回: 格式化的营养详情文本
        """
        # 用 LLM 提取食谱名称关键词
        keyword = await self._extract_recipe_keyword(user_query)
        if not keyword:
            return "请告诉我您想查询的食谱名称，例如：番茄炒蛋的营养成分"

        print(f"[Agent B] 食谱查询关键词(LLM): '{keyword}'")

        # 1. 按名称搜索食谱
        search_tool = self._get_tool("search_recipe_by_name")
        if not search_tool:
            return "食谱搜索工具不可用，请检查MCP服务状态"

        result = await search_tool.ainvoke({"keyword": keyword, "limit": 5})
        result_text = self._extract_tool_result(result)
        search_data = json.loads(result_text)
        recipes = search_data.get("recipes", [])

        if not recipes:
            return f"未找到与“{keyword}”相关的食谱，请尝试其他关键词。"

        # 2. 获取完整营养详情
        nutrition_tool = self._get_tool("get_recipe_nutrition")
        detailed_recipes = []
        for recipe in recipes:
            rid = recipe.get("recipe_id", "")
            if nutrition_tool and rid:
                detail_result = await nutrition_tool.ainvoke({"recipe_id": rid})
                detail_text = self._extract_tool_result(detail_result)
                detail_data = json.loads(detail_text)
                if "error" not in detail_data:
                    detailed_recipes.append(detail_data)
                else:
                    detailed_recipes.append(recipe)
            else:
                detailed_recipes.append(recipe)

        # 3. 构建结构化数据
        recipes_data = []
        for rd in detailed_recipes:
            recipe_info = {
                "name": rd.get("recipe_name", "未知"),
                "ingredients": rd.get("ingredients", ""),
                "nutrients": {},
            }
            nutrients_list = rd.get("nutrients", [])
            if isinstance(nutrients_list, list):
                for n in nutrients_list:
                    label = n.get("label", "")
                    val = n.get("value")
                    unit = n.get("unit", "")
                    if val is not None and label:
                        recipe_info["nutrients"][label] = f"{val} {unit}"
            elif isinstance(nutrients_list, dict):
                for key, info in nutrients_list.items():
                    if isinstance(info, dict):
                        label = info.get("label", key)
                        val = info.get("value")
                        unit = info.get("unit", "")
                        if val is not None:
                            recipe_info["nutrients"][label] = f"{val} {unit}"
            recipes_data.append(recipe_info)

        # 4. 用 LLM 生成自然语言回答
        if self.llm:
            try:
                data_text = json.dumps(recipes_data, ensure_ascii=False, indent=2)
                prompt = ChatPromptTemplate.from_messages([
                    ("system", (
                        "你是一个专业的营养顾问。根据用户的提问和查询到的食谱数据，生成简洁、有针对性的回答。\n"
                        "规则：\n"
                        "1. 只展示与用户提问相关的营养信息（如问“热量”就重点说能量/卡路里，问“营养成分”才全面列举）\n"
                        "2. 对关键数据做简短分析或对比（如高低评价、同类比较）\n"
                        "3. 用自然语言表述，不要简单罗列数据\n"
                        "4. 如果有多个食谱，可以给出简短的推荐或比较\n"
                        "5. 回答控制在300字以内"
                    )),
                    ("human", "用户提问：{query}\n\n查询到的食谱数据：\n{data}"),
                ])
                chain = prompt | self.llm | StrOutputParser()
                answer = await chain.ainvoke({
                    "query": user_query,
                    "data": data_text,
                })
                print(f"[Agent B] LLM生成食谱回答，长度: {len(answer)}")
                return answer
            except Exception as e:
                print(f"[Agent B] LLM生成回答失败，降级为原始数据: {e}")

        # 5. LLM不可用时降级：只展示核心营养素
        parts = [f"找到 {len(recipes)} 个与“{keyword}”相关的食谱：\n"]
        core_nutrients = {"能量", "蛋白质", "脂肪", "碳水化合物", "钠"}
        for rd in recipes_data:
            parts.append(f"【{rd['name']}】")
            if rd["ingredients"]:
                parts.append(f"  食材：{rd['ingredients'][:150]}")
            for label, val_unit in rd["nutrients"].items():
                if label in core_nutrients:
                    parts.append(f"  {label}: {val_unit}")
            parts.append("")
        return "\n".join(parts)

    async def handle_a2a_task(self, task: dict) -> dict:
        """
        处理来自 A2A 协议的任务请求（使用官方 SDK）
        返回: A2A Task 响应 (dict)
        """
        task_id = task.get("id")
        context_id = task.get("context_id")
        message = task.get("message", {})
        
        # 提取用户消息
        user_query = ""
        parts = message.get("parts", [])
        for part in parts:
            if "text" in part:
                user_query = part["text"]
                break
        
        # 从任务元数据中提取约束信息
        metadata = task.get("metadata", {})
        health_label = metadata.get("health_label", "")
        diet_notes = metadata.get("diet_notes", [])
        constraints = metadata.get("constraints", {})
        user_profile = metadata.get("user_profile", {})
        
        print(f"[Agent B] A2A任务: query={user_query}, label={health_label}")
        
        try:
            # 初始化状态字段（如果不存在）
            if "status" not in task:
                task["status"] = {"state": TaskState.TASK_STATE_SUBMITTED}
            
            # 更新任务状态为 WORKING
            task["status"]["state"] = TaskState.TASK_STATE_WORKING
            
            if metadata.get("task_type") == "recipe_query":
                # 食谱查询
                result_text = await self.handle_recipe_query(user_query)
                result_data = {"response": result_text}
            else:
                # 配餐请求 (diet_recommend)
                result_data = await self._handle_meal_plan_a2a(
                    user_profile, health_label, diet_notes, constraints
                )
                if result_data is None:
                    task["status"]["state"] = TaskState.TASK_STATE_FAILED
                    return task

            # 更新任务状态为 COMPLETED
            task["status"]["state"] = TaskState.TASK_STATE_COMPLETED
            
            # 添加产出物
            artifact = {
                "name": "result",
                "parts": [{"data": result_data}]
            }
            task.setdefault("artifacts", []).append(artifact)
            
            return task

        except Exception as e:
            import traceback
            traceback.print_exc()
            task["status"]["state"] = TaskState.TASK_STATE_FAILED
            task["status"]["message"] = f"处理失败: {str(e)}"
            return task

    async def _handle_meal_plan_a2a(
        self, user_profile: dict, health_label: str, diet_notes: list, constraints: dict
    ) -> Optional[dict]:
        """处理配餐意图：生成一日三餐方案"""
        meal_plan = await self._generate_full_day_meal_plan(
            user_profile=user_profile,
            health_condition=health_label,
            diet_notes=diet_notes,
            constraints=constraints
        )
        
        if not meal_plan:
            return None

        # 营养合规性分析
        nutrition_analysis = await self._analyze_nutrition_compliance(
            meal_plan, health_label
        )
        
        # 用LLM生成专业解读（结构化）
        llm_analysis = await self._explain_meal_plan_with_llm(
            user_profile=user_profile,
            health_condition=health_label,
            diet_notes=diet_notes,
            meal_plan=meal_plan
        )
        
        # 从结构化解读中提取摘要（向下兼容）
        summary = ""
        if llm_analysis and isinstance(llm_analysis, dict):
            summary = llm_analysis.get("evaluation", "")
        
        return {
            "summary": summary or "已为您生成一日三餐配餐方案",
            "meal_plan": meal_plan,
            "milvus_used": bool(diet_notes),
            "nutrition_analysis": nutrition_analysis,
            "llm_analysis": llm_analysis,
            "diet_notes": diet_notes,
        }

    async def _analyze_nutrition_compliance(
        self, meal_plan: dict, health_label: str
    ) -> Optional[dict]:
        """
        调用 analyze_recipe_nutrition 工具对一日三餐做营养合规性分析
        返回: {total, compliant_count, non_compliant_count, analysis, warnings, summary}
        """
        tool = self._get_tool("analyze_recipe_nutrition")
        if not tool:
            return None

        # 收集所有食谱ID
        recipe_ids = []
        for meal_key in ["breakfast", "lunch", "dinner"]:
            meal_data = meal_plan.get(meal_key, {})
            for recipe in meal_data.get("recipes", []):
                rid = recipe.get("recipe_id")
                if rid:
                    recipe_ids.append(rid)

        if not recipe_ids:
            return None

        # 根据健康标签构建约束
        constraint_map = {
            "高血压": {"max_sodium": 500, "max_fat": 15},
            "高脂血症": {"max_sodium": 600, "max_fat": 10, "max_calorie": 200},
            "糖尿病": {"max_carbohydrate": 20, "max_calorie": 250},
            "高尿酸血症_痛风": {"max_calorie": 250},
            "肥胖": {"max_calorie": 150, "max_fat": 10},
            "慢性肾脏病": {"max_protein": 12, "max_sodium": 400, "max_potassium": 300},
        }
        constraints = constraint_map.get(health_label, {})

        try:
            args = {"recipe_ids": recipe_ids}
            if constraints:
                args["constraints"] = constraints

            result = await tool.ainvoke(args)
            result_text = self._extract_tool_result(result)
            analysis = json.loads(result_text)
            print(f"[Agent B] 营养分析: {analysis.get('compliant_count', 0)}/"
                  f"{analysis.get('total', 0)}个食谱合规")
            return analysis

        except Exception as e:
            print(f"[Agent B] 营养合规性分析失败: {e}")
            return None

    async def _filter_recipes_by_constraints(
        self, constraints: dict, health_label: str
    ) -> dict:
        """根据约束条件调用filter_recipes工具（支持meal_type按餐次筛选）"""
        # 构建filter_recipes参数
        filter_args = {}
        # 餐次筛选（优先透传）
        if "meal_type" in constraints:
            filter_args["meal_type"] = constraints["meal_type"]
        if "max_calorie" in constraints:
            filter_args["max_calorie"] = constraints["max_calorie"]
        if "max_fat" in constraints:
            filter_args["max_fat"] = constraints["max_fat"]
        if "max_sodium" in constraints:
            filter_args["max_sodium"] = constraints["max_sodium"]
        if "max_carbohydrate" in constraints:
            filter_args["max_carbohydrate"] = constraints["max_carbohydrate"]
        if "max_protein" in constraints:
            filter_args["max_protein"] = constraints["max_protein"]
        if "max_potassium" in constraints:
            filter_args["max_potassium"] = constraints["max_potassium"]
        if "min_iron" in constraints:
            filter_args["min_iron"] = constraints["min_iron"]
        if "exclude_ingredients" in constraints:
            filter_args["exclude_ingredients"] = constraints["exclude_ingredients"]
        filter_args["limit"] = constraints.get("limit", 20)

        # 如果有健康标签但没有具体约束，使用健康标签对应的默认策略
        if health_label and health_label not in ["通用", ""] and not filter_args:
            health_constraints = {
                "高血压": {"max_sodium": 500},
                "高脂血症": {"max_fat": 8, "max_calorie": 150},
                "糖尿病": {"max_carbohydrate": 15, "max_calorie": 200},
                "肥胖": {"max_calorie": 120, "max_fat": 8},
                "高尿酸血症_痛风": {"max_calorie": 200},
            }
            filter_args.update(health_constraints.get(health_label, {"max_calorie": 300}))

        # 如果仍然没有约束，给一个宽松的默认
        if not filter_args or (len(filter_args) == 1 and "limit" in filter_args):
            filter_args["max_calorie"] = 500

        # 使用filter_recipes工具（带具体约束，每餐参数不同→结果不同）
        tool = self._get_tool("filter_recipes")
        if tool:
            print(f"[Agent B] 调用 filter_recipes: {filter_args}")
            result = await tool.ainvoke(filter_args)
            result_text = self._extract_tool_result(result)
            print(f"[Agent B] filter_recipes返回: {result_text[:300]}...")
            data = json.loads(result_text)
            return data

        return {"recipes": []}

    async def _generate_full_day_meal_plan(
        self,
        user_profile: dict,
        health_condition: str,
        diet_notes: list,
        constraints: dict
    ) -> Optional[dict]:
        """
        生成完整的一日三餐配餐方案
        
        Returns:
            {
                "breakfast": {"recipes": [...], "total_nutrition": {...}},
                "lunch": {...},
                "dinner": {...},
                "daily_total": {...}
            }
        """
        print(f"[Agent B] 开始生成一日三餐配餐方案...")
        
        # 1. 计算每日营养需求
        daily_nutrition = MealPlanner.calculate_daily_nutrition(
            user_profile, health_condition
        )
        print(f"[Agent B] 每日营养目标: {daily_nutrition}")
        
        # 2. 分配三餐目标
        meal_targets = MealPlanner.allocate_meal_targets(daily_nutrition)
        print(f"[Agent B] 三餐目标: 早餐{meal_targets['breakfast'].get('calorie')}kcal, "
              f"午餐{meal_targets['lunch'].get('calorie')}kcal, "
              f"晚餐{meal_targets['dinner'].get('calorie')}kcal")
        
        # 3. 为每餐查找食谱（早中晚餐食谱池已按meal_type分类，天然不重叠）
        meals = {}
        
        for meal_type in ["breakfast", "lunch", "dinner"]:
            meal_target = meal_targets[meal_type]
            
            # 选择最优组合(每餐3-4个食谱)
            num_recipes = 3 if meal_type == "breakfast" else 4
            
            # 构建约束，传入num_recipes以收紧max_calorie
            search_constraints = MealPlanner.build_search_constraints(meal_target, meal_type, num_recipes)
            search_constraints["limit"] = 50
            
            print(f"[Agent B] 查找{meal_type}食谱, 约束: {search_constraints}")
            
            # 调用MCP工具获取候选食谱
            candidates_result = await self._filter_recipes_by_constraints(
                search_constraints, health_condition
            )
            candidates = candidates_result.get("recipes", [])
            print(f"[Agent B] {meal_type}候选{len(candidates)}个")
            
            selected_recipes = await MealPlanner.select_recipes_for_meal(
                candidates=candidates,
                meal_target=meal_target,
                num_recipes=num_recipes,
                llm_chain=self.llm,  # 直接传递LLM对象,而非agent_chain
                health_condition=health_condition
            )
            
            meals[meal_type] = selected_recipes
            print(f"[Agent B] {meal_type}选中{len(selected_recipes)}个食谱")
        
        # 4. 计算总营养
        daily_total = MealPlanner.calculate_total_nutrition(meals)
        
        # 5. 构建返回数据
        meal_plan = {
            "breakfast": {
                "recipes": meals["breakfast"],
                "target": meal_targets["breakfast"],
            },
            "lunch": {
                "recipes": meals["lunch"],
                "target": meal_targets["lunch"],
            },
            "dinner": {
                "recipes": meals["dinner"],
                "target": meal_targets["dinner"],
            },
            "daily_total": daily_total,
            "daily_target": daily_nutrition,
        }
        
        return meal_plan
    
    async def _explain_meal_plan_with_llm(
        self,
        user_profile: dict,
        health_condition: str,
        diet_notes: list,
        meal_plan: dict
    ) -> Optional[dict]:
        """用LLM生成配餐方案的专业解读（结构化JSON）"""
        if not self.agent_chain:
            return None
        
        try:
            prompt = MealPlanner.generate_llm_prompt(
                user_profile=user_profile,
                health_condition=health_condition,
                diet_notes=diet_notes,
                meals={
                    "breakfast": meal_plan["breakfast"]["recipes"],
                    "lunch": meal_plan["lunch"]["recipes"],
                    "dinner": meal_plan["dinner"]["recipes"],
                },
                daily_target=meal_plan["daily_target"],
                actual_total=meal_plan["daily_total"],
            )
            
            response = await self.agent_chain.ainvoke({"input": prompt})
            response_text = response.strip() if response else ""
            
            if not response_text:
                return None
            
            # 解析JSON（兼容markdown格式包裹）
            text = response_text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].strip()
            # 提取JSON对象
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                text = text[start:end+1]
            
            analysis = json.loads(text)
            print(f"[Agent B] LLM结构化解读成功: {len(analysis.get('cooking_advice', []))}条烹饪建议, "
                  f"{len(analysis.get('nutrition_gaps', []))}个营养缺口")
            return analysis
            
        except json.JSONDecodeError as e:
            print(f"[Agent B] LLM解读JSON解析失败: {e}, 响应前200字: {response_text[:200]}")
            return None
        except Exception as e:
            print(f"[Agent B] LLM解读失败: {e}")
            return None