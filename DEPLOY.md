# 部署指南 · 永久链接 + AI 对话

## 目标

| 部分 | 托管位置 | 提供的能力 |
|---|---|---|
| **前端** | GitHub Pages（`index.html`） | 知识库检索、涉外国家判定、相关知识点——**开箱即用，无需后端** |
| **后端** | 免费云平台（Render 等） | AI 模型分析、联网核实、图片识别 |

前端已支持通过 URL 参数指向后端：任意静态页都能连上云后端。

---

## 一、部署后端（约 5 分钟）

本仓库已包含部署所需文件：`Procfile`、`requirements.txt`（纯标准库，无需依赖）。

### 推荐：Render（免费、免信用卡）

1. 打开 <https://render.com>，用 GitHub 账号注册登录
2. 点 **New → Web Service**，选择仓库 `4sirfour/zhengxiaoan`
3. 按下面填写：

   | 配置项 | 值 |
   |---|---|
   | Language / Runtime | `Python 3` |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `python3 server.py` |
   | Instance Type | `Free` |

4. 展开 **Environment Variables**，添加模型 Key（**只放服务端，前端拿不到**）：

   | Key | Value |
   |---|---|
   | `GLM_API_KEY` | 你的智谱 Key |
   | `DEEPSEEK_API_KEY` | （可选）DeepSeek Key |
   | `ARK_API_KEY` | （可选）豆包 Key |

5. 点 **Create Web Service**，等 2-3 分钟构建完成
6. 拿到形如 `https://zhengxiaoan.onrender.com` 的地址，**这就是永久后端地址**

> **免费层说明**：Render 免费实例闲置 15 分钟后会休眠，下次访问需等约 30 秒冷启动。
> 页面会正常等待，不会报错。如需常驻可升级付费层，或改用 Railway（有每月免费额度）。

### 验证后端

```bash
curl https://你的地址.onrender.com/api/models
# 应返回 JSON，其中 glm-4-flash 的 ready 为 true
```

---

## 二、前端连上后端

### 方式 A：URL 参数（最简单，无需改代码）

数据内嵌的静态页支持运行时指定后端：

```
https://4sirfour.github.io/zhengxiaoan/?api=https://zhengxiaoan.onrender.com
```

把这个带参数的链接发给用户即可，AI 对话、联网、图片识别全部可用。

### 方式 B：写进页面（链接更干净）

编辑 `full.html`，在 `<head>` 内加入一行：

```html
<script>window.API_BASE = "https://zhengxiaoan.onrender.com";</script>
```

保存后 `git push`，之后直接访问 `https://4sirfour.github.io/zhengxiaoan/full.html` 即可。

---

## 三、仓库文件说明

| 文件 | 用途 |
|---|---|
| `index.html` / `weixin.html` | **静态版**（Pages 入口）。数据内嵌，零外部请求，无需后端 |
| `full.html` | **完整版**前端。含模型选择器、图片识别，需连后端 |
| `server.py` | 后端服务（纯标准库）。`/` → 完整版，`/api/*` → 接口 |
| `build_weixin.py` | 由知识库数据重新生成 `weixin.html` |
| `hague_data.py` | 外交部《公约》缔约国名单（127 国） |
| `Procfile` / `requirements.txt` | 云平台部署配置 |
| `config.json` | 模型 Key（**已被 .gitignore 忽略，不会入库**） |

---

## 四、本地运行

```bash
PORT=3000 python3 server.py
```

打开 <http://localhost:3000> 即为完整版。
