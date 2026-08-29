"""API route definitions."""

ROUTES = [
    {"path": "/users", "method": "GET", "summary": "List all users"},
    {"path": "/users", "method": "POST", "summary": "Create user"},
    {"path": "/users/{id}", "method": "GET", "summary": "Get user by ID"},
    {"path": "/users/{id}", "method": "DELETE", "summary": "Delete user account"},
]
