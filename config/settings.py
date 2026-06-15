"""
应用配置管理 - 双Agent架构
Agent A (规则检索Agent) + Agent B (饮食助手Agent) + A2A通信协议
"""
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class Settings:
    """应用配置类 - 双Agent + A2A 架构"""
    
    # ==================== LLM 配置 ====================
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    QWEN_MODEL: str = os.getenv("QWEN_MODEL", "qwen-plus")
    
    # ==================== MySQL 数据库配置 (食谱营养数据) ====================
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "health_diet_db")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
    # ==================== Milvus 向量数据库配置 ====================
    MILVUS_URI: str = os.getenv("MILVUS_URI", "http://localhost:19530")
    MILVUS_DATABASE: str = os.getenv("MILVUS_DATABASE", "health")
    MILVUS_COLLECTION: str = os.getenv("MILVUS_COLLECTION", "health_rag")

    # ==================== 本地模型路径 ====================
    _PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    BGE_M3_PATH: str = os.getenv(
        "BGE_M3_PATH",
        os.path.join(_PROJECT_ROOT, "models", "bge-m3")
    )
    BGE_RERANKER_PATH: str = os.getenv(
        "BGE_RERANKER_PATH",
        os.path.join(_PROJECT_ROOT, "models", "bge-reranker-large")
    )
    
    # ==================== A2A 协议配置 (双Agent通信) ====================
    A2A_AGENT_A_ID: str = "agent_rule_search"
    A2A_AGENT_B_ID: str = "agent_diet_assistant"
    A2A_AGENT_B_URL: str = os.getenv("A2A_AGENT_B_URL", "http://127.0.0.1:8001/a2a/receive")
    A2A_VERSION: str = "1.0"
    # A2A模式：True=分布式部署（通过HTTP通信），False=同进程直连（默认）
    A2A_MODE_ENABLED: bool = os.getenv("A2A_MODE_ENABLED", "false").lower() == "true"
    
    # ==================== MCP Server ====================
    MCP_SERVER_HOST: str = os.getenv("MCP_SERVER_HOST", "127.0.0.1")
    MCP_SERVER_PORT: int = int(os.getenv("MCP_SERVER_PORT", "8000"))
    # MCP 独立部署时的 Streamable HTTP 连接地址（留空则使用 stdio 子进程模式）
    MCP_SERVER_URL: str = os.getenv("MCP_SERVER_URL", "")
    
    # ==================== 食谱数据CSV路径 (本地数据源/MySQL fallback) ====================
    RECIPE_CSV_PATH: str = os.getenv("RECIPE_CSV_PATH",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "Tools", "data", "recipes_nutrition(样本).csv"))
    
    # ==================== 应用配置 ====================
    APP_ENV: str = os.getenv("APP_ENV", "development")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


# 全局配置实例
settings = Settings()
