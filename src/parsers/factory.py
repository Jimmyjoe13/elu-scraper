from typing import Type, Dict, TypeVar
from src.parsers.base import BaseParser

P = TypeVar("P", bound=BaseParser)

class ParserFactory:
    _registry: Dict[str, Type[BaseParser]] = {}

    @classmethod
    def register(cls, template_name: str):
        def decorator(parser_class: Type[P]) -> Type[P]:
            cls._registry[template_name] = parser_class
            return parser_class
        return decorator

    @classmethod
    def get_parser(cls, template_name: str, url: str, ville_ou_secteur: str) -> BaseParser:
        parser_class = cls._registry.get(template_name)
        if not parser_class:
            raise ValueError(f"Template '{template_name}' inconnu dans la factory. A-t-il été importé ?")
        return parser_class(url, ville_ou_secteur)
