# 健康饮食助手 Agent 项目文档

**项目定位：** 基于大语言模型（通义千问）+ 向量数据库（Milvus）+ MCP 工具生态的个性化健康饮食推荐系统

**核心流程：** 用户输入 → 意图识别 → 健康规则检索（Milvus）→ 食谱筛选（MCP）→ 个性化配餐（LLM+反思机制）→ 结构化解读输出

***

## 一、整体架构总览

### 1.1 角色定义

| Agent / 模块                 | 角色定位          | 核心能力                                                | 依赖组件                                           |
| -------------------------- | ------------- | --------------------------------------------------- | ---------------------------------------------- |
| **规则检索 Agent（Agent A）**    | 上游规则解析端       | 健康标签检测 → Milvus混合检索+重排序 → 生成个性化饮食约束/注意事项            | Milvus向量数据库、BGE-M3嵌入模型、BGE-Reranker-Large重排序模型 |
| **健康饮食助手 Agent（Agent B）**  | 下游执行端         | 调用MCP食谱工具 → 营养需求计算 → LLM三餐智能选择 → 营养合规性分析 → LLM结构化解读 | MCP食谱工具集、MySQL食谱数据库、通义千问 LLM                   |
| **智能配餐引擎（MealPlanner）**    | Agent B 核心算法层 | 每日营养需求计算、三餐目标分配、LLM两阶段食谱选择（初选择+反思校验）                | Agent B内联组件                                    |
| **用户档案管理（ProfileManager）** | 用户画像层         | 身高/体重/年龄/性别/活动量解析、BMI计算、BMR计算、每日热量估算                | LLMProfileParser（LLM解析自然语言）                    |
| **API Server（FastAPI）**    | 对外服务层         | 意图分类、会话管理、请求路由、A2A协议转发                              | FastAPI、Agent A、Agent B                        |

### 1.2 整体数据流

```
用户输入（自然语言，如"我有高血压，帮我推荐一日三餐"）
    │
    ▼
【API Server】api_server.py
  1. 意图分类（LLM调用：meal_plan vs recipe_query）
  2. Profile解析：LLMProfileParser从文本提取身高/体重/年龄/性别/健康标签
  3. Profile完整性检查 → 如缺失，返回引导提问
    │
    ▼
【Agent A: 规则检索】agent/rule_search_agent.py
  1. 健康标签识别（关键词匹配：高血压/糖尿病/肥胖...）
  2. Milvus 混合检索：
     ├─ BGE-M3生成稠密+稀疏向量
     ├─ WeightedRanker(0.7, 1.0)融合
     └─ BGE-Reranker-Large 精排 → 取Top-1
  3. 输出：diet_notes（饮食注意事项）
    │
    ▼
【Agent B: 饮食助手】agent/diet_assistant_agent.py
  1. MealPlanner计算每日营养需求（基于用户Profile）
     ├─ BMI = 体重 / 身高²
     ├─ BMR（基础代谢率，Mifflin-St Jeor公式）
     └─ 每日热量 = BMR × 活动量系数
  2. 三餐目标分配（早30%、午40%、晚30%）
  3. MCP工具调用：
     ├─ filter_recipes：按约束+餐次筛选候选食谱（每餐~50个）
     └─ LLM两阶段智能选择：
        ├─ 第一轮：LLM从候选池选择食谱组合，使总热量接近目标
        └─ 第二轮（反思）：检查总热量是否在范围内，不合格则重新选择
  4. 营养合规性分析：analyze_recipe_nutrition 工具检查钠/脂肪等是否超限
  5. LLM结构化解读：
     ├─ 整体评价（优缺点）
     ├─ 专业食用建议（烹饪方式、进食时间等，含科学依据）
     └─ 营养不达标项及补充建议
    │
    ▼
【API Server】格式化响应
  1. 组装三餐食谱及核心营养数据
  2. 添加用户个人指标（BMI/每日建议热量）
  3. 返回 JSON / 自然语言响应
    │
    ▼
用户获取：个性化一日三餐配餐方案 + 营养分析 + 专业解读
```

### 1.3 协议依赖说明

| 协议                              | 用途                                         | 所在模块                              |
| ------------------------------- | ------------------------------------------ | --------------------------------- |
| **A2A（Agent-to-Agent）**         | Agent A ↔ Agent B 之间的标准消息传递，用于分布式部署时的跨进程通信 | `agent/a2a_protocol.py`           |
| **MCP（Model Context Protocol）** | Agent B ↔ 食谱数据库工具的函数调用                     | `mcp_servers/recipe_db_server.py` |
| **Milvus 混合检索**                 | Agent A ↔ 向量知识库的健康饮食规则检索                   | `core/vector_store.py`            |
| **FastAPI HTTP API**            | 外部系统 ↔ API Server 的 RESTful 接口             | `api_server.py`                   |

***

## 二、项目文件结构

