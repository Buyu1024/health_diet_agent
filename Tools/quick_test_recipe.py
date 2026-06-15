# 批量爬取食谱营养数据（并行版）
from recipe_spider import RecipeSpider

# workers=3 表示同时开3个标签页并行爬取，可调整为 2~5
spider = RecipeSpider(headless=False, need_login=True, workers=20)

# ====== 方式1：手动指定 ID 列表 ======
# recipe_ids = [8456, 8457, 8458, 8459, 8460]

# ====== 方式2：指定 ID 范围（自动遍历） ======
# start_id = 8456
# end_id = 8456+22180
start_id = 30636
end_id = 34123
recipe_ids = list(range(start_id, end_id))

print(f"[*] 准备爬取 {len(recipe_ids)} 个食谱，ID: {recipe_ids[0]} ~ {recipe_ids[-1]}")

# parallel=True 并行爬取，parallel=False 串行爬取
spider.run(recipe_ids, save_csv=True, save_json=True, parallel=True)
