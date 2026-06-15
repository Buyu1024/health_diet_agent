"""
nutridata.cn 食谱详情页爬虫（并行版）
目标网站: https://www.nutridata.cn/database/dishes/{id}
爬取字段: 菜名、食材、能量、蛋白质、脂肪、碳水化合物、维生素、矿物质
支持多标签页并行爬取，大幅提升速度
"""

import re
import json
import csv
import asyncio
import random
import time as time_module
from pathlib import Path
from typing import List, Dict, Optional

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("[!] 请先安装 playwright: pip install playwright")
    print("[!] 然后运行: playwright install chromium")
    raise


# 维生素字段列表：当这些字段同时为空时，说明登录已过期
VITAMIN_FIELDS = [
    "vitamin_a", "vitamin_d", "vitamin_e", "vitamin_k",
    "vitamin_b1", "vitamin_b2", "vitamin_b6", "vitamin_b12",
    "niacin", "folic_acid", "vitamin_c", "biotin", "total_choline",
]

# 营养字段映射（中文名 -> 英文键名）
NUTRIENT_MAPPINGS = {
    "能量": "calorie",
    "蛋白质": "protein",
    "脂肪": "fat",
    "碳水化合物": "carbohydrate",
    "维生素A": "vitamin_a",
    "维生素D": "vitamin_d",
    "维生素E": "vitamin_e",
    "维生素K": "vitamin_k",
    "硫胺素": "vitamin_b1",
    "核黄素": "vitamin_b2",
    "维生素B6": "vitamin_b6",
    "维生素B12": "vitamin_b12",
    "烟酸": "niacin",
    "叶酸": "folic_acid",
    "维生素C": "vitamin_c",
    "生物素": "biotin",
    "总胆碱": "total_choline",
    "钠": "sodium",
    "钾": "potassium",
    "镁": "magnesium",
    "铁": "iron",
    "锌": "zinc",
    "钙": "calcium",
    "磷": "phosphorus",
    "硒": "selenium",
    "碘": "iodine",
    "铜": "copper",
    "锰": "manganese",
}

# 正则模式列表（用于从正文提取营养数据）
NUTRIENT_PATTERNS = [
    (r'能量[：:\s]*([\d.]+\s*[a-zA-Z]*)', '能量'),
    (r'蛋白质[：:\s]*([\d.]+\s*[a-zA-Z]*)', '蛋白质'),
    (r'脂肪[：:\s]*([\d.]+\s*[a-zA-Z]*)', '脂肪'),
    (r'碳水化合物[：:\s]*([\d.]+\s*[a-zA-Z]*)', '碳水化合物'),
    (r'维生素A[：:\s]*([\d.]+\s*[a-zA-Z]*)', '维生素A'),
    (r'维生素D[：:\s]*([\d.]+\s*[a-zA-Z]*)', '维生素D'),
    (r'维生素E[：:\s]*([\d.]+\s*[a-zA-Z]*)', '维生素E'),
    (r'维生素K[：:\s]*([\d.]+\s*[a-zA-Z]*)', '维生素K'),
    (r'硫胺素[：:\s]*([\d.]+\s*[a-zA-Z]*)', '硫胺素'),
    (r'核黄素[：:\s]*([\d.]+\s*[a-zA-Z]*)', '核黄素'),
    (r'维生素B6[：:\s]*([\d.]+\s*[a-zA-Z]*)', '维生素B6'),
    (r'维生素B12[：:\s]*([\d.]+\s*[a-zA-Z]*)', '维生素B12'),
    (r'烟酸[：:\s]*([\d.]+\s*[a-zA-Z]*)', '烟酸'),
    (r'叶酸[：:\s]*([\d.]+\s*[a-zA-Z]*)', '叶酸'),
    (r'维生素C[：:\s]*([\d.]+\s*[a-zA-Z]*)', '维生素C'),
    (r'生物素[：:\s]*([\d.]+\s*[a-zA-Z]*)', '生物素'),
    (r'总胆碱[：:\s]*([\d.]+\s*[a-zA-Z]*)', '总胆碱'),
    (r'钠[：:\s]*([\d.]+\s*[a-zA-Z]*)', '钠'),
    (r'钾[：:\s]*([\d.]+\s*[a-zA-Z]*)', '钾'),
    (r'镁[：:\s]*([\d.]+\s*[a-zA-Z]*)', '镁'),
    (r'铁[：:\s]*([\d.]+\s*[a-zA-Z]*)', '铁'),
    (r'锌[：:\s]*([\d.]+\s*[a-zA-Z]*)', '锌'),
    (r'钙[：:\s]*([\d.]+\s*[a-zA-Z]*)', '钙'),
    (r'磷[：:\s]*([\d.]+\s*[a-zA-Z]*)', '磷'),
    (r'硒[：:\s]*([\d.]+\s*[a-zA-Z]*)', '硒'),
    (r'碘[：:\s]*([\d.]+\s*[a-zA-Z]*)', '碘'),
    (r'铜[：:\s]*([\d.]+\s*[a-zA-Z]*)', '铜'),
    (r'锰[：:\s]*([\d.]+\s*[a-zA-Z]*)', '锰'),
]