```
health_diet_agent/
├── api_server.py                    # ★ FastAPI主服务：意图分类 + Profile管理 + 路由编排
├── agent_b_server.py                # ★ Agent B独立服务（分布式A2A模式时使用，端口8001）
├── config/
│   └── settings.py                  # 全局配置（LLM、MySQL、Milvus、A2A、MCP等）
├── agent/
│   ├── __init__.py
│   ├── a2a_protocol.py              # ★ A2A标准消息协议（消息构建/校验/解析）
│   ├── rule_search_agent.py         # ★ Agent A: Milvus规则检索 + A2A请求发送
│   ├── diet_assistant_agent.py      # ★ Agent B: 配餐编排 + 食谱查询 + LLM解读
│   ├── meal_planner.py              # ★ 智能配餐引擎（营养计算+LLM两阶段选择）
│   ├── profile_manager.py           # ★ 用户档案管理器（BMI/BMR/热量计算）
│   └── llm_profile_parser.py        # ★ LLM用户信息解析器（自然语言→结构化指标）
├── core/
│   └── vector_store.py              # ★ 向量检索模块（BGE-M3混合检索 + BGE-Reranker重排序）
├── mcp_servers/
│   └── recipe_db_server.py          # ★ 食谱营养数据库MCP Server（5个工具，MySQL数据源）
├── models/                          # 本地模型存放目录
│   ├── bge-m3/                      # BGE-M3嵌入模型（稠密+稀疏）
│   └── bge-reranker-large/          # BGE-Reranker-Large重排序模型
├── Tools/
│   └── data/recipes_nutrition.csv   # 原始食谱营养数据（可选，MySQL为主要数据源）
├── requirements.txt                 # Python依赖清单
└── Agent项目文档.md                 # 本文档
```

***

## 三、A2A 通信协议层规范

