#!/bin/bash
# AI期货分析平台 - 定时数据更新脚本（带交易日检查）
# 用于定时运行 main.py 获取更新数据
# 运行时间：每天 8:30, 10:20, 13:00, 14:00, 20:30, 22:00（仅交易日）

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 配置
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/schedule_runner.log"
MAIN_SCRIPT="$SCRIPT_DIR/main.py"
PYTHON_CMD="./venv/bin/python"

# 创建日志目录
mkdir -p "$LOG_DIR"

# 记录开始时间
START_TIME=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$START_TIME] =========================================" >> "$LOG_FILE"
echo "[$START_TIME] 开始执行定时数据更新任务" >> "$LOG_FILE"
echo "[$START_TIME] 工作目录: $SCRIPT_DIR" >> "$LOG_FILE"

# 检查 Python 环境（优先使用 venv）
if [ -x "$PYTHON_CMD" ]; then
    echo "[$START_TIME] 使用 Python: $PYTHON_CMD (venv)" >> "$LOG_FILE"
elif command -v "python3" &> /dev/null; then
    PYTHON_CMD="python3"
    echo "[$START_TIME] 警告: 未找到 venv，使用系统 Python: $(which python3)" >> "$LOG_FILE"
elif command -v "python" &> /dev/null; then
    PYTHON_CMD="python"
    echo "[$START_TIME] 警告: 未找到 venv，使用系统 Python: $(which python)" >> "$LOG_FILE"
else
    echo "[$START_TIME] 错误: 未找到 Python" >> "$LOG_FILE"
    exit 1
fi

# 检查今天是否是交易日
echo "[$START_TIME] 检查今天是否是交易日..." >> "$LOG_FILE"
IS_TRADING_DAY=$($PYTHON_CMD -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from utils.market_calendar import calendar
from datetime import datetime
result = calendar.is_trading_day(datetime.now())
print('1' if result else '0')
" 2>&1)

if [ "$IS_TRADING_DAY" = "0" ]; then
    TODAY=$(date '+%Y-%m-%d')
    echo "[$START_TIME] 今天 ($TODAY) 不是交易日，跳过更新" >> "$LOG_FILE"
    echo "[$START_TIME] 任务跳过（非交易日）" >> "$LOG_FILE"
    echo "" >> "$LOG_FILE"
    exit 0
else
    echo "[$START_TIME] 今天是交易日，继续执行更新" >> "$LOG_FILE"
fi

# 检查 main.py 是否存在
if [ ! -f "$MAIN_SCRIPT" ]; then
    echo "[$START_TIME] 错误: 未找到 $MAIN_SCRIPT" >> "$LOG_FILE"
    exit 1
fi

# 设置环境变量（如果有 .env 文件）
if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
    echo "[$START_TIME] 已加载环境变量" >> "$LOG_FILE"
fi

# 运行 main.py
echo "[$START_TIME] 执行: $PYTHON_CMD $MAIN_SCRIPT" >> "$LOG_FILE"

# 执行并记录输出
OUTPUT=$($PYTHON_CMD "$MAIN_SCRIPT" 2>&1)
EXIT_CODE=$?

# 记录结果
END_TIME=$(date '+%Y-%m-%d %H:%M:%S')
if [ $EXIT_CODE -eq 0 ]; then
    echo "[$END_TIME] ✓ 数据更新成功" >> "$LOG_FILE"
else
    echo "[$END_TIME] ✗ 数据更新失败 (退出码: $EXIT_CODE)" >> "$LOG_FILE"
fi

# 记录输出（限制行数以避免日志过大）
echo "[$END_TIME] 输出内容:" >> "$LOG_FILE"
echo "$OUTPUT" | tail -50 >> "$LOG_FILE"
echo "[$END_TIME] 任务执行完成" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

# 如果失败，可以发送通知（可选）
if [ $EXIT_CODE -ne 0 ]; then
    # 这里可以添加失败通知逻辑，如发送邮件或短信
    :
fi

exit $EXIT_CODE
