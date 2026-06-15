#!/bin/bash
pip install fastmcp==2.12.5 --quiet

cat > /app/server.py << 'EOF'
from fastmcp import FastMCP

mcp = FastMCP("tool-server")


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


@mcp.tool()
def reverse(text: str) -> str:
    """Reverse a string."""
    return text[::-1]


@mcp.tool()
def count_words(text: str) -> int:
    """Count whitespace-delimited words."""
    return len(text.split())


if __name__ == "__main__":
    mcp.run(transport="stdio")
EOF