> 实现文件：[`agent/a2a_protocol.py`](file:///d:/PythonProject/health_diet_agent/agent/a2a_protocol.py)

### 3.1 协议概述

A2A（Agent-to-Agent）协议定义了 Agent A 与 Agent B 之间的标准消息格式，支持两种部署模式：

- **同进程直连模式（默认）**：Agent A 和 Agent B 在同一 `api_server.py` 进程内初始化，直接调用 Python 对象方法
- **分布式A2A模式**：Agent A 运行在 `api_server.py`（端口8000），Agent B 运行在 `agent_b_server.py`（端口8001），通过 HTTP 通信

### 3.2 消息类型

| 消息类型     | 构造方法                          | 字段说明                                                                                 |
| -------- | ----------------------------- | ------------------------------------------------------------------------------------ |
| **请求消息** | `A2AMessage.build_request()`  | `a2a_version` + `msg_id` + `sender` + `receiver` + `session_id` + `task` + `payload` |
| **响应消息** | `A2AMessage.build_response()` | 同上 + `ref_msg_id`（引用请求ID） + `status` + `payload`                                     |
| **异常消息** | `A2AMessage.build_error()`    | 同上 + `error_code` + `error_msg`                                                      |

### 3.3 请求消息（Agent A → Agent B）

```json
{
    "a2a_version": "1.0",
    "msg_id": "a2a_req_0001",
    "timestamp": "2024-01-15T10:30:00+08:00",
    "sender": "agent_rule_search",
    "receiver": "agent_diet_assistant",
    "msg_type": "request",
    "session_id": "sess_20240115_001",
    "task": "diet_recommend",
    "payload": {
        "user_query": "我有高血压，帮我推荐一日三餐",
        "health_label": "高血压",
        "diet_notes": [
            "严格控钠，每日钠摄入不超过2000mg",
            "增加富含钾的食物，促进钠的排出",
            "减少腌制食品、加工肉类摄入"
        ],
        "hard_constraints": {
            "max_sodium": 500,
            "max_fat": 15
        },
        "user_profile": {
            "height": 175,
            "weight": 75,
            "age": 40,
            "gender": "男",
            "activity_level": "中度活动",
            "bmi": 24.5,
            "bmr": 1680,
            "daily_calories": 2604
        }
    }
}
```

**Task 字段说明：**

- `diet_recommend`：配餐请求（默认）→ 调用 Agent B 的 `handle_meal_plan()`
- `recipe_query`：食谱查询请求 → 调用 Agent B 的 `handle_recipe_query()`

### 3.4 响应消息（Agent B → Agent A）

```json
{
    "a2a_version": "1.0",
    "msg_id": "a2a_resp_0001",
    "timestamp": "2024-01-15T10:30:05+08:00",
    "sender": "agent_diet_assistant",
    "receiver": "agent_rule_search",
    "msg_type": "response",
    "session_id": "sess_20240115_001",
    "ref_msg_id": "a2a_req_0001",
    "status": "success",
    "payload": {
        "summary": "已为您生成高血压适用的一日三餐配餐方案",
        "meal_plan": {
            "breakfast": {"recipes": [...], "target": {"calorie": 781}},
            "lunch": {"recipes": [...], "target": {"calorie": 1042}},
            "dinner": {"recipes": [...], "target": {"calorie": 781}},
            "daily_total": {"calorie": 2604, "protein": 130, "fat": 70, "carbohydrate": 390}
        },
        "nutrition_analysis": {
            "total": 12,
            "compliant_count": 10,
            "non_compliant_count": 2,
            "analysis": [...]
        },
        "llm_analysis": {
            "evaluation": "本方案钠含量控制良好...",
            "cooking_advice": [...],
            "nutrition_gaps": [...]
        },
        "milvus_used": true,
        "diet_notes": [...]
    }
}
```

### 3.5 异常消息

```json
{
    "a2a_version": "1.0",
    "msg_id": "a2a_err_0001",
    "timestamp": "...",
    "sender": "agent_diet_assistant",
    "receiver": "agent_rule_search",
    "msg_type": "error",
    "session_id": "...",
    "ref_msg_id": "a2a_req_0001",
    "error_code": "NO_RECIPE",
    "error_msg": "根据当前饮食约束，未匹配到足够的候选食谱"
}
```

**预定义错误码：** `INVALID_MSG`（消息格式非法）、`WRONG_RECEIVER`（接收方错误）、`NO_RESULT`（未找到结果）、`TOOL_ERROR`（工具调用失败）

### 3.6 消息解析方法

| 方法                                  | 用途                         |
| ----------------------------------- | -------------------------- |
| `A2AMessage.validate(msg)`          | 校验消息合法性（检查必填字段）            |
| `A2AMessage.parse_constraints(msg)` | 提取 `hard_constraints` 约束规则 |
| `A2AMessage.parse_diet_notes(msg)`  | 提取 `diet_notes` 饮食注意事项     |
| `A2AMessage.parse_user_query(msg)`  | 提取用户原始问题                   |

***

## 四、核心模块详细说明

### 4.1 用户档案管理

> 实现文件：[`agent/profile_manager.py`](file:///d:/PythonProject/health_diet_agent/agent/profile_manager.py) + [`agent/llm_profile_parser.py`](file:///d:/PythonProject/health_diet_agent/agent/llm_profile_parser.py)

#### UserProfile 数据模型

| 字段                   | 类型        | 必填 | 说明                                |
| -------------------- | --------- | -- | --------------------------------- |
| `height`             | float（cm） | ✅  | 身高                                |
| `weight`             | float（kg） | ✅  | 体重                                |
| `age`                | int       | ✅  | 年龄                                |
| `gender`             | str（男/女）  | ✅  | 性别                                |
| `activity_level`     | str       | ❌  | 活动量（久坐不动/轻度活动/中度活动/重度活动），默认"中度活动" |
| `health_condition`   | str       | ❌  | 健康状况（如"高血压"、"糖尿病"）                |
| `dietary_preference` | str       | ❌  | 饮食偏好                              |
| `allergies`          | str       | ❌  | 过敏食物                              |

#### 计算方法

| 方法                           | 公式                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------ |
| `calculate_bmi()`            | `weight / (height/100)²`                                                             |
| `calculate_bmr()`            | 男性: `10×weight + 6.25×height - 5×age + 5`女性: `10×weight + 6.25×height - 5×age - 161` |
| `calculate_daily_calories()` | `BMR × 活动量系数`（久坐1.2 / 轻度1.375 / 中度1.55 / 重度1.725）                                    |

#### LLM Profile Parser

从自然语言输入（如"我身高175cm体重75kg今年35岁男性"）中提取结构化指标：

1. **优先方案**：调用通义千问 LLM，通过专门的提示词提取身高/体重/年龄/性别/活动量/健康状况，输出 JSON
2. **回退方案**：使用正则表达式匹配 `身高XXcm`、`体重XXkg`、`XX岁`、`男/女` 等关键词

### 4.2 规则检索 Agent（Agent A）

> 实现文件：[`agent/rule_search_agent.py`](file:///d:/PythonProject/health_diet_agent/agent/rule_search_agent.py) + [`core/vector_store.py`](file:///d:/PythonProject/health_diet_agent/core/vector_store.py)

#### 健康关键词映射

| 健康标签      | 识别关键词                   |
| --------- | ----------------------- |
| 高血压       | 高血压、血压高、降压、血压           |
| 高脂血症      | 高血脂、血脂高、血脂、降脂           |
| 高尿酸血症\_痛风 | 痛风、尿酸、尿酸高、高尿酸           |
| 糖尿病       | 糖尿病、血糖、血糖高、降糖           |
| 肥胖        | 肥胖、超重、很胖、减肥、减重、瘦身、偏胖、微胖 |
| 慢性肾脏病     | 肾病、肾脏、肾功能               |
| 感冒        | 感冒、感冒发烧、着凉              |
| 营养指南      | 营养均衡、膳食指南、营养搭配          |

#### Milvus 混合检索流程

```
用户输入文本
    │
    ▼
BGEM3EmbeddingFunction 生成
    ├─ 稠密向量（dense）
    └─ 稀疏向量（sparse，bag-of-words）
    │
    ▼
Milvus hybrid_search:
    ├─ AnnSearchRequest → dense_vector（IP度量，nprobe=10）
    ├─ AnnSearchRequest → sparse_vector（IP度量）
    └─ WeightedRanker(0.7, 1.0) 融合加权（稀疏权重更高）
    │
    ▼
BGE-Reranker-Large 交叉编码器精排
    └─ 输出Top-1最相关文档 → 提取 diet_notes
```

**向量集合配置：**

- 集合名：`health_rag`（可通过 settings.MILVUS\_COLLECTION 配置）
- 数据库：`health`（可通过 settings.MILVUS\_DATABASE 配置）
- 输出字段：`text`、`parent_id`、`parent_content`、`source`、`timestamp`
- 子块按 `parent_content` 去重，避免重复规则

#### A2A 请求发送（分布式模式）

当 `settings.A2A_MODE_ENABLED = true` 时，Agent A 通过 HTTP 向 Agent B 发送请求：

- **目标地址**：`settings.A2A_AGENT_B_URL`（默认 `http://127.0.0.1:8001/a2a/receive`）
- **超时**：120 秒
- **Agent B 服务文件**：`agent_b_server.py`

***

### 4.3 饮食助手 Agent（Agent B）

> 实现文件：[`agent/diet_assistant_agent.py`](file:///d:/PythonProject/health_diet_agent/agent/diet_assistant_agent.py)

#### 核心能力

| 能力          | 实现路径                                                                            |
| ----------- | ------------------------------------------------------------------------------- |
| **意图分类**    | LLM判断用户意图（meal\_plan/recipe\_query），支持关键词回退                                     |
| **食谱查询**    | LLM提取关键词 → `search_recipe_by_name` 搜索 → `get_recipe_nutrition` 获取详情 → LLM自然语言回答 |
| **个性化配餐**   | MealPlanner计算营养目标 → 筛选候选食谱 → LLM两阶段选择 → 营养合规性分析 → LLM结构化解读                      |
| **MCP工具调用** | 支持 stdio子进程模式 或 Streamable HTTP模式（由 `settings.MCP_SERVER_URL` 控制）               |

#### MCP 工具加载流程

```
Agent B 初始化
    │
    ▼
检查 settings.MCP_SERVER_URL
    ├─ 非空 → Streamable HTTP 模式：连接远程 MCP Server
    └─ 为空 → stdio 子进程模式：以 Python 子进程启动 recipe_db_server.py
    │
    ▼
通过 MultiServerMCPClient 获取工具列表
    └─ 5 个工具：filter_recipes、search_recipe_by_name、
                  get_recipe_nutrition、analyze_recipe_nutrition、
                  recommend_healthy_recipes
```

#### 配餐请求处理流程

```
输入：user_query, user_profile, health_label, diet_notes, constraints
    │
    ▼
1. MealPlanner.calculate_daily_nutrition(profile, health_label)
   ├─ 基础热量 = daily_calories
   ├─ 宏量营养素比例：蛋白质15%、脂肪25%、碳水60%
   └─ 健康状况调整：
      ├─ 高血压/高脂：max_sodium=2000mg，脂肪减少10%
      ├─ 糖尿病：碳水减少15%，max_sugar=50g
      └─ 肥胖：总热量减少20%
    │
    ▼
2. MealPlanner.allocate_meal_targets(daily_nutrition)
   ├─ 早餐：30%
   ├─ 午餐：40%
   └─ 晚餐：30%
    │
    ▼
3. 每餐候选食谱筛选（并行处理三餐）
   ├─ 每顿调用 MCP filter_recipes：
   │   ├─ meal_type=早餐/午餐/晚餐
   │   ├─ max_calorie=单餐目标/食谱数 ×1.5
   │   ├─ max_fat、max_sodium、max_carbohydrate 等健康约束
   │   └─ limit=50
   └─ MCP 返回结构化候选食谱列表（含热量/蛋白质/脂肪/碳水/钠等营养数据）
    │
    ▼
4. LLM两阶段智能选择（每餐独立执行）
   ├─ 第一轮（初始选择）：
   │   ├─ LLM 浏览候选池热量分布（最低/最高/平均）
   │   ├─ 计算单食谱平均热量目标 = 餐目标 / 食谱数
   │   └─ LLM 输出食谱 index 数组（JSON格式）
   └─ 第二轮（反思检查）：
      ├─ 计算选中食谱的实际总热量
      ├─ 判断是否在目标±15%范围内
      ├─ 不合格：提示LLM重新选择（明确指出热量偏差）
      └─ 合格：确定最终选择
    │
    ▼
5. 营养合规性分析
   └─ 调用 MCP analyze_recipe_nutrition：
      ├─ 根据健康标签检查钠/脂肪/热量等是否超限
      └─ 输出合规/不合规食谱清单及原因
    │
    ▼
6. LLM 结构化解读
   └─ 基于完整配餐方案，LLM 生成：
      ├─ evaluation：整体评价（优缺点）
      ├─ cooking_advice：3-5条专业食用建议（含烹饪方式、食材处理、科学依据）
      └─ nutrition_gaps：营养不达标项及补充建议（如钾摄入不足→推荐香蕉/菠菜）
    │
    ▼
输出：结构化配餐方案（JSON）
```

***

### 4.4 MCP 食谱数据库 Server

> 实现文件：[`mcp_servers/recipe_db_server.py`](file:///d:/PythonProject/health_diet_agent/mcp_servers/recipe_db_server.py)

#### 数据源

- **主数据源**：MySQL 数据库（表：`recipes_nutrition`）
- **连接配置**：`settings.MYSQL_HOST/PORT/USER/PASSWORD/DATABASE`
- **数据字段**：recipe\_id, recipe\_name, ingredients, meal\_type, + 30项营养素（能量、蛋白质、脂肪、碳水、维生素A/B/C/D/E/K、烟酸、叶酸、胆碱、钠、钾、镁、铁、锌、钙、磷、硒、碘、铜、锰等）

#### MCP 工具列表

| 工具名                             | 用途                    | 输入参数                                                                                                                                       |
| ------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| **filter\_recipes**             | 按营养约束条件和餐次筛选食谱        | `meal_type`、`max_calorie`、`max_fat`、`max_sodium`、`max_carbohydrate`、`max_protein`、`max_potassium`、`min_iron`、`exclude_ingredients`、`limit` |
| **search\_recipe\_by\_name**    | 按食谱名称关键词搜索            | `keyword`、`limit`                                                                                                                          |
| **get\_recipe\_nutrition**      | 获取指定食谱ID的完整30项营养素详情   | `recipe_id`                                                                                                                                |
| **analyze\_recipe\_nutrition**  | 分析一组食谱的营养合规性，输出合规检查结果 | `recipe_ids`、`constraints`（可选）                                                                                                             |
| **recommend\_healthy\_recipes** | 根据健康标签推荐适配食谱          | `health_label`、`meal_type`（可选）、`limit`                                                                                                     |

#### 健康标签 → 筛选策略映射

| 健康标签      | 筛选策略                                                          |
| --------- | ------------------------------------------------------------- |
| 高血压       | `max_sodium: 500mg`，按钠升序排列                                    |
| 高脂血症      | `max_fat: 8g`，`max_calorie: 150kcal`，按脂肪升序                    |
| 高尿酸血症\_痛风 | `max_calorie: 200kcal`，按热量升序                                  |
| 糖尿病       | `max_carbohydrate: 15g`，`max_calorie: 200kcal`，按碳水升序          |
| 肥胖        | `max_calorie: 120kcal`，`max_fat: 8g`，按热量升序                    |
| 慢性肾脏病     | `max_protein: 10g`，`max_sodium: 400mg`，`max_potassium: 300mg` |
| 感冒/营养指南   | `max_calorie: 200-300kcal`，按热量升序                              |

#### 食谱排除规则（自动过滤）

在筛选和推荐时自动排除以下类别的食谱：

- 婴儿食品/配方奶粉/婴幼儿辅食
- 高钠高脂加工食品（方便面、油炸食品、饼干、肉酱等）
- 零热量饮品（茶水、纯净水、矿泉水）
- 酒精饮品（白酒、啤酒、葡萄酒等）

#### 运行模式

| 模式                      | 启动命令                                            | 说明                                                                      |
| ----------------------- | ----------------------------------------------- | ----------------------------------------------------------------------- |
| **stdio 子进程**（默认）       | `python recipe_db_server.py`                    | 作为 Agent B 的子进程，通过标准输入输出通信                                              |
| **Streamable HTTP**（独立） | `python recipe_db_server.py --http --port 8002` | 作为独立HTTP服务，Agent B 通过 `settings.MCP_SERVER_URL=http://host:8002/mcp` 连接 |

***

### 4.5 智能配餐引擎（MealPlanner）

> 实现文件：[`agent/meal_planner.py`](file:///d:/PythonProject/health_diet_agent/agent/meal_planner.py)

这是整个系统的**核心算法模块**，负责将用户的营养目标转化为实际的三餐食谱组合。

#### 每日营养需求计算

```
输入：profile（身高/体重/年龄/性别/活动量/BMI/BMR/daily_calories）+ health_label
    │
    ▼
1. 宏量营养素（基于每日热量）
   ├─ 蛋白质：daily_calories × 15% ÷ 4 = X g
   ├─ 脂肪：    daily_calories × 25% ÷ 9 = Y g
   └─ 碳水：    daily_calories × 60% ÷ 4 = Z g
    │
    ▼
2. 健康状况微调
   ├─ 高血压/高脂：max_sodium=2000mg/天，脂肪目标减少10%
   ├─ 糖尿病：    碳水目标减少15%，max_sugar=50g/天
   └─ 肥胖：      总热量目标减少20%
```

#### LLM 两阶段食谱选择机制

**第一轮（初始选择）：**

- 向 LLM 提供：候选食谱池完整列表（名称+热量+蛋白质+脂肪+碳水+钠+meal\_type）、单餐目标热量、允许范围（±15%）、健康状况
- LLM 分析候选池热量分布，计算每个食谱平均应贡献的热量
- LLM 输出食谱 index 数组（JSON格式，如 `[3, 15, 27]`）
- 系统验证 JSON 格式并提取食谱

**第二轮（反思检查）：**

- 计算第一轮选中食谱的**实际总热量**
- 判断是否在目标范围（target × 0.85 ≤ 实际 ≤ target × 1.15）
- 合格：保留选择
- 不合格：向 LLM 明确指出热量偏差（如"当前总热量1200kcal，目标800±120kcal，严重超标"），要求重新选择
- LLM 重新输出 index 数组

#### LLM 结构化解读提示词模板

```
你是一位专业营养师，请根据以下信息生成JSON格式的专业解读：

【用户信息】身高、体重、年龄、性别、BMI、健康状况、每日建议热量
【饮食注意事项】diet_notes
【营养目标 vs 实际达成】各营养素目标值 vs 实际值对比
【推荐食谱】三餐食谱列表（名称+热量+蛋白质+脂肪）

请严格以JSON格式输出：
{
    "evaluation": "整体评价（200字以内）",
    "cooking_advice": [
        {"category": "烹饪方式", "suggestions": ["建议1", "建议2"], "scientific_basis": "科学依据"},
        {"category": "进食时间", "suggestions": ["..."], "scientific_basis": "..."},
        {"category": "食材处理", "suggestions": ["..."], "scientific_basis": "..."}
    ],
    "nutrition_gaps": [
        {"nutrient": "钠超标", "gap_description": "超6905.6mg", "supplement": "推荐补充...", "expected_effect": "..."},
        ...
    ]
}
```

***

### 4.6 LLM Profile Parser

> 实现文件：[`agent/llm_profile_parser.py`](file:///d:/PythonProject/health_diet_agent/agent/llm_profile_parser.py)

#### 工作流程

```
用户自然语言输入（如"我是25岁女性，身高165cm，体重55kg，平时锻炼不多"）
    │
    ▼
1. 优先方案：调用通义千问 LLM
   ├─ 系统提示：要求从文本中提取8个字段（height/weight/age/gender/
   │          activity_level/health_condition/dietary_preference/allergies）
   ├─ 格式要求：严格JSON输出，数值字段只填数字，不确定填null
   └─ 示例：给出2个正确示例帮助 LLM 理解
    │
    ▼
2. JSON解析与数据校验
   ├─ 身高：30-250cm范围
   ├─ 体重：20-300kg范围
   ├─ 年龄：1-150岁范围
   └─ 性别：必须是"男"或"女"
    │
    ▼
输出：结构化字典 {height, weight, age, gender, activity_level, health_condition, ...}
```

#### 回退机制（LLM 不可用时）

- 使用正则表达式匹配常见表达格式：`身高XXcm`、`体重XXkg`、`XX岁`、`男/女`
- 回退方案准确性较低，仅作为应急方案

***

## 五、API Server 详解

> 实现文件：[`api_server.py`](file:///d:/PythonProject/health_diet_agent/api_server.py)

### 5.1 启动流程

```
FastAPI 应用启动
    │
    ▼
lifespan 生命周期管理
    ├─ 初始化 Agent A（VectorStore + Milvus连接）
    ├─ 初始化 Agent B（LLM + MCP工具加载）
    │   └─ MCP模式选择：stdio子进程 或 Streamable HTTP
    └─ 日志输出：双Agent架构就绪信息
    │
    ▼
监听端口 8000，等待请求
```

### 5.2 核心 API 端点

| 端点                           | 方法   | 用途                                           |
| ---------------------------- | ---- | -------------------------------------------- |
| `/`                          | GET  | 返回 Web 前端页面（若存在）                             |
| `/api/chat`                  | POST | **智能对话主入口**（意图分类→配餐/查询→返回结果）                 |
| `/api/recipe/filter`         | POST | 按约束条件直接筛选食谱（绕过Agent A，直连MCP）                 |
| `/api/recipe/search`         | GET  | 按关键词搜索食谱                                     |
| `/api/recipe/{id}/nutrition` | GET  | 获取单个食谱完整营养详情                                 |
| `/api/tools`                 | GET  | 获取可用 MCP 工具列表                                |
| `/api/agents/status`         | GET  | 查看 Agent A/B 状态（Milvus/LLM/MCP就绪情况）          |
| `/health`                    | GET  | 健康检查                                         |
| `/a2a/receive`               | POST | Agent B 独立服务接收 A2A 请求（仅 agent\_b\_server.py） |

### 5.3 `/api/chat` 完整处理流程

```
用户请求（message, session_id 可选, intent 可选）
    │
    ▼
1. 意图识别
   ├─ 显式指定 intent：直接使用（meal_plan / recipe_query）
   └─ 未指定：调用 Agent B.classify_intent() → LLM判断用户意图
    │
    ▼
2. 根据意图路由
    │
    ├─ [recipe_query] → 食谱查询路径
    │   ├─ 同进程模式：Agent B.handle_recipe_query()
    │   └─ A2A模式：Agent A.send_recipe_query() → HTTP转发
    │
    └─ [meal_plan] → 配餐请求路径
        │
        ├─ 2a. Profile解析与管理
        │   ├─ LLMProfileParser.parse(message) → 提取结构化指标
        │   ├─ ProfileParser.update_profile(profile, extracted) → 合并已有Profile
        │   └─ profile.is_complete() 检查：
        │       ├─ 不完整 → 返回引导提问（要求用户补充缺失信息）
        │       └─ 完整 → 继续
        │
        ├─ 2b. 健康标签检测
        │   ├─ 检查 message 中的关键词 → 识别 health_label
        │   ├─ 检查 profile.health_condition → 补充识别
        │   └─ 无标签 → 使用"通用"饮食建议
        │
        ├─ 2c. Milvus 规则检索（Agent A）
        │   ├─ 有健康标签 → hybrid_search_with_rerank() → 获取 diet_notes
        │   └─ 无健康标签/Milvus未命中 → 使用默认通用建议
        │
        ├─ 2d. 调用 Agent B 生成配餐
        │   ├─ 同进程模式：Agent B.handle_meal_plan(profile, health_label, diet_notes)
        │   └─ A2A模式：Agent A.send_diet_request() → 构造A2A消息 → HTTP POST到Agent B
        │
        └─ 2e. 格式化响应
            ├─ 组装三餐食谱（名称+热量+蛋白质+脂肪+碳水+钠）
            ├─ 添加营养合规性分析结果
            ├─ 添加LLM结构化解读（评价+建议+缺口）
            └─ 添加用户个人指标（BMI+每日建议热量）
    │
    ▼
返回 ChatResponse JSON（response文本 + session_id + a2a_trace追踪信息）
```

### 5.4 ChatRequest 数据模型

```python
{
    "message": "用户自然语言输入",            # 必填
    "session_id": "sess_xxx",                 # 可选，用于多轮对话关联Profile
    "intent": "meal_plan" | "recipe_query"   # 可选，显式指定意图，跳过LLM意图分类
}
```

### 5.5 ChatResponse 数据模型

```python
{
    "response": "格式化后的自然语言响应文本",
    "session_id": "sess_xxx",
    "a2a_trace": {
        "intent": "meal_plan",
        "health_label": "高血压",
        "milvus_used": true,
        "meal_plan": {...},          # 结构化配餐数据
        "nutrition_analysis": {...}, # 营养合规性分析
        "llm_analysis": {...},       # LLM专业解读
        "profile": {...}             # 用户个人指标
    }
}
```

***

## 六、部署与运行

### 6.1 环境要求

| 组件     | 要求                                                 |
| ------ | -------------------------------------------------- |
| Python | ≥ 3.10                                             |
| 向量数据库  | Milvus 2.3+（需预先导入健康饮食规则数据）                         |
| 关系数据库  | MySQL 8.0+（食谱营养数据表：`recipes_nutrition`）            |
| LLM服务  | 阿里云 DashScope API（通义千问）                            |
| 本地模型   | BGE-M3（嵌入）、BGE-Reranker-Large（重排序），放在 `models/` 目录 |

### 6.2 配置说明（settings.py）

| 配置项            | 变量                                                 | 说明                                                              |
| -------------- | -------------------------------------------------- | --------------------------------------------------------------- |
| LLM模型          | `QWEN_MODEL`                                       | 默认 `qwen-plus`                                                  |
| API Key        | `DASHSCOPE_API_KEY`                                | 需从环境变量或 `.env` 文件配置                                             |
| MySQL连接        | `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE`           | 食谱数据库连接                                                         |
| Milvus连接       | `MILVUS_URI`、`MILVUS_DATABASE`、`MILVUS_COLLECTION` | 向量数据库配置                                                         |
| 本地模型路径         | `BGE_M3_PATH`、`BGE_RERANKER_PATH`                  | 默认 `models/bge-m3`、`models/bge-reranker-large`                  |
| A2A模式开关        | `A2A_MODE_ENABLED`                                 | `true`=分布式HTTP，`false`=同进程直连（默认）                                |
| A2A Agent B地址  | `A2A_AGENT_B_URL`                                  | 分布式模式下 Agent B 的 HTTP 地址，默认 `http://127.0.0.1:8001/a2a/receive` |
| Agent ID       | `A2A_AGENT_A_ID`、`A2A_AGENT_B_ID`                  | Agent身份标识，用于A2A消息校验                                             |
| MCP Server URL | `MCP_SERVER_URL`                                   | 空=stdio子进程模式，非空=Streamable HTTP远程模式                             |

### 6.3 部署模式

#### 模式一：同进程直连（推荐，最简部署）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动主服务（单进程包含 Agent A + Agent B + MCP 子进程）
python api_server.py

# 3. 访问服务
#   API文档：  http://localhost:8000/docs
#   健康检查： http://localhost:8000/health
#   Agent状态：http://localhost:8000/api/agents/status
```

**特点**：单进程部署，无网络通信开销，Agent A/B 直接对象调用；MCP工具以子进程方式运行

**进程树**：

```
api_server.py (主进程，FastAPI)
├─ Agent A（Python对象，Milvus连接）
└─ Agent B（Python对象，LLM + MCP客户端）
    └─ recipe_db_server.py（子进程，stdio通信）
```

#### 模式二：分布式 A2A 部署（横向扩展用）

```bash
# 1. 启动 Agent B 独立服务（端口 8001）
python agent_b_server.py
#    健康检查：http://localhost:8001/health
#    A2A入口：  http://localhost:8001/a2a/receive

# 2. 在 api_server.py 所在目录的 .env 文件中配置
#    A2A_MODE_ENABLED=true
#    A2A_AGENT_B_URL=http://127.0.0.1:8001/a2a/receive

# 3. 启动主服务（包含 Agent A，Agent B 通过 HTTP 远程调用）
python api_server.py

# 4. 访问主服务（同模式一）
#    API文档：http://localhost:8000/docs
```

**特点**：Agent A 与 Agent B 解耦部署，可独立扩展；Agent B 可部署在GPU机器，Agent A 部署在普通机器

**进程树**：

```
机器A：api_server.py（主进程）
└─ Agent A（本地对象，Milvus连接，负责规则检索+A2A消息封装）

机器B：agent_b_server.py（独立FastAPI进程，端口8001）
└─ Agent B（本地对象，LLM + MCP客户端）
    └─ recipe_db_server.py（子进程或远程HTTP，MCP工具）

通信链路：Agent A → HTTP POST(8001/a2a/receive) → Agent B
```

#### 模式三：MCP 工具远程部署（极致解耦）

```bash
# 1. 启动 MCP Server（独立HTTP服务，端口8002）
python mcp_servers/recipe_db_server.py --http --port 8002
#    健康检查： http://localhost:8002/health
#    MCP端点：   http://localhost:8002/mcp

# 2. 配置 .env
#    MCP_SERVER_URL=http://127.0.0.1:8002/mcp

# 3. 启动主服务（模式一或二均可）
python api_server.py
```

**特点**：MCP工具可部署在数据库所在机器，Agent B 远程调用工具，减少数据库连接开销

***

## 七、关键设计亮点

### 7.1 Agent职责清晰分离

- **Agent A** 专注于**规则层**：语义理解 → 向量检索 → 饮食约束生成
- **Agent B** 专注于**执行层**：数据筛选 → 智能组合 → 合规分析 → 专业解读
- 两层Agent之间通过A2A标准协议通信，便于独立迭代和扩展

### 7.2 LLM反思机制（Self-Reflection）

配餐选择采用两阶段LLM调用：

1. 第一轮：LLM从候选池"盲目"选择食谱组合
2. 第二轮：LLM检查自己的选择是否满足热量目标，不合格则重新选择

- **设计价值**：LLM对数值计算不擅长，但对结构化比较和调整能力强；两阶段设计将"计算"交给系统，"选择"交给LLM，扬长避短

### 7.3 Milvus混合检索 + 重排序

- **混合检索**：稠密向量（语义相似度）+ 稀疏向量（关键词匹配）加权融合，比纯稠密向量检索更精准
- **重排序**：用更强的 CrossEncoder 模型对初召回结果做精排，显著提升Top-1命中率
- **按source过滤**：支持按健康标签（高血压/糖尿病等）限定检索范围，避免跨标签干扰

### 7.4 Profile驱动的个性化推荐

- 系统不会立即对"帮我配餐"这样的模糊请求生成方案，而是先引导用户补充个人信息（身高/体重/年龄/性别）
- 用户信息通过LLM自然语言解析，无需强制用户填写表单
- 多轮会话中Profile持续完善，同一 session\_id 的请求自动复用已有Profile

### 7.5 多通信模式支持

- MCP工具支持 **stdio子进程** 和 **Streamable HTTP** 两种模式，配置一行切换
- Agent间支持 **同进程直连** 和 **A2A HTTP** 两种模式，支持从单体到分布式的平滑过渡
- 所有通信层切换不影响业务逻辑，代码改动极小

### 7.6 结构化输出与自然语言结合

- Agent B 内部完全使用JSON结构化数据（便于程序处理和存储）
- API Server 最终转换为自然语言响应（便于用户理解）
- 同时保留结构化数据在 `a2a_trace` 字段中，便于前端渲染和后续分析

***

## 八、扩展方向与后续规划

| 方向             | 说明                                   |
| -------------- | ------------------------------------ |
| **膳食周期规划**     | 支持生成一周/一月配餐方案，考虑食材重复、营养均衡的时间维度       |
| **用户画像持久化**    | 将 Profile 存入数据库，支持用户注册登录、历史饮食记录      |
| **更多健康标签**     | 扩展Milvus规则库，覆盖孕期、儿童、老年、素食等更多人群       |
| **食谱知识库扩充**    | 增加食谱数据库规模，提供更丰富的候选池                  |
| **营养摄入量记录**    | 用户可记录实际进食，系统计算营养摄入，与目标对比给出反馈         |
| **多Agent协作增强** | 引入第三个Agent（如"运动助手Agent"），提供饮食+运动综合建议 |
| **Agent对话记忆**  | 支持多轮对话上下文，Agent可引用之前的对话内容进行个性化调整     |

***

## 九、代码参考索引

| 模块             | 文件路径                                                                                                            |
| -------------- | --------------------------------------------------------------------------------------------------------------- |
| API主服务         | [`api_server.py`](file:///d:/PythonProject/health_diet_agent/api_server.py)                                     |
| Agent B独立服务    | [`agent_b_server.py`](file:///d:/PythonProject/health_diet_agent/agent_b_server.py)                             |
| 全局配置           | [`config/settings.py`](file:///d:/PythonProject/health_diet_agent/config/settings.py)                           |
| A2A消息协议        | [`agent/a2a_protocol.py`](file:///d:/PythonProject/health_diet_agent/agent/a2a_protocol.py)                     |
| Agent A规则检索    | [`agent/rule_search_agent.py`](file:///d:/PythonProject/health_diet_agent/agent/rule_search_agent.py)           |
| Agent B饮食助手    | [`agent/diet_assistant_agent.py`](file:///d:/PythonProject/health_diet_agent/agent/diet_assistant_agent.py)     |
| 智能配餐引擎         | [`agent/meal_planner.py`](file:///d:/PythonProject/health_diet_agent/agent/meal_planner.py)                     |
| 用户档案管理         | [`agent/profile_manager.py`](file:///d:/PythonProject/health_diet_agent/agent/profile_manager.py)               |
| LLM Profile解析  | [`agent/llm_profile_parser.py`](file:///d:/PythonProject/health_diet_agent/agent/llm_profile_parser.py)         |
| 向量检索模块         | [`core/vector_store.py`](file:///d:/PythonProject/health_diet_agent/core/vector_store.py)                       |
| MCP食谱数据库Server | [`mcp_servers/recipe_db_server.py`](file:///d:/PythonProject/health_diet_agent/mcp_servers/recipe_db_server.py) |
| 依赖清单           | [`requirements.txt`](file:///d:/PythonProject/health_diet_agent/requirements.txt)                               |

***

*本文档最后更新：基于当前代码库实现*
