"""
个人指标管理器
负责解析、验证、补全用户个人健康指标
"""
from typing import Optional


# 必要指标定义
REQUIRED_FIELDS = {
    "height": {"label": "身高", "unit": "cm", "required": True, "type": "number"},
    "weight": {"label": "体重", "unit": "kg", "required": True, "type": "number"},
    "age": {"label": "年龄", "unit": "岁", "required": True, "type": "number"},
    "gender": {"label": "性别", "unit": "", "required": True, "type": "enum", "options": ["男", "女"]},
}

# 可选指标
OPTIONAL_FIELDS = {
    "activity_level": {"label": "活动量", "unit": "", "required": False, "type": "enum", 
                       "options": ["久坐不动", "轻度活动", "中度活动", "重度活动"], "default": "中度活动"},
    "health_condition": {"label": "健康状况", "unit": "", "required": False, "type": "text"},
    "dietary_preference": {"label": "饮食偏好", "unit": "", "required": False, "type": "text"},
    "allergies": {"label": "过敏食物", "unit": "", "required": False, "type": "text"},
}


class UserProfile:
    """用户个人指标档案"""

    def __init__(self):
        self.height: Optional[float] = None  # cm
        self.weight: Optional[float] = None  # kg
        self.age: Optional[int] = None
        self.gender: Optional[str] = None  # 男/女
        self.activity_level: str = "中度活动"
        self.health_condition: str = ""
        self.dietary_preference: str = ""
        self.allergies: str = ""

    def is_complete(self) -> bool:
        """检查必要指标是否全部填写"""
        return all([
            self.height is not None and self.height > 0,
            self.weight is not None and self.weight > 0,
            self.age is not None and self.age > 0,
            self.gender in ["男", "女"],
        ])

    def get_missing_fields(self) -> list:
        """获取缺失的必要指标"""
        missing = []
        if not self.height or self.height <= 0:
            missing.append(REQUIRED_FIELDS["height"])
        if not self.weight or self.weight <= 0:
            missing.append(REQUIRED_FIELDS["weight"])
        if not self.age or self.age <= 0:
            missing.append(REQUIRED_FIELDS["age"])
        if self.gender not in ["男", "女"]:
            missing.append(REQUIRED_FIELDS["gender"])
        return missing

    def to_dict(self) -> dict:
        """转为字典"""
        return {
            "height": self.height,
            "weight": self.weight,
            "age": self.age,
            "gender": self.gender,
            "activity_level": self.activity_level,
            "health_condition": self.health_condition,
            "dietary_preference": self.dietary_preference,
            "allergies": self.allergies,
        }

    def calculate_bmi(self) -> Optional[float]:
        """计算 BMI"""
        if self.height and self.weight and self.height > 0:
            height_m = self.height / 100
            return round(self.weight / (height_m ** 2), 1)
        return None

    def calculate_bmr(self) -> Optional[float]:
        """计算基础代谢率 (Mifflin-St Jeor 公式)"""
        if not (self.weight and self.height and self.age and self.gender):
            return None
        
        if self.gender == "男":
            bmr = 10 * self.weight + 6.25 * self.height - 5 * self.age + 5
        else:
            bmr = 10 * self.weight + 6.25 * self.height - 5 * self.age - 161
        return round(bmr, 1)

    def calculate_daily_calories(self) -> Optional[float]:
        """计算每日所需热量 (考虑活动量)"""
        bmr = self.calculate_bmr()
        if bmr is None:
            return None
        
        activity_multipliers = {
            "久坐不动": 1.2,
            "轻度活动": 1.375,
            "中度活动": 1.55,
            "重度活动": 1.725,
        }
        multiplier = activity_multipliers.get(self.activity_level, 1.55)
        return round(bmr * multiplier, 1)


class ProfileParser:
    """从用户输入中解析个人指标（parse_from_text 已移除，由 LLMProfileParser 替代）"""

    @staticmethod
    def update_profile(profile: UserProfile, extracted: dict) -> UserProfile:
        """用提取的指标更新用户档案"""
        if 'height' in extracted:
            profile.height = extracted['height']
        if 'weight' in extracted:
            profile.weight = extracted['weight']
        if 'age' in extracted:
            profile.age = extracted['age']
        if 'gender' in extracted:
            profile.gender = extracted['gender']
        if 'activity_level' in extracted:
            profile.activity_level = extracted['activity_level']
        if 'health_condition' in extracted:
            profile.health_condition = extracted['health_condition']
        if 'dietary_preference' in extracted:
            profile.dietary_preference = extracted['dietary_preference']
        if 'allergies' in extracted:
            profile.allergies = extracted['allergies']
        return profile
