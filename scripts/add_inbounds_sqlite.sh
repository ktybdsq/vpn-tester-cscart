#!/bin/bash
# Добавление тестовых inbound напрямую в базу 3x-ui

SERVER="mrfirst.simtechdev.us"

# Генерация UUID
UUID1="875c2ae5-17b5-40c7-8266-54600467c57b"
UUID2="c0d4e031-9d30-4b8f-b312-7cc535b0f754"
UUID3="26e313ee-ad83-4320-9115-b1bdfaf479da"

# Private Keys для REALITY
PRIV_KEY1="u5w3N9q2Y7mK8pL4vR6tJ1hF0dS5bA3cG9eX2nW7zQ4="
PRIV_KEY2="v6x4O0r3Z8nL9qM5wS7uK2iG1eT6cB4dH0fY3oX8aR5="
PRIV_KEY3="w7y5P1s4A9oM0rN6xT8vL3jH2fU7dC5eI1gZ4pY9bS6="

# Short IDs
SID1="a1b2c3d4e5f67890"
SID2="b2c3d4e5f6g78901"
SID3="c3d4e5f6g7h89012"

echo "🔧 Добавление тестовых inbound в базу 3x-ui..."

# Конфиг 1: microsoft.com + chrome + 32000
ssh root@$SERVER "docker exec 3x-ui sqlite3 /etc/x-ui/x-ui.db \"INSERT INTO inbounds (user_id, up, down, total, remark, enable, expiry_time, listen, port, protocol, settings, stream_settings, tag, sniffing) VALUES (
  1, 0, 0, 0, 'TEST-microsoft-chrome-32000', 1, 0, '', 32000, 'vless',
  '{\\\"clients\\\":[{\\\"id\\\":\\\"$UUID1\\\",\\\"flow\\\":\\\"xtls-rprx-vision\\\",\\\"email\\\":\\\"test1@cscart\\\"}]}',
  '{\\\"network\\\":\\\"tcp\\\",\\\"security\\\":\\\"reality\\\",\\\"realitySettings\\\":{\\\"show\\\":false,\\\"dest\\\":\\\"microsoft.com:443\\\",\\\"serverNames\\\":[\\\"microsoft.com\\\"],\\\"privateKey\\\":\\\"$PRIV_KEY1\\\",\\\"shortIds\\\":[\\\"\\\",\\\"$SID1\\\"]}}',
  'vless-32000',
  '{\\\"enabled\\\":true,\\\"destOverride\\\":[\\\"http\\\",\\\"tls\\\"]}'
);\""

# Конфиг 2: microsoft.com + firefox + 32001
ssh root@$SERVER "docker exec 3x-ui sqlite3 /etc/x-ui/x-ui.db \"INSERT INTO inbounds (user_id, up, down, total, remark, enable, expiry_time, listen, port, protocol, settings, stream_settings, tag, sniffing) VALUES (
  1, 0, 0, 0, 'TEST-microsoft-firefox-32001', 1, 0, '', 32001, 'vless',
  '{\\\"clients\\\":[{\\\"id\\\":\\\"$UUID2\\\",\\\"flow\\\":\\\"xtls-rprx-vision\\\",\\\"email\\\":\\\"test2@cscart\\\"}]}',
  '{\\\"network\\\":\\\"tcp\\\",\\\"security\\\":\\\"reality\\\",\\\"realitySettings\\\":{\\\"show\\\":false,\\\"dest\\\":\\\"microsoft.com:443\\\",\\\"serverNames\\\":[\\\"microsoft.com\\\"],\\\"privateKey\\\":\\\"$PRIV_KEY1\\\",\\\"shortIds\\\":[\\\"\\\",\\\"$SID2\\\"]}}',
  'vless-32001',
  '{\\\"enabled\\\":true,\\\"destOverride\\\":[\\\"http\\\",\\\"tls\\\"]}'
);\""

# Конфиг 3: apple.com + chrome + 32002
ssh root@$SERVER "docker exec 3x-ui sqlite3 /etc/x-ui/x-ui.db \"INSERT INTO inbounds (user_id, up, down, total, remark, enable, expiry_time, listen, port, protocol, settings, stream_settings, tag, sniffing) VALUES (
  1, 0, 0, 0, 'TEST-apple-chrome-32002', 1, 0, '', 32002, 'vless',
  '{\\\"clients\\\":[{\\\"id\\\":\\\"$UUID3\\\",\\\"flow\\\":\\\"xtls-rprx-vision\\\",\\\"email\\\":\\\"test3@cscart\\\"}]}',
  '{\\\"network\\\":\\\"tcp\\\",\\\"security\\\":\\\"reality\\\",\\\"realitySettings\\\":{\\\"show\\\":false,\\\"dest\\\":\\\"apple.com:443\\\",\\\"serverNames\\\":[\\\"apple.com\\\"],\\\"privateKey\\\":\\\"$PRIV_KEY2\\\",\\\"shortIds\\\":[\\\"\\\",\\\"$SID3\\\"]}}',
  'vless-32002',
  '{\\\"enabled\\\":true,\\\"destOverride\\\":[\\\"http\\\",\\\"tls\\\"]}'
);\""

echo "✅ Inbounds добавлены!"
echo ""
echo "📋 Тестовые конфиги:"
echo "  Port 32000: microsoft.com + chrome (UUID: $UUID1)"
echo "  Port 32001: microsoft.com + firefox (UUID: $UUID2)"
echo "  Port 32002: apple.com + chrome (UUID: $UUID3)"
echo ""
echo "⏳ Перезапуск Xray для применения..."
ssh root@$SERVER "docker restart 3x-ui"
sleep 5
echo "✅ Готово!"
