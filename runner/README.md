# Self-hosted GitHub Actions Runner

国内服务器部署 GitHub Actions Runner，避免上交所 API 封锁云服务器 IP。

## 快速开始

### 1. 生成 Runner Token

打开浏览器访问：
```
https://github.com/menglingjie/aetftrace/settings/actions/runners
```

点击 **"New self-hosted runner"**，页面会显示一个 token，类似：
```
./config.sh --url https://github.com/menglingjie/aetftrace --token AXBxxxxxxxxxxxxx
```

复制 `--token` 后面的值。

### 2. 配置环境变量

```bash
cd runner/
cp .env.example .env
```

编辑 `.env`，填入实际的 token 和数据库连接串：
```
RUNNER_TOKEN=AXBxxxxxxxxxxxxx（替换为步骤1获取的token）
DATABASE_URL=postgresql://...
```

### 3. 启动

```bash
docker compose up -d --build
```

查看日志：
```bash
docker compose logs -f
```

看到 `Listening for Jobs` 表示 runner 已就绪。

### 4. 修改 GitHub Workflow

将 `.github/workflows/fetch_etf.yml` 中的 `runs-on` 改为：

```yaml
runs-on: self-hosted
```

### 5. 手动触发测试

在 GitHub 仓库页面 Actions → Fetch ETF Data → Run workflow 测试。

## 注意事项

- Runner token 只在注册时需要，注册后 runner 会自动获取新的 token
- 如果 `docker compose logs` 显示 runner 掉线，删除容器重新 `docker compose up -d` 即可
- 数据库和 git 操作会在 runner 所在服务器本地执行，确保服务器有 git 和网络访问
