import aws_cdk as cdk
from constructs import Construct
from xirokampi_utils import FooConstruct, BarConstruct
from aws_cdk_bom.aspects import BomAspect


class AwsCdkBomStack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        FooConstruct(self, "Foo")
        BarConstruct(self, "Bar")

        cdk.Aspects.of(self).add(BomAspect())
