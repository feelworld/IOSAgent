#!/bin/bash
CONTAINER=$(docker ps --filter 'name=web' --format '{{.Names}}' | head -1)
echo "Container: $CONTAINER"
docker cp /tmp/apple_accounts.py $CONTAINER:/app/server/src/api/apple_accounts.py
docker cp /tmp/apple_account_service.py $CONTAINER:/app/server/src/services/apple_account_service.py
docker cp /tmp/command_dispatcher.py $CONTAINER:/app/server/src/services/command_dispatcher.py
docker cp /tmp/client_handler.py $CONTAINER:/app/server/src/ws/client_handler.py
docker restart $CONTAINER
echo "Server restarted"
