"""
智能营养配餐引擎
职责:
1. 根据用户信息计算每日营养需求
2. 分配三餐营养目标(早餐30%、午餐40%、晚餐30%)
3. 调用MCP工具查找匹配的食谱
4. LLM智能组合成完整的一日三餐方案
"""
import json
from typing import Dict, List, Optional
from config.settings import settings


class MealPlanner:
    """智能营养配餐引擎"""
    
    # 营养素宏量比例
    MACRO_RATIOS = {
        "protein": 0.15,      # 蛋白质 15%
        "fat": 0.25,          # 脂肪 25%
        "carbohydrate": 0.60, # 碳水 60%
    }
    
    # 三餐能量分配
    MEAL_RATIOS = {
        "breakfast": 0.30,    # 早餐 30%
        "lunch": 0.40,        # 午餐 40%
        "dinner": 0.30,       # 晚餐 30%
    }
    
    @staticmethod
    def calculate_daily_nutrition(profile: dict, health_condition: str = "") -> dict:
        """
        计算每日营养需求
        
        Args:
            profile: 用户档案 {height, weight, age, gender, bmi, bmr, daily_calories}
            health_condition: 健康状况(高血压/糖尿病等)
            
        Returns:
            营养需求字典
        """
        daily_calories = profile.get("daily_calories", 2000)
        
        # 基础宏量营养素计算
        protein_g = (daily_calories * MealPlanner.MACRO_RATIOS["protein"]) / 4  # 4kcal/g
        fat_g = (daily_calories * MealPlanner.MACRO_RATIOS["fat"]) / 9          # 9kcal/g
        carb_g = (daily_calories * MealPlanner.MACRO_RATIOS["carbohydrate"]) / 4 # 4kcal/g
        
        nutrition = {
            "calorie": daily_calories,
            "protein": round(protein_g, 1),
            "fat": round(fat_g, 1),
            "carbohydrate": round(carb_g, 1),
        }
        
        # 根据健康状况调整微量营养素限制
        if "高血压" in health_condition or "高脂血症" in health_condition:
            nutrition["max_sodium"] = 2000  # mg/天
            nutrition["max_fat"] = fat_g * 0.9  # 减少10%脂肪
        
        if "糖尿病" in health_condition:
            nutrition["max_carbohydrate"] = carb_g * 0.85  # 减少15%碳水
            nutrition["max_sugar"] = 50  # g/天
        
        if "肥胖" in health_condition:
            nutrition["calorie"] = daily_calories * 0.8  # 减少20%热量
        
        return nutrition
    
    @staticmethod
    def allocate_meal_targets(daily_nutrition: dict) -> dict:
        """
        分配三餐营养目标
        
        Returns:
            {
                "breakfast": {calorie, protein, fat, carbohydrate, ...},
                "lunch": {...},
                "dinner": {...}
            }
        """
        meals = {}
        
        for meal_name, ratio in MealPlanner.MEAL_RATIOS.items():
            meal_target = {}
            for nutrient, value in daily_nutrition.items():
                if nutrient.startswith("max_") or nutrient.startswith("min_"):
                    # 限制性营养素按餐平均分配
                    meal_target[nutrient] = value / 3
                else:
                    # 宏量营养素按比例分配
                    meal_target[nutrient] = round(value * ratio, 1)
            
            meals[meal_name] = meal_target
        
        return meals
    
    @staticmethod
    def build_search_constraints(meal_target: dict, meal_type: str, num_recipes: int = 3) -> dict:
        """
        将营养目标转换为MCP工具的搜索约束
        
        Args:
            meal_target: 单餐营养目标
            meal_type: breakfast/lunch/dinner
            
        Returns:
            MCP工具参数
        """
        # 餐次英文→中文映射
        MEAL_TYPE_MAP = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐"}
        constraints = {
            "meal_type": MEAL_TYPE_MAP.get(meal_type, meal_type),
            "limit": 10,
        }
        
        # 热量约束(单个食谱不超过每餐平均热量的1.5倍，给LLM充足的高热量选择)
        calorie = meal_target.get("calorie", 500)
        constraints["max_calorie"] = int(calorie / num_recipes * 1.5) if num_recipes else int(calorie * 0.8)
        
        # 脂肪约束
        if "max_fat" in meal_target:
            constraints["max_fat"] = meal_target["max_fat"] / 3
        elif "fat" in meal_target:
            constraints["max_fat"] = meal_target["fat"] * 0.6  # 放宽脂肪上限
        
        # 钠约束
        if "max_sodium" in meal_target:
            constraints["max_sodium"] = meal_target["max_sodium"]
        
        # 碳水约束
        if "max_carbohydrate" in meal_target:
            constraints["max_carbohydrate"] = meal_target["max_carbohydrate"] / 3
        
        return constraints
    
    @staticmethod
    async def select_recipes_for_meal(
        candidates: List[dict], 
        meal_target: dict, 
        num_recipes: int = 3,
        llm_chain = None,
        health_condition: str = ""
    ) -> List[dict]:
        """
        从候选食谱中选择最优组合（纯LLM智能选择，无反向降级）
            
        Args:
            candidates: 候选食谱列表
            meal_target: 营养目标
            num_recipes: 需要选择的食谱数量
            llm_chain: LLM对象
            health_condition: 健康状况
                
        Returns:
            选中的食谱列表
        """
        if not candidates or len(candidates) == 0:
            return []
            
        if not llm_chain:
            print("[MealPlanner] LLM不可用，无法选择食谱")
            return []
        
        try:
            selected = await MealPlanner._llm_select_recipes(
                candidates=candidates,
                meal_target=meal_target,
                num_recipes=num_recipes,
                llm_chain=llm_chain,
                health_condition=health_condition
            )
            if selected:
                print(f"[MealPlanner] LLM最终选择了{len(selected)}个食谱")
            else:
                print(f"[MealPlanner] LLM未能选出合格食谱")
            return selected
        except Exception as e:
            print(f"[MealPlanner] LLM选择失败: {e}")
            return []
        
    @staticmethod
    def _build_candidates_info(candidates: List[dict]) -> list:
        """构建候选食谱的简化信息列表（传递全部候选）"""
        candidates_info = []
        for i, recipe in enumerate(candidates):
            nutrients = recipe.get("nutrients", {})
            cal = nutrients.get("calorie", {}).get("value", 0) or 0
            pro = nutrients.get("protein", {}).get("value", 0) or 0
            fat = nutrients.get("fat", {}).get("value", 0) or 0
            carb = nutrients.get("carbohydrate", {}).get("value", 0) or 0
            sodium = nutrients.get("sodium", {}).get("value", 0) or 0
            candidates_info.append({
                "index": i,
                "name": recipe.get("recipe_name", "未知"),
                "meal_type": recipe.get("meal_type", ""),
                "calorie": round(cal, 1),
                "protein": round(pro, 1),
                "fat": round(fat, 1),
                "carbohydrate": round(carb, 1),
                "sodium": round(sodium, 1),
                "recipe_id": recipe.get("recipe_id", "")
            })
        return candidates_info

    @staticmethod
    def _parse_llm_json_response(response: str) -> list:
        """解析LLM返回的JSON数组，兼容markdown格式"""
        response = response.strip()
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            response = response.split("```")[1].strip()
        # 尝试提取JSON数组
        start = response.find("[")
        end = response.rfind("]")
        if start != -1 and end != -1:
            response = response[start:end+1]
        return json.loads(response)

    @staticmethod
    def _get_selected_recipes(candidates: List[dict], indices: list, num_recipes: int) -> List[dict]:
        """根据index列表从候选中提取食谱（不做热量拦截，完全信任LLM）"""
        selected = []
        used_ids = set()
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(candidates):
                recipe = candidates[idx]
                rid = recipe.get("recipe_id")
                if rid and rid not in used_ids:
                    selected.append(recipe)
                    used_ids.add(rid)
                    if len(selected) >= num_recipes:
                        break
        return selected

    @staticmethod
    def _calc_total_calorie(recipes: List[dict]) -> float:
        """计算食谱列表的总热量"""
        return sum(
            r.get("nutrients", {}).get("calorie", {}).get("value", 0) or 0
            for r in recipes
        )

    @staticmethod
    async def _llm_select_recipes(
        candidates: List[dict],
        meal_target: dict,
        num_recipes: int,
        llm_chain,
        health_condition: str
    ) -> List[dict]:
        """
        使用LLM智能选择食谱组合（含反思机制）
        
        流程：
        1. 第一轮：LLM从候选中选择食谱
        2. 第二轮（反思）：LLM检查自己的选择是否合格，不合格则重新选择
        
        Args:
            candidates: 候选食谱列表
            meal_target: 营养目标
            num_recipes: 需要选择的食谱数量
            llm_chain: LLM对象
            health_condition: 健康状况
                
        Returns:
            选中的食谱列表
        """
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser
            
        # 构建全部候选食谱的简化信息
        candidates_info = MealPlanner._build_candidates_info(candidates)
        
        # 计算候选食谱的热量分布，帮助LLM理解
        cal_values = [c["calorie"] for c in candidates_info]
        total_cal = sum(cal_values)
        avg_cal = total_cal / len(candidates_info) if candidates_info else 0
        min_candidate_cal = min(cal_values) if cal_values else 0
        max_candidate_cal = max(cal_values) if cal_values else 0
        
        # 餐目标参数
        target_cal = meal_target.get("calorie", 500)
        min_cal = int(target_cal * 0.85)
        max_cal = int(target_cal * 1.15)
        sodium_limit = f"钠: ≤{int(meal_target.get('max_sodium', 9999))}mg" if 'max_sodium' in meal_target else ""
        
        # ==================== 第一轮：初始选择 ====================
        select_prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "你是一位专业的营养师，负责为用户选择最适合的一餐食谱组合。\n"
                "\n"
                "【核心任务】\n"
                "从候选列表中选出{num}个食谱，使它们的**总热量之和**严格控制在目标范围内。\n"
                "\n"
                "【关键原则】\n"
                "1. **{num}个食谱的总热量必须在{min_cal}-{max_cal}kcal之间**（硬性约束）\n"
                "   - 正确示例：250 + 250 + 250 = 750kcal ✅\n"
                "   - 错误示例：5 + 7 + 10 = 22kcal ❌ (严重不足)\n"
                "   - 错误示例：400 + 400 + 400 = 1200kcal ❌ (严重超标)\n"
                "2. 优先选择主食类食谱(米饭、面条、包子、饼、粥等)，搭配少量蔬菜/汤品\n"
                "3. 避免选择过于相似的食谱\n"
                "4. 排除零热量饮品和婴儿食品\n"
                "\n"
                "【候选池热量分布】\n"
                "- 最低: {min_candidate_cal}kcal, 最高: {max_candidate_cal}kcal, 平均: {avg_cal}kcal\n"
                "- 你需要从中挑选{num}个，使总热量≈{target_cal}kcal\n"
                "- 这意味着每个食谱平均需要≈{per_recipe_cal}kcal\n"
                "\n"
                "【输出格式】\n"
                "只返回JSON数组，包含选中食谱的index，例如：[0, 3, 7]\n"
                "不要输出其他内容。"
            )),
            ("human", (
                "【餐次目标】\n"
                "总热量: {target_cal} kcal\n"
                "允许范围: {min_cal}-{max_cal} kcal（{num}个食谱的热量总和）\n"
                "蛋白质: {target_pro}g | 脂肪: {target_fat}g | 碳水: {target_carb}g\n"
                "{sodium_limit}\n"
                "\n"
                "【健康状况】{health}\n"
                "\n"
                "【候选食谱池】共{total_count}个\n"
                "{candidates_json}\n"
                "\n"
                "请返回选中食谱的index数组："
            ))
        ])
        
        per_recipe_cal = round(target_cal / num_recipes, 0)
        
        chain = select_prompt | llm_chain | StrOutputParser()
        
        response1 = await chain.ainvoke({
            "target_cal": target_cal,
            "min_cal": min_cal,
            "max_cal": max_cal,
            "num": num_recipes,
            "per_recipe_cal": int(per_recipe_cal),
            "min_candidate_cal": round(min_candidate_cal, 1),
            "max_candidate_cal": round(max_candidate_cal, 1),
            "avg_cal": round(avg_cal, 1),
            "target_pro": meal_target.get("protein", 20),
            "target_fat": meal_target.get("fat", 15),
            "target_carb": meal_target.get("carbohydrate", 60),
            "sodium_limit": sodium_limit,
            "health": health_condition or "无特殊限制",
            "total_count": len(candidates_info),
            "candidates_json": json.dumps(candidates_info, ensure_ascii=False, indent=2)
        })
        
        try:
            initial_indices = MealPlanner._parse_llm_json_response(response1)
        except Exception as e:
            print(f"[MealPlanner] 第一轮解析失败: {e}, 响应: {response1[:200]}")
            return []
        
        if not initial_indices or len(initial_indices) == 0:
            print(f"⚠️ [MealPlanner] 第一轮LLM返回空数组")
            return []
        
        initial_recipes = MealPlanner._get_selected_recipes(candidates, initial_indices, num_recipes)
        initial_cal = MealPlanner._calc_total_calorie(initial_recipes)
        initial_names = [r.get("recipe_name", "?") for r in initial_recipes]
        print(f"[MealPlanner] 第一轮选择: {initial_names}, 总热量{initial_cal}kcal (目标{min_cal}-{max_cal}kcal)")
        
        # ==================== 第二轮：反思检查 ====================
        # 构建已选食谱的详细信息
        selected_detail = []
        for idx, recipe in zip(initial_indices, initial_recipes):
            cal = recipe.get("nutrients", {}).get("calorie", {}).get("value", 0) or 0
            selected_detail.append(f"  index={idx}, {recipe.get('recipe_name', '?')}, {cal}kcal")
        selected_detail_text = "\n".join(selected_detail)
        
        is_in_range = min_cal <= initial_cal <= max_cal
        
        if is_in_range:
            print(f"✅ [MealPlanner] 反思通过: 总热量{initial_cal}kcal在范围内({min_cal}-{max_cal}kcal)")
            return initial_recipes
        
        # 不合格，进行反思重新选择
        status_text = ""
        if initial_cal < min_cal:
            status_text = f"总热量{initial_cal}kcal **严重不足**，低于下限{min_cal}kcal，差距{min_cal - initial_cal}kcal"
        else:
            status_text = f"总热量{initial_cal}kcal **严重超标**，超过上限{max_cal}kcal，超出{initial_cal - max_cal}kcal"
        
        print(f"⚠️ [MealPlanner] 反思: {status_text}，要求LLM重新选择")
        
        reflect_prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "你是一位严格的营养质检员。上一轮选择不合格，你需要重新选择。\n"
                "\n"
                "【上一轮选择结果 - 不合格】\n"
                "{selected_detail}\n"
                "总热量: {initial_cal}kcal\n"
                "问题: {status_text}\n"
                "\n"
                "【修正要求】\n"
                "- {num}个食谱的总热量必须在 **{min_cal}-{max_cal}kcal** 之间\n"
                "- 目标总热量是{target_cal}kcal，你需要选择热量加起来接近这个值的组合\n"
                "- 每个食谱平均需要≈{per_recipe_cal}kcal\n"
                "- 请从候选池中选择热量较高的主食类食谱，不要选全是低热量汤品\n"
                "\n"
                "【重要】请仔细计算你选择的食谱热量总和，确保在范围内！\n"
                "\n"
                "【输出格式】\n"
                "只返回JSON数组，包含选中食谱的index，例如：[2, 5, 10]\n"
                "不要输出其他内容。"
            )),
            ("human", (
                "【餐次目标】总热量: {target_cal}kcal, 允许范围: {min_cal}-{max_cal}kcal\n"
                "需要{num}个食谱，每个平均≈{per_recipe_cal}kcal\n"
                "\n"
                "【候选食谱池】共{total_count}个\n"
                "{candidates_json}\n"
                "\n"
                "请重新选择，确保总热量在{min_cal}-{max_cal}kcal范围内："
            ))
        ])
        
        chain2 = reflect_prompt | llm_chain | StrOutputParser()
        
        response2 = await chain2.ainvoke({
            "selected_detail": selected_detail_text,
            "initial_cal": round(initial_cal, 1),
            "status_text": status_text,
            "target_cal": target_cal,
            "min_cal": min_cal,
            "max_cal": max_cal,
            "num": num_recipes,
            "per_recipe_cal": int(per_recipe_cal),
            "total_count": len(candidates_info),
            "candidates_json": json.dumps(candidates_info, ensure_ascii=False, indent=2)
        })
        
        try:
            reflect_indices = MealPlanner._parse_llm_json_response(response2)
        except Exception as e:
            print(f"[MealPlanner] 反思轮解析失败: {e}, 响应: {response2[:200]}")
            # 反思失败，使用第一轮结果
            return initial_recipes
        
        if not reflect_indices or len(reflect_indices) == 0:
            print(f"⚠️ [MealPlanner] 反思轮LLM返回空数组，使用第一轮结果")
            return initial_recipes
        
        reflect_recipes = MealPlanner._get_selected_recipes(candidates, reflect_indices, num_recipes)
        reflect_cal = MealPlanner._calc_total_calorie(reflect_recipes)
        reflect_names = [r.get("recipe_name", "?") for r in reflect_recipes]
        print(f"[MealPlanner] 反思轮选择: {reflect_names}, 总热量{reflect_cal}kcal (目标{min_cal}-{max_cal}kcal)")
        
        # 使用反思后的结果（无论是否合格，都信任LLM的最终决策）
        return reflect_recipes
    
    
    @staticmethod
    def calculate_total_nutrition(meals: dict) -> dict:
        """
        计算一日总营养
        
        Args:
            meals: {"breakfast": [recipes], "lunch": [...], "dinner": [...]}
            
        Returns:
            总营养字典
        """
        total = {
            "calorie": 0,
            "protein": 0,
            "fat": 0,
            "carbohydrate": 0,
            "sodium": 0,
        }
        
        for meal_name, recipes in meals.items():
            for recipe in recipes:
                nutrients = recipe.get("nutrients", {})
                for nutrient in total.keys():
                    value = nutrients.get(nutrient, {}).get("value", 0)
                    if value is not None:
                        total[nutrient] += value
        
        # 四舍五入
        for key in total:
            total[key] = round(total[key], 1)
        
        return total
    
    @staticmethod
    def generate_llm_prompt(
        user_profile: dict,
        health_condition: str,
        diet_notes: List[str],
        meals: dict,
        daily_target: dict,
        actual_total: dict
    ) -> str:
        """
        生成LLM提示词,让AI优化和解释配餐方案
        
        Returns:
            LLM提示词
        """
        prompt = f"""你是一位专业的营养师,请根据以下信息为用户生成一日三餐饮食方案的专业解读。

【用户信息】
- 身高: {user_profile.get('height')}cm
- 体重: {user_profile.get('weight')}kg
- 年龄: {user_profile.get('age')}岁
- 性别: {user_profile.get('gender')}
- BMI: {user_profile.get('bmi', 'N/A')}
- 健康状况: {health_condition or '无特殊疾病'}
- 每日建议摄入: {user_profile.get('daily_calories', 'N/A')} kcal

【饮食注意事项】
{chr(10).join([f"- {note[:100]}" for note in diet_notes[:5]])}

【营养目标 vs 实际达成】
- 热量: 目标 {daily_target.get('calorie')} kcal | 实际 {actual_total.get('calorie')} kcal
- 蛋白质: 目标 {daily_target.get('protein')}g | 实际 {actual_total.get('protein')}g
- 脂肪: 目标 {daily_target.get('fat')}g | 实际 {actual_total.get('fat')}g
- 碳水: 目标 {daily_target.get('carbohydrate')}g | 实际 {actual_total.get('carbohydrate')}g
- 钠: 实际 {actual_total.get('sodium')}mg {'(限制<2000mg)' if '高血压' in health_condition else ''}

【推荐食谱】
"""
        
        meal_names = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐"}
        for meal_key, meal_label in meal_names.items():
            recipes = meals.get(meal_key, [])
            prompt += f"\n{meal_label}:\n"
            for recipe in recipes:
                name = recipe.get("recipe_name", "未知")
                nutrients = recipe.get("nutrients", {})
                cal = nutrients.get("calorie", {}).get("value", "N/A")
                pro = nutrients.get("protein", {}).get("value", "N/A")
                fat = nutrients.get("fat", {}).get("value", "N/A")
                prompt += f"  - {name} (热量:{cal}kcal, 蛋白质:{pro}g, 脂肪:{fat}g)\n"
        
        prompt += """
请对以上配餐方案进行专业解读，并严格以JSON格式输出（不要输出其他内容）。

JSON结构如下：
{
  "evaluation": "整体评价（优缺点、是否符合健康需求，200字以内）",
  "cooking_advice": [
    {
      "category": "环节名称（如：烹饪方式、进食时间、食材处理）",
      "suggestions": ["具体建议1", "具体建议2"],
      "scientific_basis": "科学依据（简短）"
    }
  ],
  "nutrition_gaps": [
    {
      "nutrient": "不足项目名称（如：钠超标、热量缺口、碳水缺口、水果缺失）",
      "gap_description": "缺口描述（含具体数值，如：超6905.6mg / 缺142.6kcal）",
      "supplement": "推荐补充方式（不增食谱，仅调整执行）",
      "expected_effect": "预期效果"
    }
  ]
}

【要求】
1. cooking_advice 提供3个环节的专业建议，每个环节含2-3条具体建议
2. nutrition_gaps 只列出实际不达标的项目（若全部达标则为空数组）
3. 所有建议必须具体、可操作，包含数值（如克数、时间、百分比）
4. 不要修改食谱列表，只做解读和建议
5. 只返回JSON，不要输出其他内容"""
        
        return prompt
