# 快速测试版本 - 爬取指定页数
from nutridata_spider import NutriDataSpider

spider = NutriDataSpider(headless=False)
# 手动指定要爬取的页数
spider.run(max_pages=2, save_csv=True, save_json=True)