class RecipeSpider:
    """nutridata.cn 食谱详情页爬虫（并行版）"""

    BASE_URL = "https://www.nutridata.cn/database/dishes/{id}"
    LOGIN_URL = "https://www.nutridata.cn/login"

    def __init__(self, headless: bool = True, output_dir: str = "data",
                 need_login: bool = True, workers: int = 3, batch_size: int = 50):
        """
        Args:
            headless: 是否无头模式运行浏览器
            output_dir: 输出目录
            need_login: 是否需要登录
            workers: 并行标签页数量（默认3个）
            batch_size: 增量保存间隔，每爬取多少条自动保存一次（默认50）
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.need_login = need_login
        self.workers = workers
        self.batch_size = batch_size
        self.playwright = None
        self.browser = None
        self.context = None
        # 增量保存相关文件路径
        self._csv_path = self.output_dir / "recipes_nutrition（未处理）.csv"
        self._jsonl_path = self.output_dir / "recipes_nutrition.jsonl"  # JSONL格式（每行一个JSON）
        self._old_json_path = self.output_dir / "recipes_nutrition.json"  # 兼容旧版JSON数组格式
        self._csv_fields = [
            "recipe_id", "recipe_name", "ingredients",
            "calorie", "protein", "fat", "carbohydrate",
            "vitamin_a", "vitamin_d", "vitamin_e", "vitamin_k",
            "vitamin_b1", "vitamin_b2", "vitamin_b6", "vitamin_b12",
            "niacin", "folic_acid", "vitamin_c", "biotin", "total_choline",
            "sodium", "potassium", "magnesium", "iron", "zinc",
            "calcium", "phosphorus", "selenium", "iodine", "copper", "manganese",
        ]
        self._saved_count = 0  # 已增量保存的条数
        # 重新登录相关
        self._relogin_needed = False
        self._relogin_lock = asyncio.Lock()
        self._vitamin_empty_streak = 0  # 连续维生素字段为空的计数
        self._retry_counts = {}  # {recipe_id: 重试次数}，防止无限重试

    async def start_browser(self):
        """启动浏览器"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox"]
        )
        self.context = await self.browser.new_context()
        print(f"[+] 浏览器已启动（并行数: {self.workers}）")

    async def login(self):
        """手动登录（在第一个标签页中完成）"""
        if not self.need_login:
            return

        page = await self.context.new_page()
        print(f"\n[!] 需要登录，请在浏览器中完成登录...")
        print(f"[*] 跳转到登录页面: {self.LOGIN_URL}")
        await page.goto(self.LOGIN_URL, wait_until="networkidle")
        await asyncio.sleep(2)

        print("[*] 请在浏览器中输入账号密码并登录...")
        print("[*] 登录后按回车继续...")
        await asyncio.get_event_loop().run_in_executor(None, input)

        await asyncio.sleep(2)
        current_url = page.url
        if "login" in current_url.lower():
            print("[!] 登录失败，仍在登录页面")
        else:
            print("[+] 登录成功！")
        await page.close()

    async def _handle_relogin(self):
        """处理重新登录（当维生素字段全部为空时触发）"""
        async with self._relogin_lock:
            if not self._relogin_needed:
                return  # 已被其他 worker 处理完毕
            print(f"\n{'='*50}")
            print(f"[!] 检测到 13 个维生素字段全部为空，登录可能已过期")
            print(f"[!] 请在浏览器中重新登录...")
            print(f"{'='*50}")
            await self.login()
            self._relogin_needed = False
            self._vitamin_empty_streak = 0
            self._retry_counts.clear()
            print(f"[+] 重新登录完成，继续爬取...")

    @staticmethod
    def _vitamins_all_empty(recipe_data: Dict) -> bool:
        """检查所有维生素字段是否同时为空"""
        return all(field not in recipe_data for field in VITAMIN_FIELDS)

    async def close_browser(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("[+] 浏览器已关闭")

    async def parse_recipe_page(self, recipe_id: int, page) -> Dict:
        """
        在指定的 page 上解析单个食谱
        Args:
            recipe_id: 食谱ID
            page: Playwright page 对象
        Returns:
            食谱数据字典
        """
        url = self.BASE_URL.format(id=recipe_id)

        try:
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(2)

            recipe_data = {"recipe_id": recipe_id}

            # 1. 提取菜名
            try:
                recipe_name = None
                name_selectors = [
                    ".info-title.ellipsis-1",
                    ".info-title",
                    ".header-info .info-title",
                    ".header .info-title",
                    ".fixed-title-bar",
                ]
                for selector in name_selectors:
                    elem = await page.query_selector(selector)
                    if elem:
                        text = (await elem.inner_text()).strip()
                        if text:
                            text = re.sub(r'\d+\.?\d*g$', '', text).strip()
                            if text and text not in ["基本信息", "菜肴详情"]:
                                recipe_name = text
                                break

                if recipe_name:
                    recipe_data["recipe_name"] = recipe_name
                else:
                    return {"recipe_id": recipe_id, "error": "未能提取菜名"}
            except Exception as e:
                return {"recipe_id": recipe_id, "error": f"菜名提取失败: {e}"}

            # 2. 提取食材
            try:
                ingredients = []
                ingredient_selectors = [
                    "[class*='ingredient']",
                    "[class*='tag']",
                    "span[class*='material']",
                ]
                for selector in ingredient_selectors:
                    elems = await page.query_selector_all(selector)
                    if elems:
                        for elem in elems:
                            text = (await elem.inner_text()).strip()
                            if text and ("：" in text or ":" in text) and any(c.isdigit() for c in text):
                                ingredients.append(text)
                        if ingredients:
                            break
                if ingredients:
                    recipe_data["ingredients"] = ", ".join(ingredients)
            except:
                pass

            # 3. 提取所有营养数据
            try:
                nutrient_data = {}

                # 方法1：表格
                rows = await page.query_selector_all("table tr")
                for row in rows:
                    try:
                        cells = await row.query_selector_all("td, th")
                        if len(cells) >= 2:
                            for i in range(0, len(cells) - 1, 2):
                                key = (await cells[i].inner_text()).strip()
                                value = (await cells[i + 1].inner_text()).strip()
                                if key and value:
                                    nutrient_data[key] = value
                    except:
                        continue

                # 方法2：header-info 区域
                header_info = await page.query_selector(".header-info")
                if header_info:
                    info_text = await header_info.inner_text()
                    pattern = r'([\u4e00-\u9fa5]+)\uff1a([\d.]+\s*[a-zA-Z\u03bc]+)'
                    matches = re.findall(pattern, info_text)
                    for name, value in matches:
                        nutrient_data[name] = value

                # 方法3：item-chart-title 元素
                chart_items = await page.query_selector_all(".item-chart-title")
                for item in chart_items:
                    try:
                        text = (await item.inner_text()).strip()
                        lines = text.split('\n')
                        if len(lines) >= 2:
                            name = lines[0].strip()
                            value = lines[1].strip()
                            if name and value:
                                nutrient_data[name] = value
                    except:
                        continue

                # 方法4：正则从正文提取
                body_text = await page.inner_text("body")
                for pattern, name in NUTRIENT_PATTERNS:
                    if name not in nutrient_data:
                        match = re.search(pattern, body_text)
                        if match:
                            nutrient_data[name] = match.group(1).strip()

                # 映射字段
                for cn_name, en_key in NUTRIENT_MAPPINGS.items():
                    if cn_name in nutrient_data:
                        recipe_data[en_key] = nutrient_data[cn_name]

                extracted_count = len([k for k in NUTRIENT_MAPPINGS.values() if k in recipe_data])
                recipe_data["_nutrient_count"] = extracted_count

            except Exception as e:
                print(f"    [!] ID {recipe_id} 营养数据提取失败: {e}")

            return recipe_data

        except Exception as e:
            return {"recipe_id": recipe_id, "error": str(e)}

    async def _worker(self, worker_id: int, task_queue: asyncio.Queue,
                      results: list, stats: dict, unsaved_batch: list):
        """
        单个并行工作线程
        Args:
            worker_id: 工作线程编号
            task_queue: 任务队列
            results: 结果列表
            stats: 统计信息
            unsaved_batch: 未保存的批次数据缓冲区
        """
        # 每个 worker 有自己的标签页
        page = await self.context.new_page()

        while True:
            try:
                recipe_id = task_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            try:
                recipe_data = await self.parse_recipe_page(recipe_id, page)

                if "error" in recipe_data or not recipe_data.get("recipe_name"):
                    stats["fail"] += 1
                    print(f"    [Worker-{worker_id}] ID {recipe_id} ✗ 无效/跳过")
                else:
                    nutrient_count = recipe_data.pop("_nutrient_count", 0)
                    vitamins_empty = self._vitamins_all_empty(recipe_data)

                    # 检测维生素字段是否全部为空（说明登录已过期）
                    if vitamins_empty:
                        self._vitamin_empty_streak += 1
                        retry = self._retry_counts.get(recipe_id, 0)

                        if retry >= 2:
                            # 重试超过2次，放弃该条
                            stats["fail"] += 1
                            print(f"    [Worker-{worker_id}] ID {recipe_id} ✗ 维生素字段全空且重试{retry}次，放弃")
                        elif self._vitamin_empty_streak >= 2:
                            # 连续2条维生素字段全空，触发重新登录
                            self._relogin_needed = True
                            print(f"    [Worker-{worker_id}] ID {recipe_id} ⚠ 维生素字段全空，连续{self._vitamin_empty_streak}条，需要重新登录")
                            await self._handle_relogin()
                            # 将当前 ID 放回队列重试
                            self._retry_counts[recipe_id] = retry + 1
                            task_queue.put_nowait(recipe_id)
                        else:
                            # 第1条维生素全空，可能数据本身就不含维生素，正常保存
                            results.append(recipe_data)
                            unsaved_batch.append(recipe_data)
                            stats["success"] += 1
                            print(f"    [Worker-{worker_id}] ID {recipe_id} ✓ {recipe_data['recipe_name']} ({nutrient_count}个字段，维生素为空)")
                    else:
                        # 维生素字段正常，重置连续计数
                        self._vitamin_empty_streak = 0
                        results.append(recipe_data)
                        unsaved_batch.append(recipe_data)
                        stats["success"] += 1
                        print(f"    [Worker-{worker_id}] ID {recipe_id} ✓ {recipe_data['recipe_name']} ({nutrient_count}个字段)")

                    # 达到批次大小时触发增量保存
                    if len(unsaved_batch) >= self.batch_size:
                        self._incremental_save(list(unsaved_batch), results)
                        unsaved_batch.clear()

            except Exception as e:
                stats["fail"] += 1
                print(f"    [Worker-{worker_id}] ID {recipe_id} ✗ 异常: {e}")

            # 随机延迟
            await asyncio.sleep(random.uniform(0.5, 1.5))

            task_queue.task_done()

        await page.close()

    async def crawl_recipes_parallel(self, recipe_ids: List[int],
                                     existing_data: Dict[int, Dict] = None) -> List[Dict]:
        """
        并行爬取多个食谱
        Args:
            recipe_ids: 食谱ID列表
            existing_data: 已有数据（用于断点续爬跳过）
        Returns:
            食谱数据列表
        """
        existing_data = existing_data or {}

        # 跳过已爬取的 ID
        pending_ids = [rid for rid in recipe_ids if rid not in existing_data]
        if len(pending_ids) < len(recipe_ids):
            skipped = len(recipe_ids) - len(pending_ids)
            print(f"[*] 跳过已爬取的 {skipped} 个 ID，剩余 {len(pending_ids)} 个待爬取")

        if not pending_ids:
            print("[+] 所有 ID 均已爬取，无需重复爬取")
            return list(existing_data.values())

        task_queue = asyncio.Queue()
        for rid in pending_ids:
            task_queue.put_nowait(rid)

        # 从已有数据初始化结果列表
        results = list(existing_data.values())
        stats = {"success": 0, "fail": 0}
        unsaved_batch = []  # 增量保存缓冲区

        print(f"\n[*] 开始并行爬取 {len(pending_ids)} 个食谱（{self.workers} 个标签页）")
        start_time = time_module.time()

        # 创建多个 worker 并行工作
        workers = [
            asyncio.create_task(self._worker(i, task_queue, results, stats, unsaved_batch))
            for i in range(1, self.workers + 1)
        ]

        # 等待所有任务完成
        await task_queue.join()
        await asyncio.gather(*workers)

        # 保存最后不满一批的剩余数据
        if unsaved_batch:
            self._incremental_save(list(unsaved_batch), results)
            unsaved_batch.clear()

        elapsed = time_module.time() - start_time
        print(f"\n[统计] 本次爬取 {len(pending_ids)} 个 ID，"
              f"成功 {stats['success']} 个，失败 {stats['fail']} 个，"
              f"耗时 {elapsed:.1f} 秒")

        return results

    async def crawl_recipes_serial(self, recipe_ids: List[int],
                                   existing_data: Dict[int, Dict] = None) -> List[Dict]:
        """串行爬取（备用）"""
        existing_data = existing_data or {}
        pending_ids = [rid for rid in recipe_ids if rid not in existing_data]
        if len(pending_ids) < len(recipe_ids):
            skipped = len(recipe_ids) - len(pending_ids)
            print(f"[*] 跳过已爬取的 {skipped} 个 ID，剩余 {len(pending_ids)} 个待爬取")

        if not pending_ids:
            print("[+] 所有 ID 均已爬取，无需重复爬取")
            return list(existing_data.values())

        page = await self.context.new_page()
        all_recipes = list(existing_data.values())
        unsaved_batch = []
        success = 0
        fail = 0
        idx = 0
        total = len(pending_ids)

        while idx < total:
            recipe_id = pending_ids[idx]
            print(f"[*] [{idx + 1}/{total}] ID: {recipe_id}")
            recipe_data = await self.parse_recipe_page(recipe_id, page)

            if "error" in recipe_data or not recipe_data.get("recipe_name"):
                fail += 1
                print(f"    ✗ 无效/跳过")
            else:
                nutrient_count = recipe_data.pop("_nutrient_count", None) or 0
                vitamins_empty = self._vitamins_all_empty(recipe_data)

                # 检测维生素字段是否全部为空（说明登录已过期）
                if vitamins_empty:
                    self._vitamin_empty_streak += 1
                    retry = self._retry_counts.get(recipe_id, 0)

                    if retry >= 2:
                        fail += 1
                        print(f"    ✗ 维生素字段全空且重试{retry}次，放弃")
                        await asyncio.sleep(random.uniform(1.0, 2.5))
                        idx += 1
                        continue
                    elif self._vitamin_empty_streak >= 2:
                        self._relogin_needed = True
                        print(f"    ⚠ 维生素字段全空，连续{self._vitamin_empty_streak}条，需要重新登录")
                        await self._handle_relogin()
                        self._retry_counts[recipe_id] = retry + 1
                        # 不递增 idx，重试当前 ID
                        continue
                    else:
                        all_recipes.append(recipe_data)
                        unsaved_batch.append(recipe_data)
                        success += 1
                        print(f"    ✓ {recipe_data['recipe_name']} ({nutrient_count}个字段，维生素为空)")
                else:
                    self._vitamin_empty_streak = 0
                    all_recipes.append(recipe_data)
                    unsaved_batch.append(recipe_data)
                    success += 1
                    print(f"    ✓ {recipe_data['recipe_name']} ({nutrient_count}个字段)")

                # 达到批次大小时触发增量保存
                if len(unsaved_batch) >= self.batch_size:
                    self._incremental_save(list(unsaved_batch), all_recipes)
                    unsaved_batch.clear()

            await asyncio.sleep(random.uniform(1.0, 2.5))
            idx += 1

        # 保存最后不满一批的剩余数据
        if unsaved_batch:
            self._incremental_save(list(unsaved_batch), all_recipes)
            unsaved_batch.clear()

        await page.close()
        print(f"\n[统计] 本次爬取 {len(pending_ids)} 个，成功 {success}，失败 {fail}")
        return all_recipes

    def load_existing_data(self) -> Dict[int, Dict]:
        """
        加载已有的爬取数据（用于断点续爬）
        优先读取 JSONL 格式，兼容旧版 JSON 数组格式
        Returns:
            {recipe_id: recipe_data} 字典
        """
        existing = {}

        # 优先读取 JSONL 格式（追加模式产生的文件）
        if self._jsonl_path.exists():
            try:
                with open(self._jsonl_path, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                            rid = item.get("recipe_id")
                            if rid is not None:
                                existing[rid] = item
                        except json.JSONDecodeError:
                            pass
                print(f"[+] 已从 JSONL 加载 {len(existing)} 条历史数据（断点续爬）")
            except Exception as e:
                print(f"[!] 加载 JSONL 数据失败: {e}")

        # 兼容旧版 JSON 数组格式
        if not existing and self._old_json_path.exists():
            try:
                with open(self._old_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    rid = item.get("recipe_id")
                    if rid is not None:
                        existing[rid] = item
                print(f"[+] 已从旧版 JSON 加载 {len(existing)} 条历史数据（断点续爬）")
            except Exception as e:
                print(f"[!] 加载旧版 JSON 数据失败: {e}")

        return existing

    def _append_csv(self, recipes: List[Dict]):
        """增量追加数据到 CSV 文件（真正的追加写入，不重写已有数据）"""
        if not recipes:
            return

        file_exists = self._csv_path.exists() and self._csv_path.stat().st_size > 0

        if not file_exists:
            # 文件不存在：创建文件，写表头 + 数据
            all_fields = set()
            for r in recipes:
                all_fields.update(r.keys())
            fieldnames = [f for f in self._csv_fields if f in all_fields]
            fieldnames.extend(sorted(f for f in all_fields if f not in fieldnames))

            with open(self._csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(recipes)
        else:
            # 文件已存在：读取表头，直接追加新行
            with open(self._csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or self._csv_fields

            with open(self._csv_path, "a", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writerows(recipes)

    def _append_jsonl(self, recipes: List[Dict]):
        """增量追加数据到 JSONL 文件（每行一个 JSON 对象，真正的追加写入）"""
        if not recipes:
            return
        with open(self._jsonl_path, "a", encoding="utf-8") as f:
            for recipe in recipes:
                f.write(json.dumps(recipe, ensure_ascii=False) + "\n")

    def _incremental_save(self, new_recipes: List[Dict], all_recipes: List[Dict]):
        """
        增量保存：CSV 和 JSONL 均采用追加写入模式
        Args:
            new_recipes: 本批次新增的数据
            all_recipes: 当前所有已爬取的数据（仅用于统计显示）
        """
        if not new_recipes:
            return

        # CSV 追加写入
        self._append_csv(new_recipes)

        # JSONL 追加写入
        self._append_jsonl(new_recipes)

        self._saved_count += len(new_recipes)
        print(f"    [保存] 追加写入 {len(new_recipes)} 条，累计 {self._saved_count}/{len(all_recipes)} 条")

    def save_to_csv(self, recipes: List[Dict], filename: str = "recipes_nutrition（未处理）.csv"):
        """保存为 CSV 文件（全量覆盖）"""
        filepath = self.output_dir / filename
        if not recipes:
            print("[!] 没有数据可保存")
            return

        all_fields = set()
        for recipe in recipes:
            all_fields.update(recipe.keys())

        fieldnames = [f for f in self._csv_fields if f in all_fields]
        fieldnames.extend([f for f in sorted(all_fields) if f not in fieldnames])

        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(recipes)

        print(f"\n[+] 数据已保存到: {filepath}")
        print(f"[+] 共 {len(recipes)} 条记录，{len(fieldnames)} 个字段")

    def save_to_json(self, recipes: List[Dict], filename: str = "recipes_nutrition.jsonl"):
        """保存为 JSONL 文件（全量覆盖，每行一个 JSON 对象）"""
        filepath = self.output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            for recipe in recipes:
                f.write(json.dumps(recipe, ensure_ascii=False) + "\n")
        print(f"[+] 数据已保存到: {filepath}")

    def run(self, recipe_ids: List[int], save_csv: bool = True,
            save_json: bool = True, parallel: bool = True):
        """
        执行完整爬取流程（自动运行异步事件循环）
        Args:
            recipe_ids: 食谱ID列表
            save_csv: 是否保存为 CSV
            save_json: 是否保存为 JSON
            parallel: 是否并行爬取（默认True）
        """
        return asyncio.run(
            self._async_run(recipe_ids, save_csv, save_json, parallel)
        )

    async def _async_run(self, recipe_ids, save_csv, save_json, parallel):
        """异步执行入口"""
        try:
            await self.start_browser()

            if self.need_login:
                await self.login()

            # 加载已有数据，支持断点续爬
            existing_data = self.load_existing_data()

            if parallel:
                recipes = await self.crawl_recipes_parallel(recipe_ids, existing_data)
            else:
                recipes = await self.crawl_recipes_serial(recipe_ids, existing_data)

            # 最终全量覆盖保存（确保数据完整一致）
            if save_csv:
                self.save_to_csv(recipes)
            if save_json:
                self.save_to_json(recipes)  # JSONL 格式全量覆盖

            print(f"\n{'=' * 50}")
            print(f"[✓] 爬取完成！共获取 {len(recipes)} 个食谱的营养数据")
            return recipes

        except KeyboardInterrupt:
            print(f"\n[!] 用户中断！已爬取 {self._saved_count} 条数据已保存到文件")
            print(f"[!] 下次运行将自动从断点继续")
            raise

        except Exception as e:
            print(f"\n[✗] 爬取失败: {e}")
            if self._saved_count > 0:
                print(f"[i] 已增量保存 {self._saved_count} 条数据，下次运行将自动续爬")
            raise

        finally:
            await self.close_browser()


if __name__ == "__main__":
    spider = RecipeSpider(headless=False, output_dir="data", workers=3)
    spider.run([8456, 8457, 8458], save_csv=True, save_json=True, parallel=True)
