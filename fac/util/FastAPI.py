
from fastapi import APIRouter
from functools import wraps

def route(path: str, methods: list[str], response_model=None):
    def decorator(func):
        func._api_route = (path, methods, response_model)
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator

class Routable:
    def __init__(self):
        self.router = APIRouter()

        # Auto-register decorated methods
        for name in dir(self):
            method = getattr(self, name)
            if hasattr(method, '_api_route'):
                path, methods, response_model = method._api_route
                self.router.add_api_route(path, method, methods=methods, response_model=response_model)

