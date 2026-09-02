from abc import ABC, abstractmethod


class DeployProvider(ABC):
    name: str = "base"
    label: str = "Base"

    @abstractmethod
    def get_builtin_checks(self) -> list[dict]:
        pass

    @abstractmethod
    def preflight_check(self, check_id: str) -> tuple[bool, str]:
        pass

    @abstractmethod
    def deploy(self) -> tuple[bool, str]:
        pass

    @abstractmethod
    def rollback(self) -> tuple[bool, str]:
        pass

    @abstractmethod
    def health_check(self) -> tuple[bool, str]:
        pass

    def get_health_monitor(self) -> dict:
        return {}
