# Jia Hua OMS Web Order

Jia Hua OMS Web Order 是给局域网内部使用的销售下单网页系统。它连接现有 OMS SQL Server 数据库，通过网页完成客户查询、扫码加货、订单保存、订单修改、CSO 打印和 Picking List 打印。

当前部署方式是一台 Windows 电脑作为服务器，同一局域网内的电脑或 iPad 通过浏览器访问。

## 服务端口

| 服务 | 地址 | 用途 |
| --- | --- | --- |
| Backend API | `http://127.0.0.1:8008` | 数据库、订单保存、PDF、服务器端打印 |
| Desktop Web | `http://127.0.0.1:5173` | 桌面版下单页面 |
| iPad Web | `http://127.0.0.1:5174` | iPad / mobile 扫码页面 |

局域网客户端访问时，把 `127.0.0.1` 换成服务器电脑 IP，例如：

```text
http://192.168.1.168:5173/
http://192.168.1.168:5174/
```

## 目录结构

| 路径 | 说明 |
| --- | --- |
| `backend/` | FastAPI 后端，负责数据库读写、PDF 生成、服务器端打印 |
| `frontend/` | 5173 桌面版前端 |
| `frontend-mobile/` | 5174 iPad / mobile 前端 |
| `REF/` | 参考工具脚本 |
| `tools/` | 本地维护和对比工具 |
| `start_oms_services.ps1` | 启动三个服务的主脚本 |
| `Restart OMS Order Server.cmd` | 双击重启服务脚本 |

不随 Git 仓库上传的本机资源：

| 路径 | 原因 |
| --- | --- |
| `backend/.env` | 本机数据库连接和生产写入开关 |
| `backend/.venv/` | Python 虚拟环境 |
| `database/` | 本地数据库备份，体积大且包含生产数据 |
| `oms_gmw/` | 原 OMS 图片/资源目录，体积大 |
| `backend/get_real_process/order_context/` | 生产订单快照 |
| `backend/get_real_process/snapshots/` | 生产数据库快照 |
| `pdf/`, `pdf_compare/`, `backend/print_spool/` | 生成出来的测试 PDF 和打印留存 |

## 环境要求

- Windows
- Python 3.12+ 或 3.13
- SQL Server ODBC Driver
- 可访问 OMS SQL Server 的 DSN 或连接字符串
- 服务器电脑安装目标打印机驱动

后端依赖在 `backend/requirements.txt`。启动脚本会自动创建 `backend/.venv` 并安装依赖。

## 环境变量

生产和本机连接信息放在 `backend/.env`，这个文件不会提交到 Git。

示例：

```text
ORDER_READ_DB_CONNECTION=DSN=your_read_dsn;DATABASE=omsdata;ApplicationIntent=ReadOnly;
ORDER_WRITE_DB_CONNECTION=DSN=your_write_dsn;DATABASE=omsdata;

ORDER_ENABLE_APP_WRITE=true
ORDER_ALLOW_PRODUCTION_READ=true
ORDER_ENABLE_PRODUCTION_OMS_WRITE=true
ORDER_PRODUCTION_WRITE_ACK=I_UNDERSTAND_THIS_WRITES_TO_PRODUCTION_OMS

ORDER_SO_MIN_NUMBER=9438
ORDER_PRODUCT_IMAGE_DIR=Z:\oms_gmw\oms picture
```

生产写入有多层保护：

- `ORDER_ENABLE_APP_WRITE=true`
- `ORDER_ENABLE_PRODUCTION_OMS_WRITE=true`
- `ORDER_PRODUCTION_WRITE_ACK=I_UNDERSTAND_THIS_WRITES_TO_PRODUCTION_OMS`

三者不满足时，后端不会执行生产订单写入。

## 启动服务

在服务器电脑运行：

```powershell
cd C:\Users\info\OneDrive\Desktop\code\order
.\start_oms_services.ps1
```

也可以双击：

```text
Restart OMS Order Server.cmd
```

单独启动后端：

```powershell
cd C:\Users\info\OneDrive\Desktop\code\order\backend
.\run_backend.ps1
```

单独启动桌面版前端：

```powershell
cd C:\Users\info\OneDrive\Desktop\code\order\frontend
python .\dev_server.py
```

单独启动 iPad 版前端：

```powershell
cd C:\Users\info\OneDrive\Desktop\code\order\frontend-mobile
python .\dev_server.py
```

前端静态服务器会返回 no-cache header，避免局域网客户端拿到旧页面。

## 订单逻辑

- 新订单页面显示 `Draft`，保存时才分配真实 S/O 号码。
- 保存时从 `ORDER_SO_MIN_NUMBER` 开始寻找第一个可用 S/O 号码。
- 中间缺号可以使用，不强制从当前最大订单号继续。
- 新建订单和修改订单都在 SQL transaction 内完成。
- 写入失败时整单回滚，避免写入一半。
- 多客户端同时保存时使用 SQL Server application lock，避免 S/O 号码冲突。
- 修改订单会在 transaction 内重写对应订单行。

## 客户和商品逻辑

- 客户查询支持电话号码和客户号。
- 支持 billing-only、独立 shipping address、chain store ship-to 三种客户地址逻辑。
- Store 选择按钮显示为 `List`。
- Sales 下拉菜单写在前端代码中，当前包含：
  `TINA`, `JUDY`, `RAINNIE`, `VON`, `LINA`, `WEI`, `JASON`, `RAMON`, `JAY`, `ALEX`
- 商品查询支持 item number、barcode、UPC。
- 商品价格会根据客户 business type / level 自动选择。
- 点击 Item # 可以查看 Product Detail，包括图片、L1-L5 价格、库存和位置。
- W1 库存为负数时，订单行会用红色标记。

## 打印逻辑

打印由服务器电脑完成，不由客户端浏览器直接打印。

打印机优先级：

1. CSO / invoice 优先使用 `RICOH MP C3504ex PCL 6`
2. Picking List 优先使用 `Brother HL-L6310DW series`
3. 如果其中一台不可用，另一台会接管两种打印
4. 最后 fallback 到：
   - `Canon MF460 II Series UFR II`
   - `SHARP MX-B467F XL`
   - `Canon MF460 II Series UFR II(JASON)`

不会使用 PDF、OneNote、label、fax 等虚拟打印机。

当前 PDF 转打印图片的渲染分辨率：

```text
PDF_RENDER_DPI = 400
```

位置：`backend/app/server_print.py`

## 前端版本

### Desktop 5173

- 保留桌面 OMS 风格布局。
- 使用系统键盘和浏览器输入框。
- 支持客户详情、产品详情、正式打印、正式数据库订单保存。

### iPad / Mobile 5174

- 针对 iPad Chrome 竖屏使用。
- 有 Scan Mode。
- 使用自定义悬浮数字键盘和字母数字键盘。
- Scan 输入固定在顶部，总价和退出按钮固定在底部，商品列表中间滚动。

## 常用检查

检查后端是否监听：

```powershell
Get-NetTCPConnection -LocalPort 8008
```

检查桌面前端：

```powershell
Invoke-WebRequest http://127.0.0.1:5173/ -UseBasicParsing
```

检查 iPad 前端：

```powershell
Invoke-WebRequest http://127.0.0.1:5174/ -UseBasicParsing
```

检查打印接口：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8008/api/oms/orders/11022/print/picking-list
```
