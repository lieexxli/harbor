#!/bin/bash

# Pre-install MCP server libraries so agent's server.py can import them
pip install mcp==1.16.0 fastmcp==2.12.5 --quiet

# Install test deps and run
pip install pytest==8.4.1 pytest-json-ctrf==0.3.5 --quiet

pytest --ctrf /logs/verifier/ctrf.json /tests/test_server.py -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
