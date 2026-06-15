"""
食谱营养数据库 MCP Server
从 MySQL 加载食谱营养数据，提供食谱筛选、营养分析等MCP工具
支持按餐次（早餐/午餐/晚餐）筛选食谱
"""
import asyncio
import json
import os
import sys
import re
from typing import Optional
import pymysql
from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.server.stdio

# 添加项目根目录到path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config.settings import settings

# 创建服务器实例
server = Server("recipe-database")

# ==================== 食谱数据加载 ====================

# CSV列名 → 营养素中文映射
NUTRIENT_LABELS = {
    "calorie": ("能量", "kcal"),
    "protein": ("蛋白质", "g"),
    "fat": ("脂肪", "g"),
    "carbohydrate": ("碳水化合物", "g"),
    "vitamin_a": ("维生素A", "μg RAE"),
    "vitamin_d": ("维生素D", "μg"),
    "vitamin_e": ("维生素E", "mg α-TE"),
    "vitamin_k": ("维生素K", "μg"),
    "vitamin_b1": ("维生素B1", "mg"),
    "vitamin_b2": ("维生素B2", "mg"),
    "vitamin_b6": ("维生素B6", "mg"),
    "vitamin_b12": ("维生素B12", "μg"),
    "niacin": ("烟酸", "mg"),
    "folic_acid": ("叶酸", "μg"),
    "vitamin_c": ("维生素C", "mg"),
    "biotin": ("生物素", "μg"),
    "total_choline": ("胆碱", "mg"),
    "sodium": ("钠", "mg"),
    "potassium": ("钾", "mg"),
    "magnesium": ("镁", "mg"),
    "iron": ("铁", "mg"),
    "zinc": ("锌", "mg"),
    "calcium": ("钙", "mg"),
    "phosphorus": ("磷", "mg"),
    "selenium": ("硒", "μg"),
    "iodine": ("碘", "μg"),
    "copper": ("铜", "mg"),
    "manganese": ("锰", "mg"),
}


def _parse_numeric(value_str: str) -> Optional[float]:
    """从带单位的字符串中提取数值，如 '136 kcal' → 136.0, '6.50 g' → 6.5"""
    if not value_str or value_str.strip() == "":
        return None
    match = re.match(r"([\d.]+)", value_str.strip())
    return float(match.group(1)) if match else None


