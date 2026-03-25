from importlib.metadata import version, PackageNotFoundError
from aws_cdk import Tags
from constructs import Construct

XIROKAMPI_CONSTRUCT_TAG = "xirokampi:construct"


class XirokampiConstruct(Construct):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # Derive the package name from the module: "xirokampi_foo_construct" → "xirokampi-foo-construct"
        pkg = type(self).__module__.split(".")[0].replace("_", "-")
        try:
            ver = version(pkg)
        except PackageNotFoundError:
            ver = "unknown"
        self.construct_id = f"{type(self).__name__}@{ver}"
        Tags.of(self).add(XIROKAMPI_CONSTRUCT_TAG, self.construct_id)
