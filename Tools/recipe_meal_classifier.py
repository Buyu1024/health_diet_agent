"""
食谱三餐分类器 - 使用LLM识别菜谱属于早餐/午餐/晚餐
读取 recipes_nutrition(原文本).csv，调用通义千问对每条食谱进行三餐分类，
结果直接拼接回原CSV文件的 meal_type 列
"""

import csv
import json
import time
import os
import sys
from pathlib import Path

# 添加项目根目录到路径，以便导入 config
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import dashscope
    from dashscope import Generation
except ImportError:
    print("[!] 请先安装 dashscope: pip install dashscope")
    raise

from dotenv import load_dotenv

# 加载环境变量
load_dotenv(Path(__file__).parent.parent / ".env")

# ==================== 配置 ====================
API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
MODEL = os.getenv("QWEN_MODEL", "qwen-plus")
BATCH_SIZE = 50          # 每批处理的食谱数量
MAX_RETRIES = 3          # 单次请求最大重试次数
RETRY_DELAY = 1          # 重试间隔(秒)
PROGRESS_FILE = "data/classify_progress.json"   # 进度文件(断点续传)
INPUT_CSV = "data/recipes_nutrition(原文本).csv"          # 输入/输出为同一文件


def load_recipes(csv_path: str) -> list[dict]:
    """加载食谱CSV"""
    recipes = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            recipes.append({
                "recipe_id": row["recipe_id"],
                "recipe_name": row["recipe_name"],
                "ingredients": row["ingredients"],
                "calorie": row.get("calorie", ""),
            })
    print(f"[+] 加载 {len(recipes)} 条食谱")
    return recipes


def load_progress(progress_path: str) -> dict:
    """加载已完成的进度（支持断点续传）"""
    if os.path.exists(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"[+] 恢复进度: 已完成 {len(data)} 条")
            return data
    return {}


def save_progress(progress_path: str, results: dict):
    """保存进度"""
    os.makedirs(os.path.dirname(progress_path) or ".", exist_ok=True)
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)


def build_batch_prompt(recipes_batch: list[dict]) -> str:
    """构建批量分类的提示词"""
    recipe_list = ""
    for i, r in enumerate(recipes_batch, 1):
        recipe_list += f"{i}.{r['recipe_name']}({r['ingredients'][:60]})\n"

    return f"""判断以下菜品属于早餐、午餐、晚餐中的哪一餐。直接返回JSON数组，格式：[{{"i":1,"m":"早餐"}}]
{recipe_list}"""


def call_llm_classify(recipes_batch: list[dict]) -> list[str]:
    """调用LLM对一批食谱进行分类"""
    prompt = build_batch_prompt(recipes_batch)

    for attempt in range(MAX_RETRIES):
        try:
            response = Generation.call(
                model=MODEL,
                api_key=API_KEY,
                messages=[
                    {"role": "system", "content": "只返回JSON数组，无多余文字。"},
                    {"role": "user", "content": prompt},
                ],
                result_format="message",
                temperature=0.1,
            )

            if response.status_code != 200:
                print(f"  [!] API错误: {response.code} - {response.message}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                return ["未分类"] * len(recipes_batch)

            content = response.output.choices[0].message.content.strip()

            # 清理可能的 ```json ``` 标记
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            results = json.loads(content)

            # 构建结果列表
            meal_map = {}
            for item in results:
                idx = item.get("i", 0)
                meal_map[idx] = item.get("m", "未分类")

            return [meal_map.get(i, "未分类") for i in range(1, len(recipes_batch) + 1)]

        except json.JSONDecodeError as e:
            print(f"  [!] JSON解析失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
            print(f"      原始返回: {content[:200]}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
        except Exception as e:
            print(f"  [!] 请求异常 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))

    return ["未分类"] * len(recipes_batch)


def classify_all(recipes: list[dict], batch_size: int = BATCH_SIZE) -> dict:
    """对所有食谱进行批量分类"""
    # 加载已有进度
    progress_path = os.path.join(os.path.dirname(__file__), PROGRESS_FILE)
    results = load_progress(progress_path)

    total = len(recipes)
    done = len(results)

    if done >= total:
        print("[+] 所有食谱已分类完成，无需重新处理")
        return results

    print(f"\n[*] 开始分类: {done}/{total} (剩余 {total - done})")
    print(f"[*] 批次大小: {batch_size}, 模型: {MODEL}")
    print(f"{'=' * 60}")

    start_time = time.time()

    for i in range(0, total, batch_size):
        batch = recipes[i: i + batch_size]

        # 跳过已处理的批次
        batch_ids = [r["recipe_id"] for r in batch]
        if all(rid in results for rid in batch_ids):
            continue

        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size
        print(f"[*] 批次 {batch_num}/{total_batches} "
              f"(食谱 {i + 1}-{min(i + batch_size, total)}/{total}) ... ", end="", flush=True)

        meal_types = call_llm_classify(batch)

        # 记录结果
        for recipe, meal_type in zip(batch, meal_types):
            results[recipe["recipe_id"]] = meal_type

        print(f"完成 | {', '.join(set(meal_types))}")

        # 每5个批次保存一次进度
        if batch_num % 5 == 0:
            save_progress(progress_path, results)

        # 控制请求频率
        time.sleep(0.1)

    elapsed = time.time() - start_time
    print(f"\n[+] 分类完成! 耗时: {elapsed:.1f}秒")

    # 最终保存
    save_progress(progress_path, results)

    return results


def save_classified_csv(recipes: list[dict], results: dict, csv_path: str):
    """将分类结果直接拼接回原CSV文件，新增 meal_type 列"""
    if not recipes:
        return

    # 读取原始CSV的完整数据（含所有字段）
    full_rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        # 如果已有 meal_type 列则先移除，避免重复
        if "meal_type" in fieldnames:
            fieldnames.remove("meal_type")
        for row in reader:
            full_rows.append(row)

    # 拼接 meal_type 列到末尾
    output_fieldnames = fieldnames + ["meal_type"]

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_fieldnames)
        writer.writeheader()
        for row in full_rows:
            rid = row["recipe_id"]
            row["meal_type"] = results.get(rid, "未分类")
            writer.writerow(row)

    # 统计
    from collections import Counter
    counter = Counter(results.values())
    print(f"\n[+] 已写回原文件: {csv_path}")
    print(f"[+] 共 {len(full_rows)} 条食谱")
    print(f"[+] 分类统计:")
    for meal, count in sorted(counter.items()):
        print(f"    {meal}: {count} 条 ({count / len(results) * 100:.1f}%)")


def main():
    """主函数"""
    if not API_KEY:
        print("[!] 未配置 DASHSCOPE_API_KEY，请在 .env 文件中设置")
        sys.exit(1)

    base_dir = os.path.dirname(__file__)
    csv_path = os.path.join(base_dir, INPUT_CSV)

    if not os.path.exists(csv_path):
        print(f"[!] 找不到文件: {csv_path}")
        sys.exit(1)

    # 1. 加载食谱
    recipes = load_recipes(csv_path)

    # 2. 批量分类
    results = classify_all(recipes)

    # 3. 将 meal_type 字段拼接回原CSV
    save_classified_csv(recipes, results, csv_path)

    print(f"\n{'=' * 60}")
    print("[✓] 全部完成! meal_type 已写入原CSV文件")


if __name__ == "__main__":
    main()
