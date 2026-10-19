from .aruba_central import ArubaCentralDriver
from .base import Driver, DriverError
from .meraki import MerakiDriver
from .mock import MockDriver
from .ruckus_smartzone import RuckusSmartZoneDriver

# Para suportar um novo vendor: crie um Driver e registre aqui.
REGISTRY: dict[str, type[Driver]] = {
    d.vendor: d for d in (MerakiDriver, ArubaCentralDriver, RuckusSmartZoneDriver, MockDriver)
}

__all__ = ["REGISTRY", "Driver", "DriverError"]
