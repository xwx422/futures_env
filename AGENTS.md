# futures_env
> 自动生成于 2026-05-10 22:38

## 技术栈
- Python
- Flask
- Celery
- SQLAlchemy
- Pandas
- NumPy

## 目录结构
```├── analysis_layer/```
```│   ├── adaptive_params.py```
```│   ├── batch_deepseek_agent.py```
```│   ├── deepseek_agent.py```
```│   ├── divergence_monitor.py```
```│   ├── pre_trend_engine.py```
```│   ├── support_resistance.py```
```│   ├── trend_filter.py```
```│   ├── trend_marker.py```
```│   ├── trend_phase.py```
```│   ├── turtle_strategy.py```
```├── config/```
```│   ├── cache_config.py```
```│   ├── gunicorn.conf.py```
```├── data_layer/```
```│   ├── fetch_market.py```
```│   ├── fund_flow.py```
```│   ├── quick_price_fetcher.py```
```│   ├── spot_fetcher.py```
```│   ├── spread_analyzer.py```
```│   ├── technical_indicators.py```
```├── doc/```
```│   ├── README.md```
```├── execution_layer/```
```│   ├── generate_card.py```
```│   ├── risk_manager.py```
```├── instance/```
```├── logs/```
```├── routes/```
```│   ├── adaptive_params_routes.py```
```...```

## Git 信息
- 分支: main
- 最近提交: feat: 初始化开源版本，排除核心分析模块

## 最近变更
- [2026-05-10] 创建 active_divergences 表，支持背离信号持久化
- [2026-05-10] 放宽 AI Prompt ADX 阈值：ADX<15 观望，15-20 需确认
- [2026-05-10] 优化 AI Prompt：震荡行情必须给出方向策略，不能简单观望
- [2026-05-10] 修复 Dashboard 显示：方向显示"⏸ 观望"而非"—"，趋势阶段始终显示
- [2026-05-10] 配置全局 AGENTS.md 规则 + 项目级自动更新机制

> 最后更新: 2026-05-10