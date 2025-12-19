# Contributing to Houdini MCP

Thank you for your interest in contributing to Houdini MCP!

## Development Setup

### Prerequisites

- Python 3.10+
- SideFX Houdini (for integration testing)
- Git

### Initial Setup

```bash
# Clone the repository
git clone https://github.com/oculairmedia/houdini-mcp.git
cd houdini-mcp

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or .venv\Scripts\activate  # Windows

# Install with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
pre-commit install --hook-type pre-push
```

## Development Workflow

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=houdini_mcp --cov-report=term-missing

# Run specific test file
pytest tests/test_connection.py

# Run specific test
pytest tests/test_tools.py::TestCreateNode::test_create_node_success
```

### Code Quality

```bash
# Format code
ruff format .

# Lint code
ruff check .

# Auto-fix lint issues
ruff check --fix .

# Type checking
mypy houdini_mcp/

# Security scan
bandit -r houdini_mcp/ -c pyproject.toml
```

### Pre-commit Hooks

Pre-commit hooks run automatically on commit. To run manually:

```bash
# Run all hooks on all files
pre-commit run --all-files

# Run specific hook
pre-commit run ruff --all-files
```

## Testing with Live Houdini

### Start Houdini RPC Server

In Houdini's Python shell:

```python
import hrpyc
hrpyc.start_server(port=18811)
```

### Run Integration Tests

```bash
HOUDINI_HOST=localhost HOUDINI_PORT=18811 python -c "
from houdini_mcp.tools import get_scene_info
print(get_scene_info('localhost', 18811))
"
```

## Code Style

- Use [Ruff](https://docs.astral.sh/ruff/) for formatting and linting
- Follow [PEP 8](https://pep8.org/) style guidelines
- Maximum line length: 100 characters
- Use type hints for function signatures
- Write docstrings for public functions

### Example

```python
def create_node(
    node_type: str,
    parent_path: str = "/obj",
    name: Optional[str] = None,
    host: str = "localhost",
    port: int = 18811
) -> Dict[str, Any]:
    """
    Create a new node in the Houdini scene.
    
    Args:
        node_type: The type of node to create (e.g., "geo", "sphere")
        parent_path: The parent node path (default: "/obj")
        name: Optional name for the new node
        host: Houdini server hostname
        port: Houdini RPC port
        
    Returns:
        Dict with created node information or error details.
    """
    ...
```

## Pull Request Process

1. **Fork** the repository
2. Create a **feature branch** (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. **Run tests** (`pytest`)
5. **Commit** with descriptive message (`git commit -m 'Add amazing feature'`)
6. **Push** to your fork (`git push origin feature/amazing-feature`)
7. Open a **Pull Request**

### PR Guidelines

- Reference any related issues
- Include tests for new functionality
- Update documentation if needed
- Ensure CI passes

## Reporting Issues

- Use GitHub Issues
- Include Houdini version
- Include Python version
- Provide minimal reproduction steps
- Include full error traceback

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
