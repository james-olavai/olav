# Lab Agent Setup Guide

This guide walks through deploying ContainerLab on a remote host, exposing the REST API, and configuring OLAV to connect.

---

## Overview

```
OLAV Agent主机
    │  REST API (port 8080)
    ↓
CLAB服务器 (运行ContainerLab + API容器)
    │  Docker bridge网络 (管理平面)
    ↓
Lab节点 (SRL容器)
    ← exec API推送sr_cli配置 (enter candidate → commit now)
```

步骤：
0. **用户与SSH配置**（推荐）
1. 安装ContainerLab
2. 启动ContainerLab REST API容器
3. 创建Docker bridge网络（固定网段）
4. 配置OLAV config文件
5. 验证连通性

---

## Step 0 — 用户与SSH密钥配置

### 0.1 在CLAB服务器创建专用用户（可选）

```bash
sudo adduser olav
sudo usermod -aG docker olav
sudo passwd olav
```

### 0.2 在Agent主机配置SSH免密登录

```bash
ssh-keygen -t ed25519 -C "olav-agent"
ssh-copy-id olav@<clab_server_ip>
# 验证
ssh olav@<clab_server_ip>
```

---

## Step 1 — 安装ContainerLab

在CLAB服务器上执行：

```bash
bash -c "$(curl -sL https://get.containerlab.dev)"
clab version
```

> 如未安装Docker：
> ```bash
> curl -fsSL https://get.docker.com | sh
> sudo usermod -aG docker $USER
> ```

---

## Step 2 — 启动ContainerLab REST API容器

OLAV通过 [clab-api-server](https://github.com/srl-labs/clab-api-server) 管理实验室。

```bash
docker run -d \
  --name clab-api-server \
  --privileged \
  --network host \
  --pid host \
  --restart unless-stopped \
  -e LOG_LEVEL=debug \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/run/netns:/var/run/netns \
  -v /var/lib/docker/containers:/var/lib/docker/containers \
  -v /etc/passwd:/etc/passwd:ro \
  -v /etc/shadow:/etc/shadow:ro \
  -v /etc/group:/etc/group:ro \
  -v /etc/gshadow:/etc/gshadow:ro \
  -v /home:/home \
  ghcr.io/srl-labs/clab-api-server/clab-api-server:latest

# 验证
curl http://localhost:8080/api/v1/version
```

放行防火墙（外部访问需要）：
```bash
sudo ufw allow 8080/tcp
```

---

## Step 3 — 创建Docker bridge网络

预先创建固定网段的管理网络，避免每次lab部署后网段变化：

```bash
docker network create \
  --driver bridge \
  --subnet 172.20.20.0/24 \
  --gateway 172.20.20.1 \
  --opt com.docker.network.bridge.name=br-olav \
  olav-mgmt

# 验证
docker network inspect olav-mgmt \
  --format '{{range .IPAM.Config}}Subnet: {{.Subnet}}  Gateway: {{.Gateway}}{{end}}'
```

---

## Step 4 — 配置OLAV

### 4.1 编辑config文件

编辑 `.olav/workspace/ops/lab/config/config.json`：

```json
{
  "base_url": "http://<clab_server_ip>:8080",
  "username": "olav",
  "password": "<Step 0设置的密码>"
}
```

**实际示例：**
```json
{
  "base_url": "http://192.168.100.12:8080",
  "username": "olav",
  "password": "olav123"
}
```

### 4.2 添加静态路由（Agent主机 → lab节点管理网段）

```bash
# 临时（重启失效）
sudo ip route add 172.20.20.0/24 via <clab_server_ip> dev <outbound_iface>

# 示例
sudo ip route add 172.20.20.0/24 via 192.168.100.12 dev eth0

# 验证
ip route show | grep 172.20.20
```

**永久保存（Ubuntu/Debian netplan）：**
```yaml
# /etc/netplan/01-netcfg.yaml — 在对应网卡下添加：
routes:
  - to: 172.20.20.0/24
    via: 192.168.100.12
```
```bash
sudo netplan apply
```

### 4.3 验证连通性

```bash
# REST API可达
curl http://<clab_server_ip>:8080/api/v1/version

# lab节点管理IP可达（需先部署一个lab）
ping -c 3 172.20.20.2
```

---

## Step 5 — 确认topology YAML使用olav-mgmt网络

OLAV生成的topology自动包含：

```yaml
name: olav-lab
mgmt:
  network: olav-mgmt
  ipv4-subnet: 172.20.20.0/24
  ipv4-gw: 172.20.20.1

topology:
  defaults:
    kind: srl
    image: ghcr.io/nokia/srlinux:latest
  nodes:
    R1: {}
    R2: {}
  links:
    - endpoints: ["R1:ethernet-1/1", "R2:ethernet-1/1"]
```

节点管理IP从 `172.20.20.0/24` 顺序分配（R1=172.20.20.2，R2=172.20.20.3，以此类推）。

---

## 快速检查清单

```
□ CLAB服务器：ContainerLab已安装 (clab version)
□ CLAB服务器：Docker已运行 (docker ps)
□ CLAB服务器：olav-mgmt网络已创建 (docker network inspect olav-mgmt)
□ CLAB服务器：clab-api-server容器运行中 (docker ps | grep clab-api-server)
□ CLAB服务器：8080端口防火墙已放行
□ Agent主机：.olav/workspace/ops/lab/config/config.json 已填写
□ Agent主机：静态路由已添加 (ip route show | grep 172.20.20)
□ Agent主机：REST API可达 (curl http://<clab_server_ip>:8080/api/v1/version)
```

---

## 故障排查

**REST API超时**
- 检查容器状态：`docker ps | grep clab-api-server`
- 检查防火墙：`sudo ufw status`

**ping到lab节点不通**
- 确认静态路由：`ip route show | grep 172.20.20`
- 确认IP转发：`sysctl net.ipv4.ip_forward`（应为1）

**exec API返回错误**
- 确认lab名称正确：`curl -H "Authorization: Bearer <token>" http://<url>/api/v1/labs`
- 节点名称区分大小写（与topology YAML中一致）
- SRL节点未完全启动：等待30-60秒后重试
