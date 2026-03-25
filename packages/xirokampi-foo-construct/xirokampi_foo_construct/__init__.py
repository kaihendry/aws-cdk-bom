from aws_cdk import aws_ssm as ssm
from constructs import Construct
from xirokampi_constructs_base import XirokampiConstruct


class FooConstruct(XirokampiConstruct):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        ssm.StringParameter(
            self, "FooParam",
            parameter_name=f"/xirokampi/foo/{construct_id}",
            string_value="foo-value",
            description=f"Managed by {self.construct_id}",
        )
