# OLAV Scripts

自动化脚本集合，用于 OLAV 日常运维和管理。

---

## 📁 脚本清单

### 1. daily_inspection.sh
**功能**: 每日网络健康检查自动化脚本

**特性**:
- ✅ 自动执行 `olav inspect daily-inspection` workflow
- ✅ 锁文件防止并发执行
- ✅ 超时控制（30 分钟）
- ✅ 详细日志记录
- ✅ Webhook 通知支持（Slack/Teams）
- ✅ 错误处理和重试

**使用**:
```bash
# 手动执行
./scripts/daily_inspection.sh

# 查看日志
tail -f .olav/logs/inspection_$(date +%Y%m%d).log

# 查看报告
cat exports/reports/snapshots/$(date +%Y%m%d).md
```

**配置**:
```bash
# 编辑脚本
nano scripts/daily_inspection.sh

# 启用通知
ENABLE_NOTIFICATION=true
WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# 调整超时（默认 30 分钟）
TIMEOUT=1800
```

---

### 2. install_cron.sh
**功能**: 一键安装 OLAV cron 任务

**特性**:
- ✅ 自动安装 3 个 cron 任务
- ✅ 智能合并现有 crontab
- ✅ 路径自动检测
- ✅ 任务管理（安装/列表/删除）

**使用**:
```bash
# 安装 cron 任务
./scripts/install_cron.sh

# 查看已安装任务
./scripts/install_cron.sh --list

# 删除 OLAV cron 任务
./scripts/install_cron.sh --remove

# 帮助
./scripts/install_cron.sh --help
```

**安装的任务**:
```cron
# 1. 每日检查（06:00）
0 6 * * * $OLAV_HOME/scripts/daily_inspection.sh

# 2. 每周备份（周日 02:00）
0 2 * * 0 cd $OLAV_HOME && uv run olav admin backup

# 3. 日志清理（01:00，保留 7 天）
0 1 * * * find $OLAV_HOME/.olav/logs -name "inspection_*.log" -mtime +7 -delete
```

---

### 3. merge_databases.py
**功能**: 合并 network.duckdb 到 main.duckdb

**特性**:
- ✅ 自动备份原数据库
- ✅ 表冲突检测
- ✅ 行数验证
- ✅ 完整的错误处理

**使用**:
```bash
# 执行合并
uv run python scripts/merge_databases.py

# 验证结果
uv run python -c "
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')
print(conn.execute('SHOW TABLES').fetchall())
"
```

**回滚**:
```bash
# 如果合并失败，从备份恢复
cp .olav/backups/main_backup_YYYYMMDD_HHMMSS.duckdb .olav/db/main.duckdb
```

---

## 🚀 快速开始

### Step 1: 测试手动执行

```bash
# 进入项目目录
cd /home/yhvh/Olav

# 赋予执行权限
chmod +x scripts/*.sh

# 测试 inspection 脚本
./scripts/daily_inspection.sh

# 检查输出
ls -l .olav/logs/inspection_*.log
ls -l exports/reports/snapshots/*.md
```

### Step 2: 安装 Cron 任务

```bash
# 安装
./scripts/install_cron.sh

# 验证
crontab -l | grep OLAV
```

### Step 3: 监控执行

```bash
# 实时监控 cron 日志
tail -f .olav/logs/cron.log

# 查看今天的 inspection 日志
tail -f .olav/logs/inspection_$(date +%Y%m%d).log

# 查看报告
cat exports/reports/snapshots/$(date +%Y%m%d).md
```

---

## 🔧 故障排查

### Cron 任务未执行

**检查 crontab**:
```bash
crontab -l | grep OLAV
```

**检查系统 cron 日志**:
```bash
# Ubuntu/Debian
sudo tail -f /var/log/syslog | grep CRON

# CentOS/RHEL
sudo tail -f /var/log/cron
```

**手动测试脚本**:
```bash
./scripts/daily_inspection.sh
```

### 权限问题

```bash
# 确保脚本可执行
chmod +x scripts/*.sh

# 确保路径正确
pwd  # 应该在 /home/yhvh/Olav
```

### 锁文件问题

```bash
# 如果脚本报错"已运行"
rm -f /tmp/olav_inspection.lock

# 再次执行
./scripts/daily_inspection.sh
```