def _load_recipes_from_mysql() -> list[dict]:
    """从MySQL加载食谱数据"""
    recipes = []
    try:
        conn = pymysql.connect(
            host=settings.MYSQL_HOST,
            port=settings.MYSQL_PORT,
            user=settings.MYSQL_USER,
            password=settings.MYSQL_PASSWORD,
            database=settings.MYSQL_DATABASE,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM recipes_nutrition")
            rows = cursor.fetchall()

        for row in rows:
            recipe = {
                "recipe_id": str(row.get("recipe_id", "")),
                "recipe_name": row.get("recipe_name", ""),
                "ingredients": row.get("ingredients", ""),
                "meal_type": row.get("meal_type", "") or "",  # 早餐/午餐/晚餐
            }
            # 解析所有营养素字段（确保每个字段都有值，即使为None）
            nutrients = {}
            for col_name, (label, unit) in NUTRIENT_LABELS.items():
                raw = row.get(col_name, "")
                val = _parse_numeric(raw)
                # 即使解析失败也要保留字段，设置为None
                nutrients[col_name] = {"value": val, "label": label, "unit": unit}
            recipe["nutrients"] = nutrients
            recipes.append(recipe)

        conn.close()
        print(f"[OK] 从MySQL加载 {len(recipes)} 条食谱数据", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] MySQL加载失败: {e}", file=sys.stderr)

    return recipes


# 全局食谱数据库
_recipe_db: list[dict] = _load_recipes_from_mysql()


# ==================== MCP 工具注册 ====================

@server.list_tools()
async def list_tools() -> list[Tool]:
    """列出可用工具"""
    return [
        Tool(
            name="filter_recipes",
            description=(
                "根据营养约束条件和餐次筛选食谱。"
                "支持按最大热量、最大脂肪、最大钠含量、最大碳水、"
                "最小铁含量等条件过滤，并排除含特定配料的食谱。"
                "支持按 meal_type（早餐/午餐/晚餐）筛选对应分类的食谱。"
                "返回符合条件的食谱列表及其核心营养数据。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "meal_type": {
                        "type": "string",
                        "description": "餐次类型：早餐/午餐/晚餐，仅返回该餐次的食谱",
                        "enum": ["早餐", "午餐", "晚餐"],
                    },
                    "max_calorie": {
                        "type": "number",
                        "description": "最大热量(kcal)，如200",
                    },
                    "max_fat": {
                        "type": "number",
                        "description": "最大脂肪(g)，如15",
                    },
                    "max_sodium": {
                        "type": "number",
                        "description": "最大钠含量(mg)，如2000",
                    },
                    "max_carbohydrate": {
                        "type": "number",
                        "description": "最大碳水化合物(g)，如40",
                    },
                    "max_protein": {
                        "type": "number",
                        "description": "最大蛋白质(g)",
                    },
                    "max_potassium": {
                        "type": "number",
                        "description": "最大钾含量(mg)",
                    },
                    "min_iron": {
                        "type": "number",
                        "description": "最小铁含量(mg)",
                    },
                    "exclude_ingredients": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "排除含有这些配料关键词的食谱",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量上限，默认10",
                        "default": 10,
                    },
                },
            },
        ),
        Tool(
            name="search_recipe_by_name",
            description="根据食谱名称关键词搜索食谱，返回详细营养信息",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "食谱名称关键词，如'番茄'、'排骨'、'鸡蛋'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量上限，默认5",
                        "default": 5,
                    },
                },
                "required": ["keyword"],
            },
        ),
        Tool(
            name="get_recipe_nutrition",
            description="获取指定食谱ID的完整营养详情（30种营养素）",
            inputSchema={
                "type": "object",
                "properties": {
                    "recipe_id": {
                        "type": "string",
                        "description": "食谱ID",
                    },
                },
                "required": ["recipe_id"],
            },
        ),
        Tool(
            name="analyze_recipe_nutrition",
            description="对一组食谱进行营养分析，判断是否符合给定的饮食约束，输出营养警告",
            inputSchema={
                "type": "object",
                "properties": {
                    "recipe_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "食谱ID列表",
                    },
                    "constraints": {
                        "type": "object",
                        "description": "饮食约束条件（可选），如 {max_sodium: 2000, max_fat: 30}",
                    },
                },
                "required": ["recipe_ids"],
            },
        ),
        Tool(
            name="recommend_healthy_recipes",
            description="根据健康标签推荐食谱（如高血压→低钠食谱，贫血→高铁食谱）",
            inputSchema={
                "type": "object",
                "properties": {
                    "health_label": {
                        "type": "string",
                        "description": "健康标签：高血压/糖尿病/高血脂/痛风/超重/贫血/肾病",
                    },
                    "meal_type": {
                        "type": "string",
                        "description": "餐次类型：早餐/午餐/晚餐，仅返回该餐次的食谱",
                        "enum": ["早餐", "午餐", "晚餐"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量上限，默认5",
                        "default": 5,
                    },
                },
                "required": ["health_label"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """调用工具路由"""
    handlers = {
        "filter_recipes": handle_filter_recipes,
        "search_recipe_by_name": handle_search_by_name,
        "get_recipe_nutrition": handle_get_nutrition,
        "analyze_recipe_nutrition": handle_analyze_nutrition,
        "recommend_healthy_recipes": handle_recommend_healthy,
    }
    handler = handlers.get(name)
    if handler:
        return await handler(arguments)
    return [TextContent(type="text", text=f"未知工具: {name}")]


# ==================== 工具实现 ====================

def _recipe_summary(recipe: dict) -> dict:
    """提取食谱摘要信息"""
    n = recipe["nutrients"]
    return {
        "recipe_id": recipe["recipe_id"],
        "recipe_name": recipe["recipe_name"],
        "meal_type": recipe.get("meal_type", ""),
        "nutrients": {
            "calorie": n.get("calorie", {"value": None, "label": "能量", "unit": "kcal"}),
            "protein": n.get("protein", {"value": None, "label": "蛋白质", "unit": "g"}),
            "fat": n.get("fat", {"value": None, "label": "脂肪", "unit": "g"}),
            "sodium": n.get("sodium", {"value": None, "label": "钠", "unit": "mg"}),
            "carbohydrate": n.get("carbohydrate", {"value": None, "label": "碳水化合物", "unit": "g"}),
            "iron": n.get("iron", {"value": None, "label": "铁", "unit": "mg"}),
        },
        "ingredients": recipe.get("ingredients", "")[:100],
    }


async def handle_filter_recipes(args: dict) -> list[TextContent]:
    """根据营养约束筛选食谱"""
    max_cal = args.get("max_calorie")
    max_fat = args.get("max_fat")
    max_sodium = args.get("max_sodium")
    max_carb = args.get("max_carbohydrate")
    max_protein = args.get("max_protein")
    max_potassium = args.get("max_potassium")
    min_iron = args.get("min_iron")
    exclude_ing = args.get("exclude_ingredients", [])
    limit = args.get("limit", 10)
    meal_type = args.get("meal_type", "")  # 早餐/午餐/晚餐

    results = []
    for recipe in _recipe_db:
        # 按餐次过滤
        if meal_type:
            recipe_meal_type = recipe.get("meal_type", "")
            if recipe_meal_type != meal_type:
                continue

        # 排除不合适的食谱（婴儿食品、纯调味品、婴幼儿食品等）
        recipe_name = recipe.get("recipe_name", "")
        excluded_keywords = [
            "婴儿", "配方奶粉", "麦芽糖", "婴幼儿", "米粉", "亨氏", 
            "较大婴儿", "幼儿配方", "辅食", "奶粉", "奶粉（",
            # 新增：高钠高脂加工食品
            "方便面", "泡芙", "凤尾酥", "油炸", "饼干", "甜胚子",
            "凉粉(带调料)", "肉酱", "油料", "调味料",
            # 新增：零热量饮品（不适合作为主食推荐）
            "茶水", "纯净水", "矿泉水", "白开水", "蒸馏水",
            # 新增：酒精饮品（高血压患者禁忌）
            "酒", "白酒", "啤酒", "葡萄酒", "威士忌", "伏特加", "朗姆酒", "金酒", "龙舌兰", "清酒", "黄酒", "米酒", "果酒", "鸡尾酒",
        ]
        if any(keyword in recipe_name for keyword in excluded_keywords):
            continue
                
        n = recipe["nutrients"]
        
        # 营养约束过滤（处理None值：如果数据缺失，跳过该约束检查）
        if max_cal:
            val = n.get("calorie", {}).get("value")
            if val is not None and val > max_cal:
                continue
        if max_fat:
            val = n.get("fat", {}).get("value")
            if val is not None and val > max_fat:
                continue
        if max_sodium:
            val = n.get("sodium", {}).get("value")
            if val is not None and val > max_sodium:
                continue
        if max_carb:
            val = n.get("carbohydrate", {}).get("value")
            if val is not None and val > max_carb:
                continue
        if max_protein:
            val = n.get("protein", {}).get("value")
            if val is not None and val > max_protein:
                continue
        if max_potassium:
            val = n.get("potassium", {}).get("value")
            if val is not None and val > max_potassium:
                continue
        if min_iron:
            val = n.get("iron", {}).get("value")
            if val is not None and val < min_iron:
                continue

        # 配料排除
        ingredients_text = recipe.get("ingredients", "")
        if exclude_ing and any(ing in ingredients_text for ing in exclude_ing):
            continue

        results.append(recipe)

    # 混合排序策略：提供多样化的候选池
    # 1. 按热量升序（低热量）- 20个
    low_cal_sorted = sorted(results, key=lambda r: r.get("nutrients", {}).get("calorie", {}).get("value") or 0, reverse=False)
    
    # 2. 按热量降序（高热量）- 20个
    high_cal_sorted = sorted(results, key=lambda r: r.get("nutrients", {}).get("calorie", {}).get("value") or 0, reverse=True)
    
    # 3. 中等热量（接近平均值）- 20个
    if results:
        cal_values = [r.get("nutrients", {}).get("calorie", {}).get("value") or 0 for r in results]
        avg_cal = sum(cal_values) / len(cal_values)
        mid_cal_sorted = sorted(results, key=lambda r: abs((r.get("nutrients", {}).get("calorie", {}).get("value") or 0) - avg_cal), reverse=False)
    else:
        mid_cal_sorted = []
    
    # 合并：去重后取前limit个
    seen_ids = set()
    mixed_results = []
    
    # 先添加低热量
    for r in low_cal_sorted[:20]:
        rid = r.get("recipe_id")
        if rid not in seen_ids:
            mixed_results.append(r)
            seen_ids.add(rid)
    
    # 再添加高热量
    for r in high_cal_sorted[:20]:
        rid = r.get("recipe_id")
        if rid not in seen_ids:
            mixed_results.append(r)
            seen_ids.add(rid)
    
    # 最后添加中等热量
    for r in mid_cal_sorted[:20]:
        rid = r.get("recipe_id")
        if rid not in seen_ids:
            mixed_results.append(r)
            seen_ids.add(rid)
    
    # 应用 limit
    results = [_recipe_summary(r) for r in mixed_results[:limit]]

    return [TextContent(
        type="text",
        text=json.dumps({
            "filter_conditions": {k: v for k, v in args.items() if k != "limit"},
            "meal_type": meal_type or "全部",
            "total_matched": len(results),
            "recipes": results,
        }, ensure_ascii=False, indent=2)
    )]


async def handle_search_by_name(args: dict) -> list[TextContent]:
    """按名称搜索食谱"""
    keyword = args.get("keyword", "")
    limit = args.get("limit", 5)

    results = []
    for recipe in _recipe_db:
        if keyword in recipe["recipe_name"]:
            results.append(_recipe_summary(recipe))
            if len(results) >= limit:
                break

    return [TextContent(
        type="text",
        text=json.dumps({
            "keyword": keyword,
            "count": len(results),
            "recipes": results,
        }, ensure_ascii=False, indent=2)
    )]


async def handle_get_nutrition(args: dict) -> list[TextContent]:
    """获取食谱完整营养详情"""
    recipe_id = args.get("recipe_id", "")

    for recipe in _recipe_db:
        if recipe["recipe_id"] == recipe_id:
            # 格式化所有营养素
            nutrient_details = []
            for key, info in recipe["nutrients"].items():
                nutrient_details.append({
                    "name": key,
                    "label": info["label"],
                    "value": info["value"],
                    "unit": info["unit"],
                })
            return [TextContent(
                type="text",
                text=json.dumps({
                    "recipe_id": recipe["recipe_id"],
                    "recipe_name": recipe["recipe_name"],
                    "ingredients": recipe["ingredients"],
                    "nutrients": nutrient_details,
                    "total_nutrients": len(nutrient_details),
                }, ensure_ascii=False, indent=2)
            )]

    return [TextContent(
        type="text",
        text=json.dumps({"error": f"未找到食谱ID: {recipe_id}"}, ensure_ascii=False)
    )]


async def handle_analyze_nutrition(args: dict) -> list[TextContent]:
    """分析一组食谱的营养合规性"""
    recipe_ids = args.get("recipe_ids", [])
    constraints = args.get("constraints", {})

    analyzed = []
    warnings = []

    for rid in recipe_ids:
        recipe = next((r for r in _recipe_db if r["recipe_id"] == rid), None)
        if not recipe:
            warnings.append(f"食谱 {rid} 未找到")
            continue

        n = recipe["nutrients"]
        issues = []

        # 检查约束（处理None值）
        if "max_sodium" in constraints:
            sodium_val = n.get("sodium", {}).get("value")
            if sodium_val is not None and sodium_val > constraints["max_sodium"]:
                issues.append(f"钠含量 {sodium_val}mg 超过上限 {constraints['max_sodium']}mg")

        if "max_fat" in constraints:
            fat_val = n.get("fat", {}).get("value")
            if fat_val is not None and fat_val > constraints["max_fat"]:
                issues.append(f"脂肪含量 {fat_val}g 超过上限 {constraints['max_fat']}g")

        if "max_calorie" in constraints:
            cal_val = n.get("calorie", {}).get("value")
            if cal_val is not None and cal_val > constraints["max_calorie"]:
                issues.append(f"热量 {cal_val}kcal 超过上限 {constraints['max_calorie']}kcal")

        if "exclude_ingredients" in constraints:
            ingredients_text = recipe.get("ingredients", "")
            for ing in constraints["exclude_ingredients"]:
                if ing in ingredients_text:
                    issues.append(f"含有禁忌配料: {ing}")

        analyzed.append({
            "recipe_id": rid,
            "recipe_name": recipe["recipe_name"],
            "calorie": n.get("calorie", {}).get("value"),
            "sodium": n.get("sodium", {}).get("value"),
            "fat": n.get("fat", {}).get("value"),
            "compliant": len(issues) == 0,
            "issues": issues,
        })

    compliant_count = sum(1 for a in analyzed if a["compliant"])
    return [TextContent(
        type="text",
        text=json.dumps({
            "total": len(analyzed),
            "compliant_count": compliant_count,
            "non_compliant_count": len(analyzed) - compliant_count,
            "analysis": analyzed,
            "warnings": warnings,
            "summary": f"共分析{len(analyzed)}个食谱，{compliant_count}个符合约束" if constraints else "未提供约束条件",
        }, ensure_ascii=False, indent=2)
    )]


async def handle_recommend_healthy(args: dict) -> list[TextContent]:
    """根据健康标签推荐食谱"""
    health_label = args.get("health_label", "")
    limit = args.get("limit", 5)
    meal_type = args.get("meal_type", "")  # 可选：按餐次筛选

    # 健康标签 → 筛选策略
    strategies = {
        "高血压": {"max_sodium": 500, "sort_key": "sodium", "sort_asc": True},
        "高脂血症": {"max_fat": 8, "max_calorie": 150, "sort_key": "fat", "sort_asc": True},
        "高尿酸血症_痛风": {"max_calorie": 200, "sort_key": "calorie", "sort_asc": True},
        "糖尿病": {"max_carbohydrate": 15, "max_calorie": 200, "sort_key": "carbohydrate", "sort_asc": True},
        "肥胖": {"max_calorie": 120, "max_fat": 8, "sort_key": "calorie", "sort_asc": True},
        "慢性肾脏病": {"max_protein": 10, "max_sodium": 400, "max_potassium": 300, "sort_key": "sodium", "sort_asc": True},
        "感冒": {"max_calorie": 200, "sort_key": "calorie", "sort_asc": True},
        "营养指南": {"max_calorie": 300, "sort_key": "calorie", "sort_asc": True},
    }

    strategy = strategies.get(health_label)
    if not strategy:
        # 默认推荐低热量食谱
        strategy = {"max_calorie": 200, "sort_key": "calorie", "sort_asc": True}
    else:
        # 复制一份，避免修改共享字典
        strategy = dict(strategy)

    sort_key = strategy.pop("sort_key", "calorie")
    sort_asc = strategy.pop("sort_asc", True)

    candidates = []
    for recipe in _recipe_db:
        n = recipe["nutrients"]
        
        # 排除不合适的食谱（婴儿食品、纯调味品、婴幼儿食品等）
        recipe_name = recipe.get("recipe_name", "")
        excluded_keywords = [
            "婴儿", "配方奶粉", "麦芽糖", "婴幼儿", "米粉", "亨氏", 
            "较大婴儿", "幼儿配方", "辅食", "奶粉", "奶粉（",
            # 新增：高钠高脂加工食品
            "方便面", "泡芙", "凤尾酥", "油炸", "饼干", "甜胚子",
            "凉粉(带调料)", "肉酱", "油料", "调味料",
            # 新增：零热量饮品（不适合作为主食推荐）
            "茶水", "纯净水", "矿泉水", "白开水", "蒸馏水",
            # 新增：酒精饮品（高血压患者禁忌）
            "酒", "白酒", "啤酒", "葡萄酒", "威士忌", "伏特加", "朗姆酒", "金酒", "龙舌兰", "清酒", "黄酒", "米酒", "果酒", "鸡尾酒",
        ]
        if any(keyword in recipe_name for keyword in excluded_keywords):
            continue

        # 按餐次过滤
        if meal_type:
            recipe_meal_type = recipe.get("meal_type", "")
            if recipe_meal_type != meal_type:
                continue

        passed = True

        for constraint_key, constraint_val in strategy.items():
            if constraint_key.startswith("max_"):
                nutrient_key = constraint_key[4:]
                actual = n.get(nutrient_key, {}).get("value")
                # 如果数据缺失，跳过该检查；只有有值时才比较
                if actual is not None and actual > constraint_val:
                    passed = False
                    break
            elif constraint_key.startswith("min_"):
                nutrient_key = constraint_key[4:]
                actual = n.get(nutrient_key, {}).get("value")
                if actual is not None and actual < constraint_val:
                    passed = False
                    break

        if passed:
            candidates.append(recipe)

    # 排序（处理null值，将null视为最大值，这样有值的排在前面）
    def sort_key_func(r):
        val = r["nutrients"].get(sort_key, {}).get("value")
        if val is None:
            return float('inf') if sort_asc else float('-inf')
        return val
    
    candidates.sort(key=sort_key_func, reverse=not sort_asc)

    results = [_recipe_summary(r) for r in candidates[:limit]]

    return [TextContent(
        type="text",
        text=json.dumps({
            "health_label": health_label,
            "meal_type": meal_type or "全部",
            "filter_strategy": {k: v for k, v in strategy.items()},
            "total_candidates": len(candidates),
            "recommended": results,
        }, ensure_ascii=False, indent=2)
    )]


# ==================== 启动入口 ====================

async def run_stdio():
    """启动 MCP 服务器 (stdio 模式，作为 Agent B 子进程)"""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def run_streamable_http(host: str = "0.0.0.0", port: int = 8002):
    """
    启动 MCP 服务器 (Streamable HTTP 模式，独立 HTTP 服务)
    """
    import anyio
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from starlette.responses import JSONResponse
    from starlette.requests import Request  # 新增Request导入
    from mcp.server.streamable_http import StreamableHTTPServerTransport

    # 创建全局 transport
    transport = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=True,
    )

    async def handle_mcp(scope, receive, send):
        """MCP Streamable HTTP 端点"""
        await transport.handle_request(scope, receive, send)

    # 修复：用Request对象作为参数，符合Starlette路由规范
    async def handle_health(request: Request) -> JSONResponse:
        try:
            count = len(_recipe_db) if isinstance(_recipe_db, list) else 0
            return JSONResponse({
                "status": "healthy",
                "server": "recipe-database",
                "recipes_count": count,
                "transport": "streamable_http",
            })
        except Exception as e:
            return JSONResponse({
                "status": "unhealthy",
                "error": str(e),
            }, status_code=500)

    app = Starlette(
        routes=[
            # 注意：/health 用endpoint，/mcp用Mount
            Route("/health", endpoint=handle_health, methods=["GET"]),
            Mount("/mcp", app=handle_mcp),
        ],
    )

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    uvicorn_server = uvicorn.Server(config)

    async with transport.connect() as (read_stream, write_stream):
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                server.run,
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

            print(f"[MCP Server] Streamable HTTP mode: http://{host}:{port}", file=sys.stderr)
            print(f"[MCP Server] MCP endpoint: http://{host}:{port}/mcp", file=sys.stderr)
            print(f"[MCP Server] Recipes: {len(_recipe_db)}", file=sys.stderr)

            await uvicorn_server.serve()


    async def handle_mcp(scope, receive, send):
        """MCP Streamable HTTP 端点 —— 所有请求路由到同一个 transport"""
        await transport.handle_request(scope, receive, send)

    async def handle_health(scope, receive, send):
        response = JSONResponse({
            "status": "healthy",
            "server": "recipe-database",
            "recipes_count": len(_recipe_db),
            "transport": "streamable_http",
        })
        await response(scope, receive, send)

    app = Starlette(
        routes=[
            Route("/health", endpoint=handle_health, methods=["GET"]),
            Mount("/mcp", app=handle_mcp),
        ],
    )

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    uvicorn_server = uvicorn.Server(config)

    # transport.connect() 必须在整个服务生命周期内保持
    async with transport.connect() as (read_stream, write_stream):
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                server.run,
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

            print(f"[MCP Server] Streamable HTTP mode: http://{host}:{port}", file=sys.stderr)
            print(f"[MCP Server] MCP endpoint: http://{host}:{port}/mcp", file=sys.stderr)
            print(f"[MCP Server] Recipes: {len(_recipe_db)}", file=sys.stderr)

            await uvicorn_server.serve()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="食谱营养数据库 MCP Server")
    parser.add_argument(
        "--http", action="store_true",
        help="启用 Streamable HTTP 模式（独立 HTTP 服务），默认为 stdio 模式（子进程）"
    )
    parser.add_argument(
        "--host", type=str, default="0.0.0.0",
        help="HTTP 模式监听地址（默认 0.0.0.0）"
    )
    parser.add_argument(
        "--port", type=int, default=8002,
        help="HTTP 模式监听端口（默认 8002）"
    )
    args = parser.parse_args()

    if args.http:
        asyncio.run(run_streamable_http(host=args.host, port=args.port))
    else:
        asyncio.run(run_stdio())
