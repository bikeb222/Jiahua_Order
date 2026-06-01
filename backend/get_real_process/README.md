# Real OMS Snapshot Tool

This folder contains read-only tools for capturing the current state of the real OMS SQL Server database before and after an OMS order-entry test.

The default connection is:

```text
DSN=test;DATABASE=omsdata;ApplicationIntent=ReadOnly;
```

Run from this folder:

```powershell
cd C:\Users\info\OneDrive\Desktop\code\order\backend\get_real_process
& "C:\Users\info\OneDrive\Desktop\code\order\backend\.venv\Scripts\python.exe" `
  ".\capture_snapshot.py" `
  --label before `
  --database omsdata `
  --confirm-production-read
```

If PowerShell treats the path oddly, use:

```powershell
& "C:\Users\info\OneDrive\Desktop\code\order\backend\.venv\Scripts\python.exe" `
  "C:\Users\info\OneDrive\Desktop\code\order\backend\get_real_process\capture_snapshot.py" `
  --label before `
  --database omsdata `
  --confirm-production-read
```

Outputs are written to:

```text
backend\get_real_process\snapshots\YYYYMMDD_HHMMSS_before
```

The snapshot exports:

- SQL Server/database identity and capture time
- row counts for order/inventory/payment candidate tables, from SQL Server metadata
- light metrics such as current max `ORD_NUM`, max `INVS_NUM`, and inventory row counts
- latest `orders` rows and related `ord_log`, `so_divs`, `order2e`, etc.
- latest `invoice` rows
- full `inv_data` and `bin_file` inventory snapshots, unless `--skip-full-inventory` is used

Safety notes:

- The script runs fixed `SELECT` statements only.
- It uses `READ UNCOMMITTED` to avoid blocking production work.
- It connects with `ApplicationIntent=ReadOnly`.
- It stops if the connected database is not the requested database or if `dbo.orders` is missing.
- It does not accept arbitrary SQL.
- It requires `--confirm-production-read` so production access is explicit.
- It does not query heavier order-related tables such as `invt_log`, `bin_ord`, `pay_log`, or `pay_auth` unless `--include-heavy-related` is explicitly passed.