### 日志查看

```bash
# Inspection 日志
cat .olav/logs/inspection_$(date +%Y%m%d).log

# Cron 执行日志
cat .olav/logs/cron.log

# 最近错误
grep -i error .olav/logs/*.log
```

---

## 📊 日志管理

### 日志文件位置

```
.olav/logs/
├── cron.log                      # Cron 任务输出
├── backup.log                    # 备份日志
├── inspection_YYYYMMDD.log       # 每日检查日志
└── cli_batch_YYYYMMDD_HHMMSS/   # CLI 批量执行
```

### 日志清理

```bash
# 手动清理 7 天前的日志
find .olav/logs -name "inspection_*.log" -mtime +7 -delete

# 查看日志大小
du -sh .olav/logs/*

# 清空 cron.log（如果太大）
> .olav/logs/cron.log
```

### 日志轮转（可选）

如果日志文件太大，配置 logrotate：

```bash
# /etc/logrotate.d/olav
/home/yhvh/Olav/.olav/logs/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
```

---

## 🔔 通知配置

### Slack Webhook

```bash
# 1. 创建 Slack Incoming Webhook
# https://api.slack.com/messaging/webhooks

# 2. 编辑脚本
nano scripts/daily_inspection.sh

# 3. 配置
ENABLE_NOTIFICATION=true
WEBHOOK_URL="https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX"

# 4. 测试
./scripts/daily_inspection.sh
```

**通知格式**:
```
🤖 OLAV Inspection [SUCCESS]: 
✅ Healthy: 5 devices
⚠️  Warning: 1 device (R1 - CPU 62%)
```

### Teams Webhook

类似 Slack，但格式略有不同：

```bash
WEBHOOK_URL="https://outlook.office.com/webhook/xxx"
```

### Email 通知

```bash
# 使用 mailx 或 sendmail
# 编辑 daily_inspection.sh，添加：

send_email() {
    local subject="$1"
    local body="$2"
    echo "$body" | mail -s "$subject" admin@example.com
}
```

---

## 🎯 最佳实践

### 1. 测试先行

```bash
# 在安装 cron 前，先手动测试脚本
./scripts/daily_inspection.sh

# 检查输出是否正确
ls -la .olav/logs/
ls -la exports/reports/snapshots/
```

### 2. 监控初期执行

```bash
# Cron 安装后的第一周，每天检查日志
tail -50 .olav/logs/cron.log

# 确保没有错误
grep -i error .olav/logs/cron.log
```

### 3. 定期审查报告

```bash
# 查看最近 7 天的报告
ls -lt exports/reports/snapshots/ | head -8

# 对比趋势
for i in {1..7}; do
  date=$(date -d "$i days ago" +%Y%m%d)
  echo "=== $date ==="
  grep -E "Summary|Healthy|Warning" exports/reports/snapshots/${date}.md 2>/dev/null || echo "No report"
done
```

### 4. 备份策略

```bash
# 每周自动备份（已包含在 cron 中）
0 2 * * 0 cd $OLAV_HOME && uv run olav admin backup

# 手动备份（重要操作前）
uv run olav admin backup

# 验证备份
ls -lh .olav/backups/
```

---

## 📝 脚本维护

### 更新脚本

```bash
# 直接编辑
nano scripts/daily_inspection.sh

# 或使用你喜欢的编辑器
code scripts/daily_inspection.sh
```

### 重新安装 Cron

```bash
# 更新脚本后，重新安装 cron
./scripts/install_cron.sh

# Cron 会自动使用最新的脚本
```

### 版本管理

```bash
# 脚本纳入 Git 版本控制
git add scripts/
git commit -m "Update inspection script"

# 如果修改失败，回滚
git checkout scripts/daily_inspection.sh
```

---

## 🆘 支持

如果遇到问题：

1. **查看文档**: `docs/ADMIN_AND_CRON_DESIGN_v2.md`
2. **检查日志**: `.olav/logs/cron.log`
3. **手动测试**: `./scripts/daily_inspection.sh`
4. **查看 crontab**: `crontab -l`

---

**最后更新**: 2026-02-14  
**维护者**: OLAV Team
