# nutridata.cn 食物营养数据库爬虫

## 功能说明

自动爬取 https://www.nutridata.cn/database 中的食物营养数据，提取以下 7 个字段：

| 字段 | 说明 | 单位 |
|------|------|------|
| 名称 | Food Name | - |
| 食部 | Edible | % |
| 水分 | WaterRate | % |
| 能量 | Calorie | kcal |
| 蛋白质 | Protein | g |
| 脂肪 | Fat | g |
| 碳水化合物 | Carbohydrate | g |

## 安装依赖

```powershell
cd D:\PythonProject\health_diet_agent\Tools
pip install -r requirements_spider.txt
```

> Chrome 浏览器会自动下载驱动，无需手动配置

## 使用方法

### 1. 快速测试（只爬第1页）

```powershell
python quick_test.py
```

### 2. 完整爬取（所有页面）

```powershell
python nutridata_spider.py
```

### 3. 自定义爬取

```python
from nutridata_spider import NutriDataSpider

spider = NutriDataSpider(
    headless=True,        # True=无头模式, False=显示浏览器
    output_dir="data"     # 输出目录
)

# 爬取前10页
spider.run(max_pages=10, save_csv=True, save_json=True)
```

## 输出文件

- `data/nutridata_foods.csv` - CSV 格式
- `data/nutridata_foods.json` - JSON 格式

## 注意事项

1. **反爬策略**：已内置随机延迟（1.5-3秒），降低被封风险
2. **浏览器**：需要安装 Chrome 浏览器
3. **网络**：确保能访问 nutridata.cn
4. **数据量**：如果网站数据量大，建议分批爬取

## 爬取的数据示例

```json
[
  {
    "food_name": "小麦",
    "edible_percent": "100",
    "water_rate": "10.0",
    "calorie": "338",
    "protein": "11.9",
    "fat": "1.3",
    "carbohydrate": "75.2"
  },
  {
    "food_name": "五谷香",
    "edible_percent": "100",
    "water_rate": "5.6",
    "calorie": "378",
    "protein": "9.9",
    "fat": "2.6",
    "carbohydrate": "78.9"
  }
]
```
