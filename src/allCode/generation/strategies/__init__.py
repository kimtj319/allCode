"""Built-in generation strategies."""

from allCode.generation.strategies.generic import GenericFileStrategy
from allCode.generation.strategies.go import GoStrategy
from allCode.generation.strategies.java import JavaStrategy
from allCode.generation.strategies.node import NodeTypeScriptStrategy
from allCode.generation.strategies.python import PythonProjectStrategy
from allCode.generation.strategies.rust import RustStrategy
from allCode.generation.strategy import StrategyRegistry


def default_strategy_registry() -> StrategyRegistry:
    return StrategyRegistry(
        [
            PythonProjectStrategy(),
            NodeTypeScriptStrategy(),
            GoStrategy(),
            RustStrategy(),
            JavaStrategy(),
            GenericFileStrategy(),
        ]
    )
