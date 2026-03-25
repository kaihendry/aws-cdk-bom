from aws_cdk import Tags
from constructs import Construct

ENTERPRISE_CONSTRUCT_TAG = "enterprise:construct-name"
ENTERPRISE_VERSION_TAG   = "enterprise:construct-version"


class EnterpriseConstruct(Construct):
    CONSTRUCT_NAME: str
    CONSTRUCT_VERSION: str

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        Tags.of(self).add(ENTERPRISE_CONSTRUCT_TAG, self.CONSTRUCT_NAME)
        Tags.of(self).add(ENTERPRISE_VERSION_TAG,   self.CONSTRUCT_VERSION)
        self.node.add_metadata("enterprise:construct-name",    self.CONSTRUCT_NAME)
        self.node.add_metadata("enterprise:construct-version", self.CONSTRUCT_VERSION)

    def apply_metadata_to_resource(self, cfn_resource) -> None:
        if cfn_resource is not None:
            cfn_resource.cfn_options.metadata = {
                "Enterprise": {
                    "construct-name":    self.CONSTRUCT_NAME,
                    "construct-version": self.CONSTRUCT_VERSION,
                }
            }
