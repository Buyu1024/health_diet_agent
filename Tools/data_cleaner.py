"""
食谱数据清洗工具
删除 ingredients, calorie, protein, fat, carbohydrate, sodium
为零或不存在（空值）的数据行。
处理结果保存至新文件，不修改源文件。
"""
import csv
import re
import os

INPUT_CSV = "data/recipes_nutrition(原文本).csv"
OUTPUT_CSV = "data/recipes_nutrition.csv"

# 必须存在且有非零值的字段
REQUIRED_FIELDS = ["ingredients", "calorie", "protein", "fat", "carbohydrate", "sodium"]


def parse_numeric(value_str: str) -> float | None:
    """从带单位的字符串中提取数值，如 '136 kcal' → 136.0, '0.00 g' → 0.0, '' → None"""
    if not value_str or not value_str.strip():
        return None
    match = re.match(r"([\d.]+)", value_str.strip())
    if match:
        return float(match.group(1))
    return None


def is_valid(row: dict) -> bool:
    """判断一行数据是否满足保留条件"""
    for field in REQUIRED_FIELDS:
        value = row.get(field, "")

        # ingredients 特殊处理：非空即有效
        if field == "ingredients":
            if not value or not value.strip():
                return False
            continue

        # 数值字段：必须存在且不为零
        num = parse_numeric(value)
        if num is None or num == 0:
            return False

    return True


def main():
    base_dir = os.path.dirname(__file__)
    input_path = os.path.join(base_dir, INPUT_CSV)
    output_path = os.path.join(base_dir, OUTPUT_CSV)

    if not os.path.exists(input_path):
        print(f"[!] 找不到文件: {input_path}")
        return

    # 读取原始数据
    with open(input_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        all_rows = list(reader)

    print(f"[+] 原始数据: {len(all_rows)} 条")

    # 逐行检查
    kept_rows = []
    removed_count = 0

    # 统计各字段的删除原因
    reason_counts = {f: 0 for f in REQUIRED_FIELDS}

    for row in all_rows:
        if is_valid(row):
            kept_rows.append(row)
        else:
            removed_count += 1
            # 记录是哪个字段导致删除
            for field in REQUIRED_FIELDS:
                value = row.get(field, "")
                if field == "ingredients":
                    if not value or not value.strip():
                        reason_counts[field] += 1
                        break
                else:
                    num = parse_numeric(value)
                    if num is None or num == 0:
                        reason_counts[field] += 1
                        break

    print(f"[+] 保留数据: {len(kept_rows)} 条")
    print(f"[+] 删除数据: {removed_count} 条")
    print(f"\n[删除原因统计]")
    for field, count in reason_counts.items():
        if count > 0:
            print(f"    {field} 无效: {count} 条")

    # 写入新文件
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept_rows)

    print(f"\n[✓] 清洗完成! 结果已保存至: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
