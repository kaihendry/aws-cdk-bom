from importlib.metadata import version
from aws_cdk import aws_ssm as ssm
from constructs import Construct
from enterprise_constructs_base import EnterpriseConstruct


class BarConstruct(EnterpriseConstruct):
    CONSTRUCT_NAME    = "BarConstruct"
    CONSTRUCT_VERSION = version("enterprise-bar-construct")

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        param = ssm.StringParameter(
            self, "BarParam",
            parameter_name=f"/bom/bar/{construct_id}",
            string_value="bar-value",
            description=f"Managed by BarConstruct v{self.CONSTRUCT_VERSION}",
        )
        self.apply_metadata_to_resource(param.node.default_child)
