#!/bin/bash
# 安全重启证小安服务：按端口精确定位 PID，避免 pkill/命令行自伤
set -u
PIDS=$(netstat -tlnp 2>/dev/null | grep ':3000 ' | grep -oE '[0-9]+/python3' | cut -d/ -f1 | sort -u)
for p in $PIDS; do
  kill -9 "$p" 2>/dev/null || true
done
sleep 1
cd /workspace/zhengxiaoan || exit 1
PORT=3000 setsid nohup /root/.pyenv/versions/3.11.1/bin/python3 server.py \
  > /tmp/zx_server.log 2>&1 < /dev/null &
sleep 4
if netstat -tlnp 2>/dev/null | grep -q ':3000 '; then
  echo "服务已启动，端口 3000 监听中"
  curl -s -o /dev/null -w "GET / -> %{http_code}\n" --max-time 8 http://127.0.0.1:3000/
else
  echo "启动失败，日志："
  tail -15 /tmp/zx_server.log
fi
