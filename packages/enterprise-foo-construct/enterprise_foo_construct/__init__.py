from importlib.metadata import version
from aws_cdk import aws_ssm as ssm
from constructs import Construct
from enterprise_constructs_base import EnterpriseConstruct


class FooConstruct(EnterpriseConstruct):
    CONSTRUCT_NAME    = "FooConstruct"
    CONSTRUCT_VERSION = version("enterprise-foo-construct")

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        param = ssm.StringParameter(
            self, "FooParam",
            parameter_name=f"/bom/foo/{construct_id}",
            string_value="foo-value",
            description=f"Managed by FooConstruct v{self.CONSTRUCT_VERSION}",
        )
        self.apply_metadata_to_resource(param.node.default_child)
