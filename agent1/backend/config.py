"""DeepSeek API 配置"""

import os

# DeepSeek API 密钥（从环境变量读取，不硬编码；未设置时为空）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# DeepSeek API 基础地址
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# 模型名称（固定为 deepseek-v4-flash）
MODEL_NAME = "deepseek-v4-flash"

# 生成参数
TEMPERATURE = 0.3
MAX_TOKENS = 4096
TOP_P = 0.95

# 超时设置（秒）
TIMEOUT = 120
