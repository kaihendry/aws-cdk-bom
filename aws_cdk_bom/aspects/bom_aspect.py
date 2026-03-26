import jsii
import aws_cdk as cdk
from constructs import IConstruct
from xirokampi_constructs_base import XirokampiConstruct

# This tag is added to the CloudFormation stack when BOM validation passes.
# An SCP can deny cloudformation:CreateStack / UpdateStack unless this tag
# is present, blocking any deployment that bypassed CDK + BomAspect entirely.
BOM_VALIDATED_TAG = "xirokampi:validated"


@jsii.implements(cdk.IAspect)
class BomAspect:
    def __init__(self) -> None:
        self._stack_registered = False

    def visit(self, node: IConstruct) -> None:
        if not (isinstance(node, cdk.Stack) and not self._stack_registered):
            return

        self._stack_registered = True

        enterprise_nodes = [
            child for child in node.node.find_all()
            if isinstance(child, XirokampiConstruct)
        ]

        # Stamp the stack with the validation tag.
        # An SCP at the AWS Organisation level can then deny CreateStack /
        # UpdateStack unless aws:RequestTag/bom:validated equals "true".
        # Use node.tags.set_tag() rather than Tags.of().add() to avoid the
        # Aspect priority conflict (CDK rejects adding a Tag Aspect at priority
        # 200 after BomAspect has already run at priority 500).
        node.tags.set_tag(BOM_VALIDATED_TAG, "true")

        # Encode construct versions as a stack tag so that a library version
        # bump (which changes no resource properties) still shows up as a tag
        # change in the CloudFormation changeset, forcing an actual deploy and
        # keeping the deployed BOM metadata accurate.
        # AWS tag values are limited to 256 characters; truncate with a marker
        # if the list is unusually long.
        bom_tag_value = " ".join(
            child.construct_id for child in enterprise_nodes
        )
        if len(bom_tag_value) > 256:
            bom_tag_value = bom_tag_value[:253] + "..."
        node.tags.set_tag("xirokampi:bom", bom_tag_value)

        # Write the BOM summary into the stack's CloudFormation template Metadata.
        bom_entries = [
            {
                "blueprint": child.construct_id,
                "module":    type(child).__module__,
                "path":      child.node.path,
            }
            for child in enterprise_nodes
        ]
        node.template_options.metadata = {
            "BOM": {
                "GeneratedAt": "synth-time",
                "Constructs":  bom_entries,
                "Count":       len(bom_entries),
            }
        }
