# AI 期货分析助手

### 具备趋势预判能力的期货决策系统

> 消耗超 10 亿 Token 算力，融合 DeepSeek、千问等主流大模型深度打造。集趋势预判引擎、智能否决机制、四维评分、趋势空间评估于一体，覆盖 14 个活跃期货品种。

---

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=flat&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.0+-000000?style=flat&logo=flask&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5.0+-37814A?style=flat&logo=celery&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-6.0+-DC382D?style=flat&logo=redis&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3.0+-003B57?style=flat&logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Online](https://img.shields.io/badge/🟢-在线体验-brightgreen)

**[在线体验](https://qh.ossou.cn) · [功能特点](#核心能力) · [系统架构](#三层分析链路) · [快速开始](#快速开始)**

</div>

---

## 关于本仓库

> **本仓库为开源版本，包含项目架构、前端模板、部署脚本等基础设施代码。**
>
> **核心分析引擎（趋势预判、四维评分、否决机制等算法）为闭源商业模块，未包含在本仓库中。**
>
> | 版本 | 内容 | 获取方式 |
> |:---:|:---|:---|
> | **开源版** | 项目架构、前端页面、部署脚本、配置示例 | 本仓库 |
> | **完整版** | 包含全部核心算法的线上服务 | [在线体验](https://qh.ossou.cn) |
>
> 这是业界标准的 **Open Core（开放核心）** 模式，类似 GitLab CE/EE、Redis、MySQL 等知名项目。
>
> 开源的目的是展示技术架构、吸引社区关注、方便合作伙伴评估。如需完整功能，请使用线上服务。

---

## 产品定位

**这不是一个简单的指标看板，而是一个具备"趋势预判"能力的智能决策系统。**

传统分析工具只告诉你"现在是什么样"，而 AI 期货分析助手要回答交易员最核心的三个问题：

| 问题 | 系统能力 |
|:---:|:---:|
| **现在能不能做？** | 趋势预判评分 + 智能否决机制 |
| **空间还有多大？** | 趋势空间评估（ATR 消耗度） |
| **风险在哪里？** | 动态风控体系 + 盈亏比约束 |

系统将"看方向、定仓位、控风险"串成统一闭环，帮助交易员从主观拍脑袋，升级为有证据的实战决策。

---

## 核心能力

### 一、趋势预判引擎 ⭐ 核心创新

**从"现状描述"升级到"趋势预判"**

不是所有指标看多就喊买，而是在多数指标刚转多、价格还没大涨时发现机会。系统对每个品种输出 **0-100 的预判评分**，基于四大维度加权计算：

| 维度 | 权重 | 说明 |
|:---:|:---:|:---|
| **📈 趋势早期度** | 30% | 趋势刚启动（初期/成长）还是已走完（成熟/衰竭）？越早期分越高 |
| **💰 资金确认度** | 25% | 持仓量增减 + 主力资金流向是否配合趋势方向？ |
| **📍 位置安全度** | 25% | RSI 在安全区域（40-60）还是极端区？追高风险有多大？ |
| **⚖️ 盈亏比系数** | 20% | 当前入场价到止损/止盈的距离比是否划算？ |

### 二、智能否决机制 🚫 宁可错过，不做错

当技术指标给出"做多"建议时，系统会先执行三道硬性否决检查，任一触发即禁止入场：

| 否决规则 | 触发条件 | 保护目标 |
|:---:|:---:|:---:|
| **RSI 超买否决** | RSI ≥ 75 禁止追多，RSI ≤ 25 禁止追空 | 避免高位接盘、低位割肉 |
| **深贴水否决** | 年化展期收益率 < -10% 禁止做多 | 期限结构严重利空时强制观望 |
| **趋势衰竭否决** | ADX > 50 且 RSI 极端 | 大概率见顶/见底，强制离场 |

### 三、趋势空间评估 📏 还能追吗？

计算当前趋势已消耗 ATR 倍数与剩余空间，告诉你：

- **已走 0.5 ATR** → 趋势刚启动，空间充足，可以布局
- **已走 1.5 ATR** → 趋势中期，关注回调机会
- **已走 2.5 ATR（84% 消耗）** → 趋势末期，不建议再追

### 四、三层分析链路 🔄

系统不是看完所有指标说"涨"或"跌"，而是按 **现状 → 趋势 → 预判** 逐层过滤，确保每一条结论都有据可查：

```
┌─────────────────────────────────────────────────────────────┐
│  第一层 · 现状分析                                            │
│  客观描述已经发生的事：价格、涨跌、技术指标、基差结构、           │
│  期限价差、资金流向、持仓量变化、多周期K线                       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  第二层 · 趋势分析                                            │
│  判断方向与阶段：ADX趋势强度、DI差值、趋势生命周期              │
│  输出信号评级：布局 / 关注 / 等待                              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  第三层 · 趋势预判引擎 ⭐                                      │
│  四维评分 → 0-100 预判评分                                    │
│  否决机制 → 硬性禁止入场条件                                   │
│  空间评估 → ATR消耗度 → 建议入场区                             │
└─────────────────────────────────────────────────────────────┘
```

### 五、信号三档评级 📋

| 评级 | 含义 | 预判评分 | 操作建议 |
|:---:|:---:|:---:|:---|
| **🟢 布局** | 趋势早期 + 资金确认 + 位置安全 | ≥ 70 分 | 可以考虑入场 |
| **🟡 关注** | 部分条件满足，等待确认 | 50-69 分 | 持续跟踪，等待信号 |
| **⚪ 等待** | 否决触发或条件不足 | < 50 分 | 强制观望，不做操作 |

---

## 技术指标体系

系统集成了完整的多维度技术分析框架：

### 趋势类指标
| 指标 | 用途 | 参数 |
|:---:|:---:|:---:|
| **ADX** | 趋势强度判断 | 14周期 |
| **DI+/DI-** | 多空力量对比 | 14周期 |
| **MACD** | 趋势方向与动量 | 12/26/9 |
| **MA** | 均线系统 | MA5/MA20 |

### 震荡类指标
| 指标 | 用途 | 参数 |
|:---:|:---:|:---:|
| **RSI** | 超买超卖判断 | 14周期 |
| **KDJ** | 短期超买超卖 | 9/3/3 |
| **布林带** | 价格波动区间 | 20周期/2倍标准差 |

### 波动类指标
| 指标 | 用途 | 参数 |
|:---:|:---:|:---:|
| **ATR** | 波动率度量 | 14周期 |
| **布林带宽度** | 波动率变化 | - |

### 资金类指标
| 指标 | 用途 |
|:---:|:---:|
| **持仓量变化** | 多空资金博弈 |
| **主力资金流向** | 大资金动向 |
| **基差/期限结构** | 现货与期货价差 |
| **跨期价差** | 近远月合约价差 |

---

## 覆盖品种

系统覆盖 **14 个活跃期货品种**，保证金 ≤ 1 万，适合新手验证系统（1手起步）：

### 黑色建材板块
| 品种 | 代码 | 交易所 | 合约乘数 | 保证金率 |
|:---:|:---:|:---:|:---:|:---:|
| 螺纹钢 | RB | SHFE | 10吨/手 | 10% |
| 热轧卷板 | HC | SHFE | 10吨/手 | 10% |
| 铁矿石 | I | DCE | 100吨/手 | 12% |

### 能源化工板块
| 品种 | 代码 | 交易所 | 合约乘数 | 保证金率 |
|:---:|:---:|:---:|:---:|:---:|
| 甲醇 | MA | CZCE | 10吨/手 | 8% |
| PTA | TA | CZCE | 5吨/手 | 8% |
| 塑料 | L | DCE | 5吨/手 | 9% |
| PVC | V | DCE | 5吨/手 | 7% |
| 纯碱 | SA | CZCE | 20吨/手 | 12% |
| 玻璃 | FG | CZCE | 20吨/手 | 12% |

### 农产品板块
| 品种 | 代码 | 交易所 | 合约乘数 | 保证金率 |
|:---:|:---:|:---:|:---:|:---:|
| 豆粕 | M | DCE | 10吨/手 | 8% |
| 豆油 | Y | DCE | 10吨/手 | 9% |
| 玉米 | C | DCE | 10吨/手 | 7% |
| 棉花 | CF | CZCE | 5吨/手 | 10% |
| 白糖 | SR | CZCE | 10吨/手 | 8% |

---

## 动态风控体系

### ATR 动态止损止盈

基于 ATR（平均真实波幅）的动态风控，自动适应市场波动：

```
止损距离 = ATR × 止损倍数（默认 1.0）
止盈距离 = ATR × 止盈倍数（默认 2.0）
盈亏比   = 止盈距离 / 止损距离 ≥ 2:1
```

### 仓位约束

- **固定手数**：新手验证系统固定 1 手
- **单笔最大亏损**：每手最大亏损 ≤ 100 元
- **保证金计算**：自动计算开仓所需保证金

### 风控示例

以螺纹钢为例：
- 当前 ATR = 60 点
- 止损距离 = 60 × 1.0 = 60 点（600 元）
- 止盈距离 = 60 × 2.0 = 120 点（1200 元）
- 盈亏比 = 2:1
- 每手最大亏损 = 600 元 > 100 元限制 → 系统会自动调整手数

---

## 技术架构

### 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户层 (User Layer)                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Web 前端   │  │   移动端     │  │   API 接口   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      应用层 (Application Layer)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Flask      │  │   Celery     │  │   Redis      │          │
│  │   Web 服务   │  │   异步任务   │  │   缓存/队列  │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      分析层 (Analysis Layer)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ DeepSeek AI  │  │ 趋势预判引擎 │  │ 海龟策略     │          │
│  │ 方向分析     │  │ 四维评分     │  │ 趋势跟踪     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ 趋势阶段     │  │ 支撑阻力     │  │ 否决机制     │          │
│  │ 识别         │  │ 分析         │  │ 风控         │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      数据层 (Data Layer)                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ 天勤量化     │  │ 技术指标     │  │ 资金流向     │          │
│  │ TQSDK        │  │ 计算         │  │ 分析         │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      存储层 (Storage Layer)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   SQLite     │  │   PostgreSQL │  │   文件系统   │          │
│  │   分析结果   │  │   用户数据   │  │   日志/配置  │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

### 目录结构

```
futures_env/
├── analysis_layer/              # AI 分析模块（核心）
│   ├── deepseek_agent.py        #   DeepSeek AI 调用和交易方向分析
│   ├── batch_deepseek_agent.py  #   批量 AI 分析
│   ├── trend_filter.py          #   趋势过滤（ADX+双均线+多周期）
│   ├── trend_phase.py           #   趋势阶段分析（初期→成长→成熟→衰竭）
│   ├── pre_trend_engine.py      #   趋势预判引擎（四维评分）
│   ├── support_resistance.py    #   支撑阻力分析
│   └── turtle_strategy.py       #   海龟交易策略
│
├── data_layer/                  # 数据获取模块
│   ├── fetch_market.py          #   行情数据获取（天勤量化）
│   ├── fund_flow.py             #   资金流向分析
│   └── technical_indicators.py  #   技术指标计算（RSI/MACD/ATR等）
│
├── execution_layer/             # 执行层
│   ├── generate_card.py         #   分析卡片生成（整合所有分析）
│   └── risk_manager.py          #   风险管理（仓位/止损/止盈）
│
├── routes/                      # Flask 路由
│   ├── update_routes.py         #   更新相关接口
│   ├── task_routes.py           #   任务管理接口
│   ├── market_data_routes.py    #   行情数据接口
│   ├── monitor_routes.py        #   监控接口
│   ├── divergence_routes.py     #   背离信号接口
│   └── signal_routes.py         #   信号评级接口
│
├── tasks/                       # Celery 异步任务
│   └── analysis_tasks.py        #   定时分析任务
│
├── templates/                   # HTML 模板
│   ├── index.html               #   首页（产品介绍）
│   ├── dashboard.html           #   Dashboard（分析结果展示）
│   └── ...                      #   其他页面模板
│
├── static/                      # 静态资源
│   ├── css/                     #   样式文件
│   ├── js/                      #   JavaScript
│   ├── images/                  #   图片资源
│   └── mobile/                  #   移动端资源
│
├── config/                      # 配置模块
│   └── cache_config.py          #   缓存配置
│
├── utils/                       # 工具函数
│   └── device_detector.py       #   设备检测（PC/移动端）
│
├── services/                    # 业务服务
│
├── config.yaml                  # 品种配置文件
├── main.py                      # 主入口（分析流程、数据库操作）
├── app.py                       # Flask 应用（路由、Dashboard）
├── celery_app.py                # Celery 应用配置
├── init_db.py                   # 数据库初始化
├── logging_config.py            # 日志配置
├── requirements.txt             # Python 依赖
│
├── deploy.sh                    # 部署脚本
├── deploy-production.sh         # 生产环境部署
├── setup_systemd_services.sh    # systemd 服务配置
├── start-local.sh               # 本地启动脚本
├── start_celery.sh              # Celery 启动脚本
└── setup_cron.sh                # 定时任务配置
```

---

## 快速开始

### 环境要求

- **Python**: 3.8+
- **Redis**: 6.0+（用于 Celery 消息队列和缓存）
- **天勤量化账号**: 注册 [TQSDK](https://www.shinnytech.com/) 获取
- **DeepSeek API Key**: 注册 [DeepSeek](https://platform.deepseek.com/) 获取

### 安装步骤

#### 1. 克隆项目

```bash
git clone https://gitee.com/xwx422/futures_env.git
cd futures_env
```

#### 2. 创建虚拟环境

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

#### 3. 安装依赖

```bash
pip install -r requirements.txt
```

#### 4. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入以下配置：

```env
# 天勤量化账号
TQ_ACCOUNT=your_tq_account
TQ_PASSWORD=your_tq_password

# DeepSeek API
DEEPSEEK_API_KEY=your_deepseek_api_key

# Flask 配置
SECRET_KEY=your_random_secret_key

# 可选：数据库配置（默认使用 SQLite）
# DATABASE_URL=postgresql://user:pass@localhost/dbname

# 可选：Redis 配置（默认 localhost:6379）
# REDIS_URL=redis://localhost:6379/0
```

#### 5. 初始化数据库

```bash
python init_db.py
```

#### 6. 启动服务

**方式一：一键启动（推荐）**

```bash
./start-local.sh
```

**方式二：分别启动**

```bash
# 终端 1：启动 Flask 应用
python app.py

# 终端 2：启动 Celery Worker
celery -A celery_app worker --loglevel=info

# 终端 3：启动 Celery Beat（定时任务）
celery -A celery_app beat --loglevel=info
```

#### 7. 访问系统

打开浏览器访问：`http://localhost:5000`

---

## 部署指南

### 生产环境部署

#### 方式一：systemd 服务部署

```bash
# 配置 systemd 服务
./setup_systemd_services.sh

# 启动服务
sudo systemctl start futures-ai
sudo systemctl start futures-ai-celery
sudo systemctl start futures-ai-beat

# 设置开机自启
sudo systemctl enable futures-ai
sudo systemctl enable futures-ai-celery
sudo systemctl enable futures-ai-beat
```

#### 方式二：Gunicorn + Nginx

```bash
# 启动 Gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app

# Nginx 配置示例
# server {
#     listen 80;
#     server_name your-domain.com;
#
#     location / {
#         proxy_pass http://127.0.0.1:5000;
#         proxy_set_header Host $host;
#         proxy_set_header X-Real-IP $remote_addr;
#     }
# }
```

#### 方式三：Docker 部署

```dockerfile
# Dockerfile 示例
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 5000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

```bash
# 构建镜像
docker build -t futures-ai .

# 运行容器
docker run -d -p 5000:5000 --env-file .env futures-ai
```

---

## 配置说明

### 品种配置 (config.yaml)

```yaml
# 品种定义
varieties:
  螺纹钢:
    sector: 黑色建材
    code: RB
    keywords: ["螺纹钢", "建筑钢材", "房地产", "基建"]
    exchange: SHFE

# 品种规则
commodity_rules:
  RB:
    min_volatility: 0.015      # 最小波动率
    typical_atr: 60            # 典型 ATR 值
    position_multiplier: 10    # 合约乘数（每点价值）
    margin_rate: 0.10          # 保证金率

# 风险控制
risk_control:
  fixed_lots: 1                # 固定手数
  max_loss_per_lot: 100        # 每手最大可接受亏损（元）
  take_profit_atr_multiple: 2.0  # 止盈 ATR 倍数
  stop_loss_atr_multiple: 1.0    # 止损 ATR 倍数

# 趋势预判引擎配置
pre_trend_engine:
  veto_rules:
    rsi_overbought: 75         # RSI 高于此值禁止追多
    rsi_oversold: 25           # RSI 低于此值禁止追空
    deep_basis_threshold: -10  # 年化展期收益率低于此值(%)禁止做多
    trend_exhaustion_adx: 50   # ADX 高于此值+RSI极端=趋势衰竭

# 技术分析参数
technical_params:
  ma_short_period: 5           # 短期均线周期
  ma_long_period: 20           # 长期均线周期
  atr_period: 14               # ATR 周期
  rsi_period: 14               # RSI 周期
  bollinger_period: 20         # 布林带周期
  bollinger_std: 2             # 布林带标准差倍数
```

### 环境变量 (.env)

| 变量名 | 说明 | 必填 | 默认值 |
|:---:|:---:|:---:|:---:|
| `TQ_ACCOUNT` | 天勤量化账号 | ✅ | - |
| `TQ_PASSWORD` | 天勤量化密码 | ✅ | - |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | ✅ | - |
| `SECRET_KEY` | Flask 会话密钥 | ✅ | - |
| `REDIS_URL` | Redis 连接地址 | ❌ | `redis://localhost:6379/0` |
| `DATABASE_URL` | 数据库连接地址 | ❌ | `sqlite:///futures_analysis.db` |

---

## API 接口

系统提供 RESTful API 接口，支持二次开发：

| 接口 | 方法 | 说明 |
|:---:|:---:|:---|
| `GET /api/analysis/<variety>` | GET | 获取指定品种分析结果 |
| `GET /api/market-data` | GET | 获取实时行情数据 |
| `GET /api/analysis-history` | GET | 获取历史分析记录 |
| `GET /api/divergences` | GET | 获取背离信号 |
| `GET /api/signals` | GET | 获取信号评级列表 |
| `POST /api/trigger-analysis` | POST | 手动触发分析任务 |

---

## 技术栈

| 类别 | 技术 | 版本 | 用途 |
|:---:|:---:|:---:|:---|
| **后端框架** | Flask | 2.0+ | Web 应用框架 |
| **异步任务** | Celery | 5.0+ | 定时任务与异步处理 |
| **消息队列** | Redis | 6.0+ | Celery Broker + 缓存 |
| **数据库** | SQLite / PostgreSQL | - | 数据持久化 |
| **数据源** | 天勤量化 (TQSDK) | - | 期货行情数据 |
| **AI 模型** | DeepSeek API | - | 智能分析与研判 |
| **数据处理** | Pandas, NumPy | - | 数据清洗与计算 |
| **缓存** | Flask-Caching | - | 接口缓存加速 |

---

## 算力投入

**这不是一个简单的 API 调用封装。**

系统核心决策链经历了 DeepSeek、千问等多个主流 AI 大模型的反复对弈与校验——从行情数据解析、技术指标逻辑、趋势预判公式到否决规则阈值，每一步都经过海量对话测试与迭代优化。

```
累计消耗 Token 算力: 10 亿+
```

相当于 **10 年专业交易员** 的知识积累与决策经验，一次性注入系统。

---

## 产品优势

### 🚀 全自动定时运行

Celery 异步任务驱动，早盘前、午盘前、每 4 小时自动执行全品种分析。Redis 缓存 + 价格实时刷新，数据始终保持最新。

### 🧠 AI + 趋势双验证

AI 负责理解和归因，趋势分析负责验证方向。多重交叉确认，避免单一指标误导。

### 🔒 以风控为先

仓位、止损、止盈协同约束，优先控制回撤再追求收益，适配长期实盘生存逻辑。

### 📊 信号分级快速筛选

布局、关注、等待三档信号评级，让你快速锁定重点品种，不被信息淹没。

### 📱 多端适配

PC 端 + 移动端自适应布局，随时随地查看分析结果。

---

## 使用流程

```
① 注册登录 → ② 查看信号 → ③ 辅助决策
```

1. **注册登录**：免费注册账号，每天登录自动赠送 3 次分析额度
2. **查看信号**：进入 Dashboard 查看品种信号评级，快速锁定"布局"和"关注"档的重点品种
3. **辅助决策**：结合 AI 研判、趋势分析、盈亏比建议，做出更有依据的交易决策

---

## 开源协议

本项目采用 [Apache License 2.0](LICENSE) 开源协议。

---

## 免责声明

⚠️ **风险提示**：期货交易风险极高，可能损失全部本金。本系统仅提供辅助决策参考，不构成任何投资建议。投资者应谨慎决策，盈亏自负。

---

## 联系方式

- **项目地址**：https://gitee.com/xwx422/futures_env
- **问题反馈**：https://gitee.com/xwx422/futures_env/issues
- **在线体验**：https://qh.ossou.cn

---

## 更新日志

### v2.0.0 (2026-05-10)
- ✨ 新增趋势预判引擎（四维评分模型）
- ✨ 新增智能否决机制（RSI超买/深贴水/趋势衰竭）
- ✨ 新增趋势空间评估（ATR消耗度）
- ✨ 新增海龟交易策略模块
- ✨ 新增背离信号检测功能
- ✨ 新增信号三档评级（布局/关注/等待）
- ✨ 支持移动端自适应布局
- 🐛 优化 AI Prompt，改善分析质量
- 🐛 修复 Dashboard 显示问题

### v1.0.0 (2026-01-01)
- 🎉 初始版本发布
- ✨ 支持 14 个期货品种分析
- ✨ 实现基础技术指标计算
- ✨ 集成 DeepSeek AI 分析
- ✨ 实现分析卡片生成
- ✨ 支持定时任务调度

---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给一个 Star 支持一下！⭐**

</div>
