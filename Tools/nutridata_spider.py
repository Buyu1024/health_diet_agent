"""
nutridata.cn 食物营养数据库爬虫
目标网站: https://www.nutridata.cn/database
爬取字段: 名称(Food Name)、食部(Edible %)、水分(WaterRate %)、能量(Calorie kcal)、蛋白质(Protein g)、脂肪(Fat g)、碳水化合物(Carbohydrate g)
"""

import time
import random
import json
import csv
from pathlib import Path
from typing import List, Dict, Optional

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[!] 请先安装 playwright: pip install playwright")
    print("[!] 然后运行: playwright install chromium")
    raise


class NutriDataSpider:
    """nutridata.cn 食物营养数据爬虫"""
    
    BASE_URL = "https://www.nutridata.cn/database/list?id=1&date=1780829310341"
    
    # 目标字段映射（中文 -> 英文键名）
    FIELDS = {
        "名称": "food_name",
        "食部": "edible_percent",
        "水分": "water_rate",
        "能量": "calorie",
        "蛋白质": "protein",
        "脂肪": "fat",
        "碳水化合物": "carbohydrate",
        # 维生素类
        "维生素A": "vitamin_a",
        "VitaminA": "vitamin_a",
        "硫胺素": "vitamin_b1",
        "VitaminB1": "vitamin_b1",
        "核黄素": "vitamin_b2",
        "VitaminB2": "vitamin_b2",
        "维生素B6": "vitamin_b6",
        "VitaminB6": "vitamin_b6",
        "维生素B12": "vitamin_b12",
        "VitaminB12": "vitamin_b12",
        "维生素D": "vitamin_d",
        "VitaminD": "vitamin_d",
        "维生素K": "vitamin_k",
        "VitaminK": "vitamin_k",
        "烟酸": "niacin",
        "Niacin": "niacin",
        "维生素C": "vitamin_c",
        "VitaminC": "vitamin_c",
        "维生素E": "vitamin_e",
        "VitaminE": "vitamin_e",
        "叶酸": "folic_acid",
        "FolicAcid": "folic_acid",
        "生物素": "biotin",
        "Biotin": "biotin",
        "泛酸": "pantothenic_acid",
        "PantothenicAcid": "pantothenic_acid",
        "总胆碱": "total_choline",
        "TotalCholine": "total_choline",
        # 矿物质类
        "钙": "calcium",
        "Ca": "calcium",
        "磷": "phosphorus",
        "Phosphorus": "phosphorus",
        "钾": "potassium",
        "Kalium": "potassium",
        "镁": "magnesium",
        "Mg": "magnesium",
        "铁": "iron",
        "Fe": "iron",
        "锌": "zinc",
        "Zn": "zinc",
        "硒": "selenium",
        "Se": "selenium",
    }
    
    def __init__(self, headless: bool = True, output_dir: str = "data"):
        """
        Args:
            headless: 是否无头模式运行浏览器
            output_dir: 输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.page = None
    
    def start_browser(self):
        """启动浏览器"""
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox"]
        )
        self.page = self.browser.new_page()
        print("[+] 浏览器已启动")
    
    def close_browser(self):
        """关闭浏览器"""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        print("[+] 浏览器已关闭")
    
    def navigate_to_database(self):
        """访问数据库页面"""
        print(f"[*] 访问: {self.BASE_URL}")
        self.page.goto(self.BASE_URL, wait_until="networkidle")
        time.sleep(2)
        print("[+] 页面加载完成")
    
    def parse_table(self) -> List[Dict]:
        """
        解析当前页面的表格数据
        Returns:
            食物数据列表
        """
        foods = []
        
        try:
            # 等待表格加载
            self.page.wait_for_selector("table", timeout=10000)
            
            # 获取所有数据行
            rows = self.page.query_selector_all("table tbody tr")
            print(f"[*] 当前页找到 {len(rows)} 条数据")
            
            # 打印第一行调试
            if len(rows) > 0:
                debug_cols = rows[0].query_selector_all("td")
                print(f"[DEBUG] 第一行有 {len(debug_cols)} 列")
                for i, col in enumerate(debug_cols):
                    print(f"  列{i}: [{col.inner_text().strip()}]")
            
            for row in rows:
                try:
                    cols = row.query_selector_all("td")
                    if len(cols) < 10:  # 至少10列
                        continue
                    
                    # 根据调试输出，表格结构是11列：
                    # [空, 空, 食部, 水分, 能量, 蛋白质, 脂肪, 碳水化合物, 钠, 名称, 空]
                    # 索引:  0    1    2     3     4      5      6      7       8    9     10
                    food_name = cols[9].inner_text().strip()
                    if not food_name:
                        continue
                    
                    food = {
                        "food_name": food_name,
                        "edible_percent": cols[2].inner_text().strip(),
                        "water_rate": cols[3].inner_text().strip(),
                        "calorie": cols[4].inner_text().strip(),
                        "protein": cols[5].inner_text().strip(),
                        "fat": cols[6].inner_text().strip(),
                        "carbohydrate": cols[7].inner_text().strip(),
                    }
                    
                    foods.append(food)
                except Exception as e:
                    print(f"[!] 解析行数据失败: {e}")
                    continue
            
        except Exception as e:
            print(f"[!] 表格加载失败: {e}")
        
        return foods
    
    def get_total_pages(self) -> int:
        """获取总页数"""
        try:
            # 尝试多种分页组件选择器
            selectors = [
                ".pagination",
                "[class*='pagination']",
                "[class*='page']",
                "ul[class*='page']",
                "div[class*='page']",
                ".pager",
                "[class*='pager']",
                "nav",
            ]
            
            for selector in selectors:
                pagination = self.page.query_selector(selector)
                if pagination:
                    all_elements = pagination.query_selector_all("a, button, span")
                    page_numbers = []
                    
                    for elem in all_elements:
                        try:
                            text = elem.inner_text().strip()
                            if text.isdigit() and 1 <= int(text) <= 1000:
                                page_numbers.append(int(text))
                        except:
                            continue
                    
                    if page_numbers:
                        total = max(page_numbers)
                        print(f"[+] 检测到总页数: {total}")
                        return total
            
            # 如果找不到分页组件，尝试通过页面信息推断
            print("[*] 正在分析页面内容以估算页数...")
            
            # 查找包含"共X条"或"total"的元素
            body_text = self.page.inner_text("body")
            import re
            
            # 尝试匹配"共X条"格式
            match = re.search(r"共\s*(\d+)\s*条", body_text)
            if not match:
                match = re.search(r"total[:\s]*(\d+)", body_text, re.IGNORECASE)
            
            if match:
                total_items = int(match.group(1))
                estimated_pages = max(1, (total_items + 19) // 20)  # 假设每页20条
                print(f"[+] 页面显示共 {total_items} 条数据，估算需要 {estimated_pages} 页")
                return estimated_pages
            
            # 如果仍然找不到，尝试查找页面底部的文本
            footer_text = self.page.inner_text("footer, [class*='footer'], [class*='bottom']")
            if footer_text:
                match = re.search(r"共\s*(\d+)", footer_text)
                if match:
                    total_items = int(match.group(1))
                    estimated_pages = max(1, (total_items + 19) // 20)
                    print(f"[+] 底部显示共 {total_items} 条数据，估算需要 {estimated_pages} 页")
                    return estimated_pages
            
            print("[!] 无法获取总页数，默认爬取1页（如需爬取更多页请手动设置 max_pages）")
            return 1
            
        except Exception as e:
            print(f"[!] 获取总页数失败: {e}，默认爬取1页")
            return 1
    
    def go_to_page(self, page_num: int):
        """跳转到指定页"""
        try:
            # 尝试查找页码输入框
            page_input = self.page.query_selector("input[type='number'], input[class*='page']")
            if page_input:
                page_input.fill(str(page_num))
                self.page.keyboard.press("Enter")
                time.sleep(2)
                print(f"[*] 跳转到第 {page_num} 页")
                return
            
            # 尝试点击下一页
            current = self.get_current_page()
            while current < page_num:
                next_btn = self.page.query_selector(".next, [class*='next'] a, text='下一页'")
                if next_btn:
                    next_btn.click()
                    time.sleep(2)
                    current = self.get_current_page()
                    print(f"[*] 跳转到第 {current} 页")
                else:
                    break
        except Exception as e:
            print(f"[!] 无法跳转到第 {page_num} 页: {e}")
    
    def get_current_page(self) -> int:
        """获取当前页码"""
        try:
            active = self.page.query_selector(".active, [class*='active']")
            if active:
                text = active.inner_text().strip()
                if text.isdigit():
                    return int(text)
        except:
            pass
        return 1
    
    def crawl_all_pages(self, max_pages: Optional[int] = None) -> List[Dict]:
        """
        爬取所有页面数据
        Args:
            max_pages: 最大爬取页数（None表示自动检测）
        Returns:
            所有食物数据
        """
        all_foods = []
        
        # 如果指定了 max_pages，直接使用
        if max_pages:
            total_pages = max_pages
            print(f"[*] 使用手动指定页数: {total_pages}")
        else:
            total_pages = self.get_total_pages()
        
        print(f"[*] 总页数: {total_pages}")
        
        # 先爬取第1页
        print(f"\n{'='*50}")
        print(f"[*] 正在爬取第 1/{total_pages} 页")
        foods = self.parse_table()
        all_foods.extend(foods)
        print(f"[+] 本页获取 {len(foods)} 条，累计 {len(all_foods)} 条")
        
        # 记录已爬取的名称，用于去重
        crawled_names = {food['food_name'] for food in all_foods}
        
        # 检查是否有"加载更多"或"下一页"按钮
        has_next = True
        while has_next and len(all_foods) < (total_pages * 20):
            try:
                # 尝试查找各种"下一页"或"加载更多"的按钮
                next_selectors = [
                    "text=下一页",
                    "text=加载更多",
                    ".next",
                    "[class*='next']",
                    ".load-more",
                    "[class*='load-more']",
                    "button:has-text('下一页')",
                    "button:has-text('加载更多')",
                ]
                
                next_btn = None
                for selector in next_selectors:
                    try:
                        next_btn = self.page.query_selector(selector)
                        if next_btn and next_btn.is_visible():
                            break
                    except:
                        continue
                
                if not next_btn or not next_btn.is_visible():
                    print("[+] 没有更多数据了")
                    break
                
                # 点击下一页
                print(f"\n{'='*50}")
                print(f"[*] 正在爬取第 {len(all_foods)//20 + 1} 页")
                next_btn.click()
                time.sleep(2)
                
                # 解析新数据
                foods = self.parse_table()
                
                # 去重：只添加新的食物
                new_foods = [f for f in foods if f['food_name'] not in crawled_names]
                if len(new_foods) == 0:
                    print("[+] 没有更多新数据了")
                    break
                
                all_foods.extend(new_foods)
                crawled_names.update(f['food_name'] for f in new_foods)
                print(f"[+] 本页获取 {len(new_foods)} 条新数据，累计 {len(all_foods)} 条")
                
                # 检查是否达到指定页数
                current_page = len(all_foods) // 20 + 1
                if max_pages and current_page >= max_pages:
                    print(f"[+] 已达到指定页数 {max_pages}")
                    break
                
                # 随机延迟
                delay = random.uniform(1.0, 2.0)
                time.sleep(delay)
                
            except Exception as e:
                print(f"[!] 翻页失败: {e}")
                break
        
        return all_foods
    
    def save_to_csv(self, foods: List[Dict], filename: str = "nutridata_foods.csv"):
        """保存为 CSV 文件"""
        filepath = self.output_dir / filename
        
        if not foods:
            print("[!] 没有数据可保存")
            return
        
        # 动态获取所有字段
        all_fields = set()
        for food in foods:
            all_fields.update(food.keys())
        
        # 确保基础字段在前
        base_fields = [
            "food_name", "edible_percent", "water_rate", "calorie",
            "protein", "fat", "carbohydrate",
            # 维生素
            "vitamin_a", "vitamin_b1", "vitamin_b2", "vitamin_b6",
            "vitamin_b12", "vitamin_d", "vitamin_k", "niacin",
            "vitamin_c", "vitamin_e", "folic_acid", "biotin",
            "pantothenic_acid", "total_choline",
            # 矿物质
            "calcium", "phosphorus", "potassium", "magnesium",
            "iron", "zinc", "selenium",
        ]
        fieldnames = [f for f in base_fields if f in all_fields]
        fieldnames.extend([f for f in sorted(all_fields) if f not in fieldnames])
        
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(foods)
        
        print(f"[+] 数据已保存到: {filepath}")
        print(f"[+] 共 {len(foods)} 条记录，{len(fieldnames)} 个字段")
    
    def save_to_json(self, foods: List[Dict], filename: str = "nutridata_foods.json"):
        """保存为 JSON 文件"""
        filepath = self.output_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(foods, f, ensure_ascii=False, indent=2)
        
        print(f"[+] 数据已保存到: {filepath}")
        if foods:
            print(f"[+] 共 {len(foods)} 条记录，字段: {list(foods[0].keys())}")
    
    def run(self, max_pages: Optional[int] = None, save_csv: bool = True, save_json: bool = True):
        """
        执行完整爬取流程
        Args:
            max_pages: 最大爬取页数
            save_csv: 是否保存为 CSV
            save_json: 是否保存为 JSON
        """
        try:
            self.start_browser()
            self.navigate_to_database()
            
            foods = self.crawl_all_pages(max_pages=max_pages)
            
            if save_csv:
                self.save_to_csv(foods)
            if save_json:
                self.save_to_json(foods)
            
            print(f"\n{'='*50}")
            print(f"[✓] 爬取完成！共获取 {len(foods)} 条食物数据")
            
            return foods
        
        except Exception as e:
            print(f"\n[✗] 爬取失败: {e}")
            raise
        
        finally:
            self.close_browser()


def main():
    """主函数"""
    spider = NutriDataSpider(
        headless=False,  # 设为 True 可无头运行
        output_dir="data"
    )
    
    # 爬取前 5 页测试
    spider.run(max_pages=5, save_csv=True, save_json=True)


if __name__ == "__main__":
    main()
