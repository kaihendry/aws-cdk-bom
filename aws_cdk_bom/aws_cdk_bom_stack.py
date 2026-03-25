import aws_cdk as cdk
from constructs import Construct
from xirokampi_foo_construct import FooConstruct
from xirokampi_bar_construct import BarConstruct
from aws_cdk_bom.aspects import BomAspect

# Approved is a set of actual class objects.
# Importing them here means this file has a hard dependency on the approved packages —
# you cannot approve a construct you haven't installed.
APPROVED_CONSTRUCT_TYPES: set[type] = {FooConstruct, BarConstruct}


class AwsCdkBomStack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        FooConstruct(self, "Foo")
        BarConstruct(self, "Bar")

        cdk.Aspects.of(self).add(BomAspect(approved=APPROVED_CONSTRUCT_TYPES))
