#!/bin/bash
# Массовое добавление тестовых inbound на mrfirst.simtechdev.us
# Через 3x-ui API

SERVER="mrfirst.simtechdev.us"
USER="root"

# Генерация UUID для тестов
UUID1=$(cat /proc/sys/kernel/random/uuid)
UUID2=$(cat /proc/sys/kernel/random/uuid)
UUID3=$(cat /proc/sys/kernel/random/uuid)

echo "🔧 Adding test inbound configs to $SERVER..."

# Конфиг 1: microsoft.com + chrome + 32000
ssh $USER@$SERVER "curl -s -X POST 'http://localhost:54321/inbound/add' -H 'Content-Type: application/json' -d '{
  \"port\": 32000,
  \"protocol\": \"vless\",
  \"settings\": \"{\\\"clients\\\":[{\\\"id\\\":\\\"$UUID1\\\",\\\"flow\\\":\\\"xtls-rprx-vision\\\"}]}\",
  \"streamSettings\": \"{\\\"network\\\":\\\"tcp\\\",\\\"security\\\":\\\"reality\\\",\\\"realitySettings\\\":{\\\"target\\\":\\\"microsoft.com:443\\\",\\\"serverNames\\\":[\\\"microsoft.com\\\"],\\\"privateKey\\\":\\\"u5w3N9q2Y7mK8pL4vR6tJ1hF0dS5bA3cG9eX2nW7zQ4=\\\",\\\"shortIds\\\":[\\\"\\\",\\\"a1b2c3d4e5f67890\\\"]}}\",
  \"sniffing\": \"{\\\"enabled\\\":true,\\\"destOverride\\\":[\\\"http\\\",\\\"tls\\\"]}\"
}'"

# Конфиг 2: microsoft.com + firefox + 32001
ssh $USER@$SERVER "curl -s -X POST 'http://localhost:54321/inbound/add' -H 'Content-Type: application/json' -d '{
  \"port\": 32001,
  \"protocol\": \"vless\",
  \"settings\": \"{\\\"clients\\\":[{\\\"id\\\":\\\"$UUID2\\\",\\\"flow\\\":\\\"xtls-rprx-vision\\\"}]}\",
  \"streamSettings\": \"{\\\"network\\\":\\\"tcp\\\",\\\"security\\\":\\\"reality\\\",\\\"realitySettings\\\":{\\\"target\\\":\\\"microsoft.com:443\\\",\\\"serverNames\\\":[\\\"microsoft.com\\\"],\\\"privateKey\\\":\\\"u5w3N9q2Y7mK8pL4vR6tJ1hF0dS5bA3cG9eX2nW7zQ4=\\\",\\\"shortIds\\\":[\\\"\\\",\\\"b2c3d4e5f6g78901\\\"]}}\",
  \"sniffing\": \"{\\\"enabled\\\":true,\\\"destOverride\\\":[\\\"http\\\",\\\"tls\\\"]}\"
}'"

# Конфиг 3: apple.com + chrome + 32002
ssh $USER@$SERVER "curl -s -X POST 'http://localhost:54321/inbound/add' -H 'Content-Type: application/json' -d '{
  \"port\": 32002,
  \"protocol\": \"vless\",
  \"settings\": \"{\\\"clients\\\":[{\\\"id\\\":\\\"$UUID3\\\",\\\"flow\\\":\\\"xtls-rprx-vision\\\"}]}\",
  \"streamSettings\": \"{\\\"network\\\":\\\"tcp\\\",\\\"security\\\":\\\"reality\\\",\\\"realitySettings\\\":{\\\"target\\\":\\\"apple.com:443\\\",\\\"serverNames\\\":[\\\"apple.com\\\"],\\\"privateKey\\\":\\\"v6x4O0r3Z8nL9qM5wS7uK2iG1eT6cB4dH0fY3oX8aR5=\\\",\\\"shortIds\\\":[\\\"\\\",\\\"c3d4e5f6g7h89012\\\"]}}\",
  \"sniffing\": \"{\\\"enabled\\\":true,\\\"destOverride\\\":[\\\"http\\\",\\\"tls\\\"]}\"
}'"

echo "✅ Test inbounds added!"
echo "UUID1: $UUID1 (port 32000)"
echo "UUID2: $UUID2 (port 32001)"
echo "UUID3: $UUID3 (port 32002)"
