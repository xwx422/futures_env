#!/bin/bash
# AI期货分析平台 - 设置定时任务脚本
# 设置 cron 定时任务，在指定时间自动运行数据更新

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER_SCRIPT="$SCRIPT_DIR/schedule_runner.sh"

# 检查 runner 脚本是否存在
if [ ! -f "$RUNNER_SCRIPT" ]; then
    echo "错误: 未找到 $RUNNER_SCRIPT"
    exit 1
fi

# 确保 runner 脚本可执行
chmod +x "$RUNNER_SCRIPT"

# 定时任务配置
# 运行时间：每天 8:30, 10:20, 13:00, 14:00, 20:30, 22:00
CRON_JOBS="
# AI期货分析平台 - 自动数据更新任务
30 8 * * * $RUNNER_SCRIPT
20 10 * * * $RUNNER_SCRIPT
0 13 * * * $RUNNER_SCRIPT
0 14 * * * $RUNNER_SCRIPT
30 20 * * * $RUNNER_SCRIPT
0 22 * * * $RUNNER_SCRIPT
"

echo "============================================"
echo "AI期货分析平台 - 定时任务设置"
echo "============================================"
echo ""
echo "将在以下时间自动运行数据更新:"
echo "  - 上午 8:30"
echo "  - 上午 10:20"
echo "  - 下午 13:00"
echo "  - 下午 14:00"
echo "  - 晚上 20:30"
echo "  - 晚上 22:00"
echo ""
echo "执行脚本: $RUNNER_SCRIPT"
echo ""

# 检查是否已存在相同的定时任务
if crontab -l 2>/dev/null | grep -q "$RUNNER_SCRIPT"; then
    echo "提示: 已存在相同的定时任务"
    echo "选项:"
    echo "  1. 更新定时任务 (删除旧的并添加新的)"
    echo "  2. 删除现有定时任务"
    echo "  3. 取消"
    echo ""
    read -p "请选择 [1/2/3]: " choice
    
    case $choice in
        1)
            # 删除旧的任务
            crontab -l 2>/dev/null | grep -v "$RUNNER_SCRIPT" | crontab -
            echo "已删除旧的定时任务"
            ;;
        2)
            crontab -l 2>/dev/null | grep -v "$RUNNER_SCRIPT" | crontab -
            echo "已删除定时任务"
            exit 0
            ;;
        *)
            echo "已取消"
            exit 0
            ;;
    esac
fi

# 添加新的定时任务
(crontab -l 2>/dev/null; echo "$CRON_JOBS") | crontab -

echo ""
echo "✓ 定时任务设置成功！"
echo ""
echo "当前 cron 任务列表:"
crontab -l | grep -A 10 "AI期货分析平台"
echo ""
echo "提示:"
echo "  - 日志文件: $SCRIPT_DIR/logs/schedule_runner.log"
echo "  - 查看所有 cron 任务: crontab -l"
echo "  - 删除所有任务: crontab -r"
echo "  - 手动运行测试: $RUNNER_SCRIPT"
