from typing import List, Optional
from protocols.messages import Capabilities, copy_model


class CapabilityManager:
    """
    Manages agent capabilities, payload capacities, and supported operations.
    """

    def __init__(
        self,
        capabilities: Optional[List[str]] = None,
        payload_capacity_kg: float = 0.0,
        supported_operations: Optional[List[str]] = None,
    ):
        self._capabilities = Capabilities(
            capabilities=capabilities or [],
            payload_capacity_kg=payload_capacity_kg,
            supported_operations=supported_operations or [],
        )

    @property
    def capabilities(self) -> List[str]:
        return self._capabilities.capabilities

    @property
    def payload_capacity_kg(self) -> float:
        return self._capabilities.payload_capacity_kg

    @property
    def supported_operations(self) -> List[str]:
        return self._capabilities.supported_operations

    def has_capability(self, capability: str) -> bool:
        return self._capabilities.can_perform(capability)

    def can_carry(self, weight_kg: float) -> bool:
        return self._capabilities.can_carry(weight_kg)

    def supports_operation(self, operation: str) -> bool:
        return operation in self._capabilities.supported_operations

    def add_capability(self, capability: str) -> None:
        if capability not in self._capabilities.capabilities:
            self._capabilities.capabilities.append(capability)

    def to_model(self) -> Capabilities:
        return copy_model(self._capabilities)
