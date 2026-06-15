"""
使用LLM智能解析用户个人指标
替代复杂的正则表达式,让AI来理解自然语言中的身高、体重等信息
"""
import json
from typing import Optional, Dict, Any

from config.settings import settings


class LLMProfileParser:
    """使用LLM解析个人指标的解析器"""
    
    @staticmethod
    def parse(text: str) -> dict:
        """
        使用LLM从文本中提取个人指标
        
        Args:
            text: 用户输入的自然语言文本
            
        Returns:
            提取的指标字典 {height, weight, age, gender, ...}
        """
        try:
            from langchain_community.chat_models import ChatTongyi
            
            # 创建LLM实例
            llm = ChatTongyi(
                model=settings.QWEN_MODEL,
                api_key=settings.DASHSCOPE_API_KEY,
                temperature=0.1,
            )
            
            # 构建提示词
            prompt = f"""你是一个专业的健康数据提取助手。请从以下用户输入中提取个人健康指标信息。

用户输入："{text}"

请仔细分析文本，提取以下字段（如果无法确定则填null）：
- height: 身高(cm)，如果是米请转换为cm（例如1.7米→170），只填写数字
- weight: 体重(kg)，如果是斤请除以2（例如130斤→65），只填写数字  
- age: 年龄(岁)，只填写数字
- gender: 性别，只能是"男"或"女"
- activity_level: 活动量，根据描述判断，可选值："久坐不动"、"轻度活动"、"中度活动"、"重度活动"，如果不确定填null
- health_condition: 健康状况，如"高血压"、"糖尿病"等，多个用逗号分隔，如果没有填null
- dietary_preference: 饮食偏好，如"喜欢清淡"、"爱吃辣"等，如果没有填null
- allergies: 过敏食物，如果没有填null

重要规则：
1. 只返回JSON格式，不要有任何其他文字
2. 所有数值字段只填写数字，不要带单位
3. 如果某个字段在文本中找不到，填null
4. 确保JSON格式正确

示例1：
输入："身高170cm，体重65kg，23岁，男，推荐饮食"
输出：{{"height": 170, "weight": 65, "age": 23, "gender": "男", "activity_level": null, "health_condition": null, "dietary_preference": null, "allergies": null}}

示例2：
输入："我有高血压，身高1.75米，体重140斤，今年30岁，女性"
输出：{{"height": 175, "weight": 70, "age": 30, "gender": "女", "activity_level": null, "health_condition": "高血压", "dietary_preference": null, "allergies": null}}

现在请处理上面的用户输入，只返回JSON："""
            
            # 调用LLM
            response = llm.invoke(prompt)
            result_text = response.content.strip()
            
            # 尝试解析JSON（可能包含```json```标记）
            if '```json' in result_text:
                result_text = result_text.split('```json')[1].split('```')[0].strip()
            elif '```' in result_text:
                result_text = result_text.split('```')[1].split('```')[0].strip()
            
            extracted = json.loads(result_text)
            
            # 验证并清理数据
            cleaned = {}
            
            # 身高验证 (30-250cm)
            if extracted.get('height') is not None:
                h = float(extracted['height'])
                if 30 <= h <= 250:
                    cleaned['height'] = h
            
            # 体重验证 (20-300kg)
            if extracted.get('weight') is not None:
                w = float(extracted['weight'])
                if 20 <= w <= 300:
                    cleaned['weight'] = w
            
            # 年龄验证 (1-150岁)
            if extracted.get('age') is not None:
                a = int(extracted['age'])
                if 1 <= a <= 150:
                    cleaned['age'] = a
            
            # 性别验证
            if extracted.get('gender') in ['男', '女']:
                cleaned['gender'] = extracted['gender']
            
            # 其他字段直接复制
            for field in ['activity_level', 'health_condition', 'dietary_preference', 'allergies']:
                if extracted.get(field):
                    cleaned[field] = extracted[field]
            
            print(f"[LLMProfileParser] 成功解析: {cleaned}")
            return cleaned
            
        except Exception as e:
            print(f"[LLMProfileParser] LLM解析失败: {e}")
            print(f"[LLMProfileParser] 回退到简单正则解析")
            # 回退到简单的备用方案
            return LLMProfileParser._fallback_parse(text)
    
    @staticmethod
    def _fallback_parse(text: str) -> dict:
        """
        备用简单解析方案（当LLM不可用时使用）
        仅支持最基本的格式：身高XXXcm，体重XXXkg，XX岁，男/女
        """
        import re
        extracted = {}
        
        # 最简单的正则：直接匹配数字+单位
        # 身高 - 严格匹配"身高"后面跟着数字和cm
        height_match = re.search(r'身高\s*[：:\s]*\s*(\d+(?:\.\d+)?)\s*cm', text)
        if height_match:
            h = float(height_match.group(1))
            if 30 <= h <= 250:
                extracted['height'] = h
        
        # 体重 - 严格匹配"体重"后面跟着数字和kg
        weight_match = re.search(r'体重\s*[：:\s]*\s*(\d+(?:\.\d+)?)\s*kg', text)
        if weight_match:
            w = float(weight_match.group(1))
            if 20 <= w <= 300:
                extracted['weight'] = w
        
        # 年龄
        age_match = re.search(r'(\d+)\s*岁', text)
        if age_match:
            a = int(age_match.group(1))
            if 1 <= a <= 150:
                extracted['age'] = a
        
        # 性别
        if '男' in text:
            extracted['gender'] = '男'
        elif '女' in text:
            extracted['gender'] = '女'
        
        return extracted
