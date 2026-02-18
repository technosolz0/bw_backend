#!/bin/bash

# Configuration
API_URL="http://127.0.0.1:8000"
API_KEY="SUPER@SECRET@KEY@32"

echo "1. Getting App Status..."
curl -X GET "$API_URL/app-status"
echo -e "\n"

echo "2. Toggling Maintenance Mode (ON)..."
curl -X POST "$API_URL/admin/toggle-maintenance" \
     -H "Content-Type: application/json" \
     -H "x-api-key: $API_KEY" \
     -d '{"status": true}'
echo -e "\n"

echo "3. Toggling Log Store (OFF)..."
curl -X POST "$API_URL/admin/toggle-log-store" \
     -H "Content-Type: application/json" \
     -H "x-api-key: $API_KEY" \
     -d '{"status": false}'
echo -e "\n"

echo "4. Attempting to Store Log (Should fail because Log Store is OFF)..."
curl -X POST "$API_URL/store-log" \
     -H "Content-Type: application/json" \
     -H "x-api-key: $API_KEY" \
     -d '{"user_id": "user123", "device_info": "iPhone 13", "message": "Test log message"}'
echo -e "\n"

echo "5. Toggling Log Store (ON)..."
curl -X POST "$API_URL/admin/toggle-log-store" \
     -H "Content-Type: application/json" \
     -H "x-api-key: $API_KEY" \
     -d '{"status": true}'
echo -e "\n"

echo "6. Storing Log (Should succeed)..."
curl -X POST "$API_URL/store-log" \
     -H "Content-Type: application/json" \
     -H "x-api-key: $API_KEY" \
     -d '{"user_id": "user123", "device_info": "iPhone 13", "message": "Test log message"}'
echo -e "\n"
