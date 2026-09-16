# 部署指南 · 永久链接 + AI 对话

## 目标

| 部分 | 托管位置 | 提供的能力 |
|---|---|---|
| **前端** | GitHub Pages（`index.html`） | 知识库检索、涉外国家判定、相关知识点——**开箱即用，无需后端** |
| **后端** | 免费云平台（Render 等） | AI 模型分析、联网核实、图片识别 |

前端已支持通过 URL 参数指向后端：任意静态页都能连上云后端。

---

## 一、部署后端

### 方案 A：Hugging Face Spaces（推荐 —— 免信用卡，永久 URL）

Render 免费层对新账号要求验证信用卡；HF Spaces **全程不需要任何支付凭证**。

1. 注册/登录 <https://huggingface.co>（邮箱即可，无需信用卡）
2. 右上角头像 → **New Space**：
   - Space name：`zhengxiaoan`
   - SDK 选 **Docker** → Blank 模板
   - Visibility 选 **Public**（前端跨域调用必需）
3. Space 建好后，进入 **Files** 标签 → 上传 `hf-space.zip` 里的全部文件
   （`Dockerfile`、`README.md`、`server.py`、`kb_data.py`、`kb_official.py`、
   `hague_data.py`、`index.html`、`weixin.html`、`full.html`）
4. **Settings → Variables and secrets** → 新建 Secret：
   - Name：`GLM_API_KEY`
   - Value：你的智谱 Key（Secret 不公开，比写进代码安全）
5. 回到 **App** 标签等 2-3 分钟自动构建
6. 永久地址：`https://<你的用户名>-zhengxiaoan.hf.space`

> Dockerfile 已内置 `PORT=7860` 与 `DEFAULT_MODEL=glm-4-flash`。
> 免费层闲置约 48 小时后休眠，访问即自动唤醒（几十秒）。

### 方案 B：Render（免信用卡 ❌ 需验证卡）

新账号部署免费 Web Service 会被要求绑定信用卡（防滥用验证）。如果愿意绑卡：
Start Command 填 `python3 server.py`，环境变量 `GLM_API_KEY`，
构建 `pip install -r requirements.txt`。地址形如 `https://xxx.onrender.com`。

### 验证后端

```bash
curl https://你的地址/api/models
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
